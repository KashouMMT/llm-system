import asyncio
import base64
import contextlib
import re
import time
import uuid
from collections.abc import Callable, Coroutine, Mapping, Sequence
from typing import Any
from uuid import UUID

from langchain_core.messages import HumanMessage

from app.agent.graph import AgentGraph
from app.authentication.authorization import is_admin
from app.authentication.models import User
from app.config.settings import (
    LLM_SUPPORTS_VISION,
    MAX_USER_INPUT_CHARS,
)
from app.plugins.contracts import CommandContext, PluginCommand
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
from app.utils.detect import IMAGE_CONTENT_TYPES, VIDEO_CONTENT_TYPES
from app.utils.images import downscale_image
from app.utils.logger import logger
from app.utils.video_frames import FrameExtractionError, extract_frames

# A command is deterministic and never reaches the LLM: the first
# whitespace-separated token of the (already-stripped) user input must
# match this exactly, or the message is an ordinary turn. Deliberately
# narrow — a message that merely contains a slash elsewhere must never be
# hijacked.
_COMMAND_TOKEN_PATTERN = re.compile(r"^/[a-z][a-z0-9-]*$")

# Terminal status -> the event that announces it.
TERMINAL_EVENTS = {
    "complete": EVENT_MESSAGE_COMPLETED,
    "cancelled": EVENT_MESSAGE_CANCELLED,
    "failed": EVENT_MESSAGE_FAILED,
}

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
    __slots__ = ("user_message_id", "assistant_message_id", "is_command")  # noqa: RUF023

    def __init__(
        self,
        user_message_id: int,
        assistant_message_id: int,
        is_command: bool = False,
    ) -> None:
        self.user_message_id = user_message_id
        self.assistant_message_id = assistant_message_id
        # True when begin_turn already routed this turn to a slash-command
        # handler and finalized it itself. The caller (server.py, cli.py)
        # must not also spawn ChatService.generate for it — a command
        # never reaches the LLM.
        self.is_command = is_command


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
        commands: Mapping[str, PluginCommand] | None = None,
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
        # Namespace -> PluginCommand, collected at startup by
        # app.plugins.load_commands. Empty is a legitimate deployment
        # (no plugin registers a command), not a misconfiguration.
        self.commands = commands or {}

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

        first_token = user_input.split(maxsplit=1)[0] if user_input else ""

        if _COMMAND_TOKEN_PATTERN.match(first_token):
            namespace = first_token[1:]
            rest = user_input[len(first_token) :].strip()
            rest_parts = rest.split(maxsplit=1) if rest else []
            subcommand = rest_parts[0] if rest_parts else ""
            argument = rest_parts[1] if len(rest_parts) > 1 else ""

            # A command never reaches the LLM: begin_turn runs and
            # finalizes it itself, in the background so this call still
            # returns immediately like a normal turn. The caller must not
            # also call generate() for it — see TurnIds.is_command.
            self._spawn(
                self._run_command(
                    conversation_id=conversation_id,
                    user=user,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    namespace=namespace,
                    subcommand=subcommand,
                    argument=argument,
                )
            )

            return TurnIds(
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                is_command=True,
            )

        return TurnIds(
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
        )

    async def _run_command(
        self,
        conversation_id: UUID,
        user: User,
        user_message_id: int,
        assistant_message_id: int,
        namespace: str,
        subcommand: str,
        argument: str,
    ) -> None:
        """
        Run one slash command and finalize the turn through the same path
        an LLM generation uses — _finalize owns the lock release, the
        terminal event, conversation-log writing and summarization
        scheduling either way, so a command turn and an LLM turn look
        identical from every consumer downstream of this call.
        """
        command = self.commands.get(namespace)

        if command is None:
            content = self._unknown_command_message(namespace)
            status = "complete"
        else:
            context = CommandContext(
                conversation_id=conversation_id,
                user=user,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                subcommand=subcommand,
                argument=argument,
            )

            try:
                content = await command.handler(context)
                status = "complete"

            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Command failed | namespace=%s conversation=%s",
                    namespace,
                    conversation_id,
                )
                content = f"The `/{namespace}` command failed: {exc}"
                status = "failed"

        await self._finalize(
            conversation_id=conversation_id,
            assistant_message_id=assistant_message_id,
            content=content,
            status=status,
        )

    def _unknown_command_message(self, namespace: str) -> str:
        known = ", ".join(f"`/{name}`" for name in sorted(self.commands))

        return (
            f"Unknown command: `/{namespace}`.\n\n"
            + (f"Available commands: {known}" if known else "No commands are registered.")
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

    async def _build_turn_input(
        self,
        conversation_id: UUID,
        user_message_id: int,
        user_input: str,
    ) -> tuple[HumanMessage, list[dict[str, Any]]]:
        """
        The current turn's HumanMessage, and the image blocks that go with
        it — returned separately, never combined here.

        The HumanMessage is always plain text: the user's input plus one
        manifest line per attachment. It becomes LangGraph state, and state
        is written to the Postgres checkpointer on every graph step and
        never deleted — a base64 image inside it was stored once per step,
        for as many turns as compaction kept the message, forever. The
        image blocks instead travel in the run config, which the
        checkpointer does not persist (it copies only scalar config values
        into checkpoint metadata, never a list), and the agent node joins
        them to the message only when it builds the model's input.

        This is the only turn that ever carries image bytes.
        HistoryContextBuilder re-describes the same attachments as
        text-only manifest lines on every later turn, via the same
        format_attachment_manifest_line this uses, so the model is never
        told two different things about one file.
        """
        files = await self.file_repository.get_by_message_ids([user_message_id])

        if not files:
            return HumanMessage(content=user_input), []

        vision_enabled = LLM_SUPPORTS_VISION
        manifest_lines: list[str] = []
        image_blocks: list[dict[str, Any]] = []

        for file in files:
            image_prepared = False
            video_frames_shown = 0
            video_note: str | None = None

            if file.content_type in IMAGE_CONTENT_TYPES and vision_enabled:
                block = await self._build_image_block(conversation_id, file)

                if block is not None:
                    image_blocks.append(block)
                    image_prepared = True

            if file.content_type in VIDEO_CONTENT_TYPES and vision_enabled:
                blocks, video_note = await self._build_video_blocks(
                    conversation_id, file
                )
                image_blocks.extend(blocks)
                video_frames_shown = len(blocks)

            manifest_lines.append(
                format_attachment_manifest_line(
                    file,
                    is_current_turn=True,
                    vision_enabled=vision_enabled,
                    image_prepared=image_prepared,
                    video_frames_shown=video_frames_shown,
                    video_note=video_note,
                )
            )

        text_lines = ([user_input] if user_input else []) + manifest_lines

        return HumanMessage(content="\n".join(text_lines)), image_blocks

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

    async def _build_video_blocks(
        self,
        conversation_id: UUID,
        file: FileRecord,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """
        Sample stills from one video as vision content blocks, in time order,
        plus a note for the manifest line: what was skipped and any capture
        warnings, or why the video could not be used at all.

        Returns ([], reason) on failure, for the same reason _build_image_block
        returns None: one unusable video must not fail the turn. The reason is
        passed on rather than logged away, so the model can tell the user to
        turn the lights on instead of only saying it could not see the video.
        """
        try:
            async with self.file_storage.temporary_path(file.storage_key) as path:
                sample = await extract_frames(path)
        except FrameExtractionError as error:
            logger.warning(
                "Could not extract video frames | conversation=%s file=%s error=%s",
                conversation_id,
                file.id,
                error,
            )
            return [], str(error)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Could not prepare video for the model | conversation=%s file=%s",
                conversation_id,
                file.id,
            )
            return [], None

        blocks = [
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/jpeg;base64,"
                    + base64.b64encode(frame.jpeg).decode("ascii")
                },
            }
            for frame in sample.frames
        ]

        return blocks, " ".join([sample.summary() + ".", *sample.warnings])

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
            human_message, image_blocks = await self._build_turn_input(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                user_input=user_input,
            )

            async for message_chunk, metadata in self.agent_graph.stream(
                input_messages=[human_message],
                thread_id=str(conversation_id),
                current_user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                current_turn_image_blocks=image_blocks,
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
