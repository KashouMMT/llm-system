import asyncio
import base64
import contextlib
import time
import uuid
from collections.abc import Callable, Coroutine, Sequence
from typing import Any
from uuid import UUID

from langchain_core.messages import HumanMessage

from app.agent.graph import AgentGraph
from app.authentication.authorization import is_admin
from app.authentication.models import User
from app.config.settings import (
    LLM_SUPPORTS_VISION,
    MAX_ATTACHMENT_BATCH_BYTES,
    MAX_USER_INPUT_CHARS,
)
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.file_repository import (
    FileRecord,
    FileRepository,
    serialize_attachment,
)
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
from app.services.conversation_title_service import ConversationTitleService
from app.services.summarization_service import SummarizationService
from app.storage.base import FileStorage
from app.utils import conversation_log
from app.utils.attachment_manifest import format_attachment_manifest_line
from app.utils.detect import IMAGE_JPEG, IMAGE_PNG
from app.utils.images import downscale_image
from app.utils.logger import logger

# Terminal status -> the event that announces it.
TERMINAL_EVENTS = {
    "complete": EVENT_MESSAGE_COMPLETED,
    "cancelled": EVENT_MESSAGE_CANCELLED,
    "failed": EVENT_MESSAGE_FAILED,
}

_IMAGE_CONTENT_TYPES = {IMAGE_PNG, IMAGE_JPEG}

