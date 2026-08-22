import time
from uuid import UUID

from langchain_core.messages import BaseMessage

from app.agent.context.history_context_builder import HistoryContextBuilder
from app.agent.context.summary_context_builder import SummaryContextBuilder
from app.utils.logger import logger


class ConversationContextBuilder:
    """
    Builds stable background context for one user request.

    Current sources:
        - Durable conversation summary (messages already summarized away).
        - Recent history: messages not yet folded into that summary.

    Future sources:
        - RAG documents relevant to the current user query.
        - Durable user-memory facts.
    """

    def __init__(
        self,
        summary_context_builder: SummaryContextBuilder,
        history_context_builder: HistoryContextBuilder,
    ) -> None:
        self.summary_context_builder = summary_context_builder
        self.history_context_builder = history_context_builder

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

        summary_context = self.summary_context_builder.build(conversation_id)

        recent_history = self.history_context_builder.build(
            conversation_id=conversation_id,
            after_message_id=summary_context.last_summarized_message_id,
        )

        prepared_context: list[BaseMessage] = [
            *summary_context.messages,
            *recent_history,
        ]

        # Future order:
        #
        # prepared_context = [
        #     *summary_context.messages,
        #     *recent_history,
        #     *self.rag_context_builder.build(
        #         conversation_id=conversation_id,
        #         user_query=user_query,
        #     ),
        #     *self.user_memory_context_builder.build(conversation_id),
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
