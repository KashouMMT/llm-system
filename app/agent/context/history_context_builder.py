from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

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
        max_history_messages: int,
    ) -> None:
        self.message_repository = message_repository
        self.max_history_messages = max_history_messages

    def build(
        self,
        conversation_id: UUID,
        after_message_id: int,
    ) -> list[BaseMessage]:
        """
        Load transcript messages newer than after_message_id.

        after_message_id is the summary watermark: everything at or before
        it is already represented by the durable summary, so including it
        here would feed the model the same content twice.
        """
        rows = self.message_repository.get_messages_after_id(
            conversation_id=conversation_id,
            message_id=after_message_id,
        )

        if len(rows) > self.max_history_messages:
            logger.warning(
                "Unsummarized backlog exceeds history window | "
                "conversation=%s backlog=%s window=%s",
                conversation_id,
                len(rows),
                self.max_history_messages,
            )

            rows = rows[-self.max_history_messages :]

        history_messages: list[BaseMessage] = []

        for _, role, content, _ in rows:
            if role == "user":
                history_messages.append(HumanMessage(content=content))

            elif role == "assistant":
                history_messages.append(AIMessage(content=content))

        logger.debug(
            "History context loaded | conversation=%s messages=%s",
            conversation_id,
            len(history_messages),
        )

        return history_messages
