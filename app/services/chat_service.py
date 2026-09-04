import asyncio
import contextlib
import time
import uuid
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from langchain_core.messages import HumanMessage

from app.agent.graph import AgentGraph
from app.authentication.authorization import is_admin
from app.authentication.models import User
from app.config.settings import MAX_USER_INPUT_CHARS
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.runtime.conversation_lock import ConversationLock
from app.runtime.event_bus import (
    EVENT_CONVERSATION_UPDATED,
    EVENT_MESSAGE_CANCELLED,
    EVENT_MESSAGE_COMPLETED,
    EVENT_MESSAGE_CREATED,
    EVENT_MESSAGE_DELTA,
    EVENT_MESSAGE_FAILED,
    Event,
    EventBus,
)
from app.services.summarization_service import SummarizationService
from app.utils.logger import logger

# Terminal status -> the event that announces it.
TERMINAL_EVENTS = {
    "complete": EVENT_MESSAGE_COMPLETED,
    "cancelled": EVENT_MESSAGE_CANCELLED,
    "failed": EVENT_MESSAGE_FAILED,
}


class ConversationHeldError(Exception):
    """
    A non-admin tried to send into a conversation an admin has put on hold.

    Inert until something sets conversations.status = 'held'. The check lives
    here so the future admin-override feature is a small addition rather than
    a change to the send path.
    """

    def __init__(self, conversation_id: UUID) -> None:
        super().__init__(f"Conversation is on hold: {conversation_id}")
        self.conversation_id = conversation_id


class TurnIds:
    __slots__ = ("user_message_id", "assistant_message_id")  # noqa: RUF023

    def __init__(
        self,
        user_message_id: int,
        assistant_message_id: int,
    ) -> None:
        self.user_message_id = user_message_id
        self.assistant_message_id = assistant_message_id


