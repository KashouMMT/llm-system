from collections.abc import Sequence
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.config.runtime_settings import RuntimeSettingsHolder
from app.repositories.file_repository import FileRecord, FileRepository
from app.repositories.message_repository import MessageRepository
from app.utils.attachment_manifest import format_attachment_manifest_line
from app.utils.logger import logger


class HistoryContextBuilder:
    """
    Loads transcript messages not yet folded into the durable summary.

    SummarizationService is responsible for keeping this backlog small.
    If it has fallen behind, only the most recent max_history_messages are
    kept — anything older than that, and not yet summarized, is not visible
    to the model until summarization catches up.
    """

    def __init__(
        self,
        message_repository: MessageRepository,
        file_repository: FileRepository,
        settings: RuntimeSettingsHolder,
    ) -> None:
        self.message_repository = message_repository
        self.file_repository = file_repository
        self.settings = settings

    async def build(
        self,
        conversation_id: UUID,
        after_message_id: int,
        before_message_id: int | None = None,
    ) -> list[BaseMessage]:
        """
        Load transcript messages newer than after_message_id.

        after_message_id is the summary watermark: everything at or before
        it is already represented by the durable summary, so including it
        here would feed the model the same content twice.
        """
        rows = await self.message_repository.get_messages_after_id(
            conversation_id=conversation_id,
            message_id=after_message_id,
            before_message_id=before_message_id,
        )
        
        max_history_messages = self.settings.current.max_context_history_messages

        if len(rows) > max_history_messages:
            logger.warning(
                "Unsummarized backlog exceeds history window | "
                "conversation=%s backlog=%s window=%s",
                conversation_id,
                len(rows),
                max_history_messages,
            )

            rows = list(rows)[-max_history_messages:]

        # One query for every user message in this window, rather than one
        # per message — the same reasoning as
        # FileRepository.get_by_message_ids' other callers.
        user_message_ids = [message.id for message in rows if message.role == "user"]
        files_by_message = await self._files_by_message_id(user_message_ids)

        history_messages: list[BaseMessage] = []

        for message in rows:
            if message.role == "user":
                history_messages.append(
                    HumanMessage(
                        content=self._with_attachment_manifest(
                            message.content,
                            files_by_message.get(message.id, []),
                        )
                    )
                )

            elif message.role == "assistant":
                history_messages.append(AIMessage(content=message.content))

        logger.debug(
            "History context loaded | conversation=%s messages=%s",
            conversation_id,
            len(history_messages),
        )

        return history_messages

    async def _files_by_message_id(
        self,
        message_ids: Sequence[int],
    ) -> dict[int, list[FileRecord]]:
        if not message_ids:
            return {}

        files = await self.file_repository.get_by_message_ids(message_ids)

        grouped: dict[int, list[FileRecord]] = {}

        for file in files:
            if file.message_id is not None:
                grouped.setdefault(file.message_id, []).append(file)

        return grouped

    @staticmethod
    def _with_attachment_manifest(content: str, files: list[FileRecord]) -> str:
        """
        Append a manifest line per attachment as plain text.

        Only ever text here — an image's bytes were sent once, on the turn
        it arrived (ChatService._build_human_message); every later replay
        of this message says so instead of re-sending them.
        """
        if not files:
            return content

        lines = [content] if content else []

        lines.extend(
            format_attachment_manifest_line(file, is_current_turn=False)
            for file in files
        )

        return "\n".join(lines)
