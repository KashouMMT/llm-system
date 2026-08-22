import time
from uuid import UUID

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
)

from app.repositories.message_repository import MessageRepository
from app.utils.logger import logger


class ConversationContextBuilder:
    """
    Builds stable background context for one user request.

    Current sources:
        - Recent completed conversation history.

    Future sources:
        - Conversation summary for older completed messages.
        - RAG documents relevant to the current user query.
        - Durable user-memory facts.
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
        user_query: str,
    ) -> list[BaseMessage]:
        """
        Assemble context that remains stable during one agent/tool loop.

        The current user message is not included here because it belongs to
        LangGraph's active turn state.
        """
        start = time.perf_counter()

        logger.debug(
            "Prepared context build started | conversation=%s query_chars=%s",
            conversation_id,
            len(user_query),
        )

        recent_history = self.build_recent_history(
            conversation_id=conversation_id,
        )

        prepared_context: list[BaseMessage] = [
            *recent_history,
        ]

        # Future order:
        #
        # prepared_context = [
        #     *self.build_summary_memory(conversation_id),
        #     *recent_history,
        #     *self.retrieve_rag_context(
        #         conversation_id=conversation_id,
        #         user_query=user_query,
        #     ),
        #     *self.build_user_memory(conversation_id),
        # ]

        elapsed = time.perf_counter() - start

        logger.debug(
            "Prepared context build completed | conversation=%s "
            "messages=%s elapsed=%.3fs",
            conversation_id,
            len(prepared_context),
            elapsed,
        )

        return prepared_context

    def build_recent_history(
        self,
        conversation_id: UUID,
    ) -> list[BaseMessage]:
        """
        Load completed transcript messages from the application database.
        """
        rows = self.message_repository.get_recent_messages(
            conversation_id=conversation_id,
            limit=self.max_history_messages,
        )

        history_messages: list[BaseMessage] = []

        for _, role, content, _ in rows:
            if role == "user":
                history_messages.append(HumanMessage(content=content))

            elif role == "assistant":
                history_messages.append(AIMessage(content=content))

        logger.debug(
            "Recent transcript context loaded | conversation=%s messages=%s",
            conversation_id,
            len(history_messages),
        )

        return history_messages