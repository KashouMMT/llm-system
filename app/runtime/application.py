from contextlib import AsyncExitStack
from types import TracebackType

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
from app.config.settings import (
    MAX_CHECKPOINT_MESSAGES,
    MAX_CONTEXT_HISTORY_MESSAGES,
)
from app.database.init_db import initialize_database
from app.llm.llm_factory import LLMFactory
from app.llm.prompt_factory import PromptFactory
from app.persona.load_prompt import load_prompt
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.summary_repository import SummaryRepository
from app.services.chat_service import ChatService
from app.services.summarization_service import SummarizationService
from app.utils.logger import logger


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

        self.conversation_repository = ConversationRepository()
        self.message_repository = MessageRepository()
        self.summary_repository = SummaryRepository()

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

            logger.info("Loading system prompt")
            loaded_system_prompt = load_prompt()
            self.system_prompt = PromptFactory.create(
                loaded_system_prompt,
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
                max_history_messages=MAX_CONTEXT_HISTORY_MESSAGES,
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
                system_prompt=self.system_prompt,
                tools=TOOLS,
                checkpointer=self.checkpointer,
                conversation_context_builder=(self.conversation_context_builder),
                max_checkpoint_messages=MAX_CHECKPOINT_MESSAGES,
            )
            logger.info("AgentGraph initialized")

            logger.info("Creating summarization service")
            self.summarization_service = SummarizationService(
                llm=self.llm,
                message_repository=self.message_repository,
                summary_repository=self.summary_repository,
            )
            logger.info("Summarization service initialized")

            logger.info("Creating ChatService")
            self.chat_service = ChatService(
                agent_graph=self.agent_graph,
                conversation_repository=self.conversation_repository,
                summarization_service=self.summarization_service,
            )
            logger.info("ChatService initialized")

            logger.info("Application initialization completed")

        except BaseException:
            logger.exception("Application initialization failed")
            await self.shutdown()
            raise

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
