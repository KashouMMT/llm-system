import time
from collections.abc import Callable
from uuid import UUID

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agent.context.conversation_context_builder import (
    ConversationContextBuilder,
)
from app.agent.state import AgentState, get_current_turn_messages
from app.utils.logger import logger

PrepareContextNode = Callable[[AgentState, RunnableConfig], dict]


def create_prepare_context_node(
    conversation_context_builder: ConversationContextBuilder,
) -> PrepareContextNode:
    """
    Create the node that prepares background context once per user request.
    """

    def prepare_context_node(
        state: AgentState,
        config: RunnableConfig,
    ) -> dict:
        start = time.perf_counter()

        thread_id = config["configurable"]["thread_id"]
        conversation_id = UUID(thread_id)

        current_turn_messages = get_current_turn_messages(
            state["messages"],
        )

        current_user_message = current_turn_messages[0]

        if not isinstance(current_user_message, HumanMessage):
            raise RuntimeError(  # noqa: TRY004
                "The current turn must begin with a HumanMessage."
            )

        if not isinstance(current_user_message.content, str):
            raise TypeError(
                "Only text user messages are currently supported."
            )

        prepared_context = conversation_context_builder.build(
            conversation_id=conversation_id,
            user_query=current_user_message.content,
        )

        elapsed = time.perf_counter() - start

        logger.debug(
            "Prepare-context node completed | conversation=%s "
            "context_messages=%s elapsed=%.3fs",
            conversation_id,
            len(prepared_context),
            elapsed,
        )

        return {
            "prepared_context": prepared_context,
        }

    return prepare_context_node