class ChatService:
    """
    Application-level chat service.

    A turn is opened and persisted before generation starts, then generated
    by a background task that publishes tokens to the event bus. Nothing about
    the turn depends on an HTTP connection staying open, so a client that
    disconnects loses nothing.

    Summarization runs afterward, out of band, so it never delays a response.
    """

    def __init__(
        self,
        agent_graph: AgentGraph,
        conversation_repository: ConversationRepository,
        message_repository: MessageRepository,
        summarization_service: SummarizationService,
        event_bus: EventBus,
        conversation_lock: ConversationLock,
        spawn: Callable[[Coroutine[Any, Any, None]], asyncio.Task],
    ) -> None:
        self.agent_graph = agent_graph
        self.conversation_repository = conversation_repository
        self.message_repository = message_repository
        self.summarization_service = summarization_service
        self.event_bus = event_bus
        self.conversation_lock = conversation_lock

        # Detached work (finalization, summarization) is registered with the
        # application-wide spawner, so shutdown has a single registry to drain.
        self._spawn = spawn

        # Dedup guard, not a task registry: skip a second summarization run
        # for a conversation already being summarized.
        self._summarizing: set[UUID] = set()

        logger.info("ChatService initialized")

    @staticmethod
    def validate_user_input(user_input: str) -> str:
        user_input = user_input.strip()

        if not user_input:
            raise ValueError("Message must not be empty.")

        if len(user_input) > MAX_USER_INPUT_CHARS:
            raise ValueError(
                f"Message exceeds {MAX_USER_INPUT_CHARS} characters "
                f"(got {len(user_input)})."
            )

        return user_input

    async def begin_turn(
        self,
        conversation_id: UUID,
        user: User,
        user_input: str,
        client_message_id: UUID,
    ) -> TurnIds:
        """
        Persist both sides of a turn and announce them.

        The caller must already hold the conversation lock.
        """
        user_input = self.validate_user_input(user_input)

        # Re-read, not cached from the route, so a hold applied mid-session
        # takes effect on the very next send. Admins are never held.
        status = await self.conversation_repository.get_status(conversation_id)

        if status == "held" and not is_admin(user):
            raise ConversationHeldError(conversation_id)

        turn = await self.message_repository.create_turn(
            conversation_id=conversation_id,
            user_content=user_input,
            client_message_id=client_message_id,
        )

        user_message_id = turn.user_message_id
        assistant_message_id = turn.assistant_message_id

        self.conversation_lock.attach_message_id(
            conversation_id,
            assistant_message_id,
        )

        self.event_bus.publish(
            Event(
                type=EVENT_MESSAGE_CREATED,
                conversation_id=conversation_id,
                id=user_message_id,
                payload={
                    "message_id": user_message_id,
                    "role": "user",
                    "content": user_input,
                    "status": "complete",
                    "created_at": turn.user_created_at.isoformat(),
                    "client_message_id": str(client_message_id),
                },
            )
        )

        self.event_bus.publish(
            Event(
                type=EVENT_MESSAGE_CREATED,
                conversation_id=conversation_id,
                id=assistant_message_id,
                payload={
                    "message_id": assistant_message_id,
                    "role": "assistant",
                    "content": "",
                    "status": "streaming",
                    "created_at": turn.assistant_created_at.isoformat(),
                    "reply_to_message_id": user_message_id,
                },
            )
        )

        self.event_bus.publish(
            Event(
                type=EVENT_CONVERSATION_UPDATED,
                conversation_id=conversation_id,
                payload={"conversation_id": str(conversation_id)},
            )
        )

        logger.info(
            "Turn opened | conversation=%s user_message=%s assistant_message=%s",
            conversation_id,
            user_message_id,
            assistant_message_id,
        )

        return TurnIds(
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
        )

    async def generate(
        self,
        conversation_id: UUID,
        user_message_id: int,
        assistant_message_id: int,
        user_input: str,
    ) -> None:
        """
        Produce the assistant response for an already-opened turn.

        Runs as a background task, not inside a request. Tokens are buffered
        in memory and published as they arrive; the buffer is written once,
        on whichever terminal state is reached.
        """
        request_id = uuid.uuid4().hex[:8]

        logger.info(
            "Generation started | request=%s conversation=%s message=%s",
            request_id,
            conversation_id,
            assistant_message_id,
        )

        start = time.perf_counter()

        buffer: list[str] = []
        seq = 0
        status = "failed"

        try:
            async for message_chunk, metadata in self.agent_graph.stream(
                input_messages=[HumanMessage(content=user_input)],
                thread_id=str(conversation_id),
                current_user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
            ):
                if metadata.get("langgraph_node") != "agent":
                    continue

                content = message_chunk.content

                if not content or not isinstance(content, str):
                    continue

                buffer.append(content)
                seq += 1

                self.event_bus.publish(
                    Event(
                        type=EVENT_MESSAGE_DELTA,
                        conversation_id=conversation_id,
                        payload={
                            "message_id": assistant_message_id,
                            "seq": seq,
                            "text": content,
                        },
                    )
                )

            if buffer:
                status = "complete"

            else:
                # A successful graph run that produced no text is not a
                # usable answer, and must not be shown as one.
                logger.warning(
                    "Graph produced no final text | request=%s conversation=%s",
                    request_id,
                    conversation_id,
                )

        except asyncio.CancelledError:
            status = "cancelled"

            logger.info(
                "Generation cancelled | request=%s conversation=%s",
                request_id,
                conversation_id,
            )

            raise

        except Exception:  # noqa: BLE001
            status = "failed"

            logger.exception(
                "Generation failed | request=%s conversation=%s elapsed=%.2fs",
                request_id,
                conversation_id,
                time.perf_counter() - start,
            )

        finally:
            content = "".join(buffer)

            # Shielded, and awaited only if we are not already being
            # cancelled: inside a finally during cancellation a bare await is
            # cancelled immediately, and the flush would silently never run.
            finalize = self._spawn(
                self._finalize(
                    conversation_id=conversation_id,
                    assistant_message_id=assistant_message_id,
                    content=content,
                    status=status,
                )
            )

            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(finalize)

            logger.info(
                "Generation finished | request=%s conversation=%s status=%s "
                "latency=%.2fs response_chars=%s",
                request_id,
                conversation_id,
                status,
                time.perf_counter() - start,
                len(content),
            )

    async def _finalize(
        self,
        conversation_id: UUID,
        assistant_message_id: int,
        content: str,
        status: str,
    ) -> None:
        """
        Write the buffer, release the lock, announce the outcome.

        Runs even when generation was cancelled, which is the whole point:
        a partial answer is kept and labelled rather than discarded.
        """
        try:
            await self.message_repository.complete_message(
                message_id=assistant_message_id,
                content=content,
                status=status,
            )

            await self.conversation_repository.touch(conversation_id)

        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to persist generation outcome | conversation=%s "
                "message=%s status=%s",
                conversation_id,
                assistant_message_id,
                status,
            )

        finally:
            self.conversation_lock.release(conversation_id)

        self.event_bus.publish(
            Event(
                type=TERMINAL_EVENTS[status],
                conversation_id=conversation_id,
                id=assistant_message_id,
                payload={
                    "message_id": assistant_message_id,
                    "content": content,
                    "status": status,
                },
            )
        )

        self.event_bus.publish(
            Event(
                type=EVENT_CONVERSATION_UPDATED,
                conversation_id=conversation_id,
                payload={"conversation_id": str(conversation_id)},
            )
        )

        if status == "complete":
            self._schedule_summarization(conversation_id)

    def _schedule_summarization(self, conversation_id: UUID) -> None:
        """
        Kick off summarization in the background, if not already running
        for this conversation.

        Never awaited by the caller — it must not add latency to the
        response the user just received.
        """
        if conversation_id in self._summarizing:
            return

        self._summarizing.add(conversation_id)

        self._spawn(self._run_summarization(conversation_id))

    async def _run_summarization(self, conversation_id: UUID) -> None:
        try:
            await self.summarization_service.trigger_if_needed(
                conversation_id,
            )

        except Exception:  # noqa: BLE001
            logger.exception(
                "Background summarization failed | conversation=%s",
                conversation_id,
            )

        finally:
            self._summarizing.discard(conversation_id)
