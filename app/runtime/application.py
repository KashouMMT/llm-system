import asyncio
from collections.abc import Coroutine
from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from typing_extensions import Self

from app.agent.checkpointer import create_checkpointer
from app.agent.context.conversation_context_builder import (
    ConversationContextBuilder,
)
from app.agent.context.history_context_builder import HistoryContextBuilder
from app.agent.context.summary_context_builder import SummaryContextBuilder
from app.agent.graph import AgentGraph
from app.agent.tools import TOOLS
from app.config.runtime_settings import (
    PERSISTED_FIELDS,
    RuntimeSettings,
    RuntimeSettingsHolder,
)
from app.config.settings import LLM_PROVIDER
from app.database.connection import create_pool
from app.database.init_db import initialize_database
from app.llm.llm_factory import LLMFactory
from app.llm.system_prompt import load_system_prompt
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.settings_repository import SettingsRepository
from app.repositories.summary_repository import SummaryRepository
from app.runtime.conversation_lock import ConversationLock
from app.runtime.event_bus import EventBus
from app.services.chat_service import ChatService
from app.services.summarization_service import SummarizationService
from app.utils.logger import logger, set_log_level

# How long shutdown waits for detached work before cancelling it.
#
# Not a wait for answers to finish — a generation can run for minutes,
# and no deploy should block on one. It is a short window for work that
# is nearly done, then a second window for cancelled work to persist
# what it already produced.
DRAIN_TIMEOUT_SECONDS = 3.0
CANCEL_TIMEOUT_SECONDS = 5.0


async def _drain_tasks(tasks: set[asyncio.Task], label: str) -> None:
    """
    Wait briefly for detached tasks, then cancel whatever is left.

    Cancelling is not data loss here: ChatService.generate treats
    cancellation as a terminal state and still writes the partial answer
    from its finally block. Summarization is safe to cancel outright,
    since SummaryRepository commits the chunk and the watermark in one
    transaction — a cancelled run leaves no half-applied state.
    """
    pending = {task for task in tasks if not task.done()}

    if not pending:
        return

    logger.info(
        "Waiting for background tasks | kind=%s count=%s",
        label,
        len(pending),
    )

    _, unfinished = await asyncio.wait(
        pending,
        timeout=DRAIN_TIMEOUT_SECONDS,
    )

    if not unfinished:
        logger.info("Background tasks finished | kind=%s", label)
        return

    logger.warning(
        "Cancelling unfinished background tasks | kind=%s count=%s",
        label,
        len(unfinished),
    )

    for task in unfinished:
        task.cancel()

    # A cancelled generate() still needs the pool: its finally block
    # writes the partial answer. Give that write time to land before the
    # caller closes the pool underneath it.
    _, stuck = await asyncio.wait(
        pending,
        timeout=CANCEL_TIMEOUT_SECONDS,
    )

    if stuck:
        logger.error(
            "Background tasks did not stop | kind=%s count=%s",
            label,
            len(stuck),
        )


