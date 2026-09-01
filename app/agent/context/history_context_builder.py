from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.config.runtime_settings import RuntimeSettingsHolder
from app.repositories.message_repository import MessageRepository
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
        settings: RuntimeSettingsHolder,
    ) -> None:
        self.message_repository = message_repository
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

        history_messages: list[BaseMessage] = []

        for message in rows:
            if message.role == "user":
                history_messages.append(HumanMessage(content=message.content))

            elif message.role == "assistant":
                history_messages.append(AIMessage(content=message.content))

        logger.debug(
            "History context loaded | conversation=%s messages=%s",
            conversation_id,
            len(history_messages),
        )

        return history_messages