# Long side, in pixels, an image is downscaled to before being sent to a
# vision model. 2048 is generous for anything a phone camera or a screen
# capture produces, while bounding the token cost a single image adds.
VISION_MAX_IMAGE_DIMENSION_PX = 2048


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
        file_repository: FileRepository,
        file_storage: FileStorage,
        summarization_service: SummarizationService,
        title_service: ConversationTitleService,
        event_bus: EventBus,
        conversation_lock: ConversationLock,
        spawn: Callable[[Coroutine[Any, Any, None]], asyncio.Task],
    ) -> None:
        self.agent_graph = agent_graph
        self.conversation_repository = conversation_repository
        self.message_repository = message_repository
        self.file_repository = file_repository
        self.file_storage = file_storage
        self.summarization_service = summarization_service
        self.title_service = title_service
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
    def validate_user_input(user_input: str, *, has_attachments: bool) -> str:
        user_input = user_input.strip()

        if not user_input and not has_attachments:
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
        attachment_ids: Sequence[UUID] = (),
    ) -> TurnIds:
        """
        Persist both sides of a turn and announce them.

        The caller must already hold the conversation lock.
        """
        user_input = self.validate_user_input(
            user_input,
            has_attachments=bool(attachment_ids),
        )

        # Re-read, not cached from the route, so a hold applied mid-session
        # takes effect on the very next send. Admins are never held.
        status = await self.conversation_repository.get_status(conversation_id)

        if status == "held" and not is_admin(user):
            raise ConversationHeldError(conversation_id)

        # Set before the generation task is spawned, so that task — and the
        # graph run and tool calls beneath it — inherit the actor when
        # asyncio copies this context.
        conversation_log.set_actor(user)

        turn = await self.message_repository.create_turn(
            conversation_id=conversation_id,
            user_content=user_input,
            client_message_id=client_message_id,
            user_id=user.id,
            max_attachment_batch_bytes=MAX_ATTACHMENT_BATCH_BYTES,
            attachment_ids=attachment_ids,
        )

        user_message_id = turn.user_message_id
        assistant_message_id = turn.assistant_message_id

        self.conversation_lock.attach_message_id(
            conversation_id,
            assistant_message_id,
        )

        # Only queried when there is something to attach — the common case
        # has none, and re-reading what create_turn just wrote would be
        # wasted work on every turn.
        attachments = (
            [
                serialize_attachment(file)
                for file in await self.file_repository.get_by_message_ids(
                    [user_message_id],
                )
            ]
            if attachment_ids
            else []
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
                    "attachments": attachments,
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

        if conversation_log.is_enabled():
            logger.debug(
                "Conversation | user | conversation=%s message=%s\n%s",
                conversation_id,
                user_message_id,
                user_input,
                extra=conversation_log.CONVERSATION_ONLY,
            )

        # Name the conversation from this message, in the background, so it
        # never adds latency to the turn. The service no-ops unless the
        # title is still the placeholder, so spawning it every turn is
        # cheap and the first turn is not a special case here.
        self._spawn(self._run_title_generation(conversation_id, user_input))

        return TurnIds(
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
        )

    async def _run_title_generation(
        self,
        conversation_id: UUID,
        first_user_message: str,
    ) -> None:
        try:
            await self.title_service.generate_and_store(
                conversation_id,
                first_user_message,
            )

        except Exception:  # noqa: BLE001
            logger.exception(
                "Background title generation failed | conversation=%s",
                conversation_id,
            )

    async def _build_human_message(
        self,
        conversation_id: UUID,
        user_message_id: int,
        user_input: str,
    ) -> HumanMessage:
        """
        The current turn's HumanMessage — plain text if nothing is
        attached, or content blocks (text + a manifest line per
        attachment + image blocks) if there is.

        This is the only turn that ever carries image bytes.
        HistoryContextBuilder re-describes the same attachments as
        text-only manifest lines on every later turn, via the same
        format_attachment_manifest_line this uses, so the model is never
        told two different things about one file.
        """
        files = await self.file_repository.get_by_message_ids([user_message_id])

        if not files:
            return HumanMessage(content=user_input)

        vision_enabled = LLM_SUPPORTS_VISION
        manifest_lines: list[str] = []
        image_blocks: list[dict[str, Any]] = []

        for file in files:
            image_prepared = False

            if file.content_type in _IMAGE_CONTENT_TYPES and vision_enabled:
                block = await self._build_image_block(conversation_id, file)

                if block is not None:
                    image_blocks.append(block)
                    image_prepared = True

            manifest_lines.append(
                format_attachment_manifest_line(
                    file,
                    is_current_turn=True,
                    vision_enabled=vision_enabled,
                    image_prepared=image_prepared,
                )
            )

        text_lines = ([user_input] if user_input else []) + manifest_lines

        content: list[dict[str, Any]] = [
            {"type": "text", "text": "\n".join(text_lines)},
            *image_blocks,
        ]

        return HumanMessage(content=content)

    async def _build_image_block(
        self,
        conversation_id: UUID,
        file: FileRecord,
    ) -> dict[str, Any] | None:
        """
        Read, downscale, and base64-encode one image for a vision content
        block. Returns None on any failure — reading a stray-corrupt image
        or a decompression edge case must not fail the whole turn, only
        that one image, and the caller reflects the failure in that
        image's own manifest line rather than dropping it silently.
        """
        try:
            raw = await self.file_storage.read(file.storage_key)

            downscaled = await asyncio.to_thread(
                downscale_image,
                raw,
                file.content_type,
                max_dimension=VISION_MAX_IMAGE_DIMENSION_PX,
            )

        except Exception:  # noqa: BLE001
            logger.exception(
                "Could not prepare image for the model | conversation=%s file=%s",
                conversation_id,
                file.id,
            )
            return None

        encoded = base64.b64encode(downscaled).decode("ascii")

        return {
            "type": "image_url",
            "image_url": {"url": f"data:{file.content_type};base64,{encoded}"},
        }

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
            human_message = await self._build_human_message(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                user_input=user_input,
            )

            async for message_chunk, metadata in self.agent_graph.stream(
                input_messages=[human_message],
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
        if conversation_log.is_enabled():
            logger.debug(
                "Conversation | assistant | conversation=%s message=%s status=%s\n%s",
                conversation_id,
                assistant_message_id,
                status,
                content,
                extra=conversation_log.CONVERSATION_ONLY,
            )
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