class Application:
    """
    Application runtime.

    Owns the lifecycle of the application's shared resources.
    """

    def __init__(self) -> None:
        self.llm = None
        self.system_prompt: str = ""

        self.checkpointer: AsyncPostgresSaver | None = None
        self._resources: AsyncExitStack | None = None

        self.agent_graph: AgentGraph | None = None
        self.conversation_context_builder: ConversationContextBuilder | None = None
        self.summary_context_builder: SummaryContextBuilder | None = None
        self.history_context_builder: HistoryContextBuilder | None = None

        # Unopened until initialize(); constructing it needs no event loop.
        self.pool = create_pool()

        self.conversation_repository = ConversationRepository(self.pool)
        self.message_repository = MessageRepository(self.pool)
        self.summary_repository = SummaryRepository(self.pool)
        self.settings_repository = SettingsRepository(self.pool)

        # Built from the environment before anything else, because
        # EventBus needs it now and the pool is not open yet. Persisted
        # overrides are layered on in initialize().
        self.runtime_settings = RuntimeSettingsHolder(
            RuntimeSettings.from_env(),
        )

        self.event_bus = EventBus(self.runtime_settings)
        self.conversation_lock = ConversationLock()

        self._background_tasks: set[asyncio.Task] = set()

        self.summarization_service: SummarizationService | None = None
        self.chat_service: ChatService | None = None

    async def initialize(self) -> None:
        """
        Initialize all application resources.

        If any later step fails, resources opened by earlier steps
        are still closed.
        """
        if self._resources is not None:
            raise RuntimeError("Application is already initialized.")

        logger.info("Application initialization started")

        self._resources = AsyncExitStack()

        try:
            logger.info("Initializing application database")
            initialize_database()
            logger.info("Application database initialized")

            logger.info("Opening PostgreSQL connection pool")
            await self.pool.open(wait=True)
            self._resources.push_async_callback(self.pool.close)
            logger.info("PostgreSQL connection pool ready")

            logger.info("Loading persisted settings")
            await self._load_persisted_settings()
            logger.info("Persisted settings loaded")

            # A previous process may have died mid-generation, leaving rows
            # that no task will ever finish.
            await self.message_repository.sweep_streaming()

            logger.info("Loading system prompt")
            # Loaded once here to fail fast on a bad SYSTEM_PROMPT and to
            # log its size. The agent node reloads it per turn, so this
            # value is not what the model actually receives.
            self.system_prompt = load_system_prompt(
                self.runtime_settings.current.system_prompt_name,
            )
            logger.info(
                "System prompt initialized | characters=%s",
                len(self.system_prompt),
            )

            logger.info("System prompt initialized")
            logger.debug(
                "System prompt prepared | characters=%s",
                len(self.system_prompt),
            )

            logger.info("Creating LLM")
            self.llm = LLMFactory.create()
            logger.info("LLM initialized")

            logger.info("Creating LangGraph PostgreSQL checkpointer")
            self.checkpointer = await self._resources.enter_async_context(
                create_checkpointer()
            )

            await self.checkpointer.setup()

            logger.info("LangGraph checkpointer initialized")

            logger.info("Creating summary context builder")
            self.summary_context_builder = SummaryContextBuilder(
                summary_repository=self.summary_repository,
            )
            logger.info("Summary context builder initialized")

            logger.info("Creating history context builder")
            self.history_context_builder = HistoryContextBuilder(
                message_repository=self.message_repository,
                settings=self.runtime_settings,
            )
            logger.info("History context builder initialized")

            logger.info("Creating conversation context builder")
            self.conversation_context_builder = ConversationContextBuilder(
                summary_context_builder=self.summary_context_builder,
                history_context_builder=self.history_context_builder,
            )
            logger.info("Conversation context builder initialized")

            logger.info("Creating AgentGraph")
            self.agent_graph = AgentGraph(
                llm=self.llm,
                settings=self.runtime_settings,
                provider=LLM_PROVIDER,
                tools=TOOLS,
                checkpointer=self.checkpointer,
                conversation_context_builder=(self.conversation_context_builder),
            )
            logger.info("AgentGraph initialized")

            logger.info("Creating summarization service")
            self.summarization_service = SummarizationService(
                llm=self.llm,
                message_repository=self.message_repository,
                summary_repository=self.summary_repository,
                settings=self.runtime_settings,
            )
            logger.info("Summarization service initialized")

            logger.info("Creating ChatService")
            self.chat_service = ChatService(
                agent_graph=self.agent_graph,
                conversation_repository=self.conversation_repository,
                message_repository=self.message_repository,
                summarization_service=self.summarization_service,
                event_bus=self.event_bus,
                conversation_lock=self.conversation_lock,
            )
            logger.info("ChatService initialized")

            logger.info("Application initialization completed")

        except BaseException:
            logger.exception("Application initialization failed")
            await self.shutdown()
            raise

    async def _load_persisted_settings(self) -> None:
        """
        Layer database overrides on top of the environment defaults.

        Best effort: a bad or stale row must not prevent startup, because
        the environment defaults are always a working configuration.
        """
        try:
            stored = await self.settings_repository.get_all()

        except Exception:  # noqa: BLE001
            logger.exception("Failed to read persisted settings")
            return

        if not stored:
            return

        try:
            self.runtime_settings.apply(stored)

        except ValueError:
            logger.exception(
                "Persisted settings rejected, using environment defaults | "
                "keys=%s",
                sorted(stored),
            )
            return

        logger.info(
            "Persisted settings applied | keys=%s",
            sorted(stored),
        )

    async def apply_settings(
        self,
        changes: dict[str, object],
    ) -> RuntimeSettings:
        """
        Apply runtime settings and persist the ones that outlive a restart.

        Validation happens first, so an invalid batch changes nothing and
        writes nothing.
        """
        updated = self.runtime_settings.apply(changes)

        # log_level is applied but never stored: it belongs to this run.
        if "log_level" in changes:
            set_log_level(updated.log_level)

        persistable = {
            key: str(getattr(updated, key))
            for key in changes
            if key in PERSISTED_FIELDS
        }

        await self.settings_repository.upsert_many(persistable)

        return updated

    def spawn(self, coroutine: Coroutine[Any, Any, None]) -> asyncio.Task:
        """
        Run a coroutine detached from the request that started it.

        The reference is held here because asyncio keeps only a weak one, and
        an unreferenced task can be garbage collected mid-flight.
        """
        task = asyncio.create_task(coroutine)

        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        return task

    async def shutdown(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        """
        Shut down shared resources in reverse order of acquisition.
        """
        logger.info("Application shutdown started")
        # Before the pool closes. Detached work still needs a connection
        # to persist what it produced, and AsyncExitStack.__aexit__ below
        # is what closes it.
        await _drain_tasks(self._background_tasks, "generation")

        # Second, and after the first on purpose: draining a generation
        # is what *creates* its finalize task. See the note below.
        if self.chat_service is not None:
            await _drain_tasks(
                self.chat_service.pending_tasks(),
                "finalization",
            )

        resources = self._resources
        self._resources = None

        try:
            if resources is not None:
                logger.info("Closing application resources")
                await resources.__aexit__(
                    exc_type,
                    exc_value,
                    traceback,
                )
        finally:
            self.checkpointer = None
            self.agent_graph = None
            self.conversation_context_builder = None
            self.summary_context_builder = None
            self.history_context_builder = None
            self.summarization_service = None
            self.chat_service = None
            self.llm = None

        logger.info("Application shutdown completed")

    async def __aenter__(self) -> Self:
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.shutdown(
            exc_type,
            exc_value,
            traceback,
        )
