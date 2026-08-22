import time
from uuid import UUID

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
)

from app.repositories.message_repository import MessageRepository
from app.utils.logger import logger


class ContextBuilder:
    """
    Loads completed conversation history from the application database.

    It does not add the current graph message. The agent node is responsible
    for combining this historical context with the current LangGraph turn.

    Future strategy:
        build_history()
        build_summary_memory()
        retrieve_rag_context()
    """

    def __init__(
        self,
        message_repository: MessageRepository,
        recent_message_limit: int = 20,
    ) -> None:
        self.message_repository = message_repository
        self.recent_message_limit = recent_message_limit

    def build_history(
        self,
        conversation_id: UUID,
    ) -> list[BaseMessage]:
        """
        Load completed transcript messages for a conversation.

        The current user message is not yet stored by ChatService, so it is
        intentionally not included here. It comes from LangGraph state.
        """
        start = time.perf_counter()

        logger.debug(
            "History context build started | conversation=%s limit=%s",
            conversation_id,
            self.recent_message_limit,
        )

        recent_rows = self.message_repository.get_recent_messages(
            conversation_id=conversation_id,
            limit=self.recent_message_limit,
        )

        history: list[BaseMessage] = []

        for _, role, content, _ in recent_rows:
            if role == "user":
                history.append(HumanMessage(content=content))

            elif role == "assistant":
                history.append(AIMessage(content=content))

        elapsed = time.perf_counter() - start

        logger.debug(
            "History context build completed | conversation=%s "
            "messages=%s elapsed=%.3fs",
            conversation_id,
            len(history),
            elapsed,
        )

        return history
