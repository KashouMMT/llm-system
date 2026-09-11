import time
from collections.abc import Awaitable, Callable
from uuid import UUID

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agent.context.conversation_context_builder import (
    ConversationContextBuilder,
)
from app.agent.state import AgentState, get_current_turn_messages
from app.utils.logger import logger

PrepareContextNode = Callable[[AgentState, RunnableConfig], Awaitable[dict]]


def _extract_text(content: str | list) -> str:
    """
    The plain-text portion of a HumanMessage's content.

    Plain text when there are no attachments; content blocks — a list with
    one text block plus a manifest line per attachment, and image blocks
    when vision is on — when there are (see
    ChatService._build_human_message). Only the text matters here: this
    feeds a debug log and ConversationContextBuilder's not-yet-built RAG
    extension point, neither of which needs the image blocks.
    """
    if isinstance(content, str):
        return content

    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "")

    return ""


def create_prepare_context_node(
    conversation_context_builder: ConversationContextBuilder,
) -> PrepareContextNode:
    """
    Create the node that prepares background context once per user request.
    """

    async def prepare_context_node(
        state: AgentState,
        config: RunnableConfig,
    ) -> dict:
        start = time.perf_counter()

        thread_id = config["configurable"]["thread_id"]
        conversation_id = UUID(thread_id)
        
        current_user_message_id = config["configurable"].get(
            "current_user_message_id",
        )

        current_turn_messages = get_current_turn_messages(
            state["messages"],
        )

        current_user_message = current_turn_messages[0]

        if not isinstance(current_user_message, HumanMessage):
            raise RuntimeError(  # noqa: TRY004
                "The current turn must begin with a HumanMessage."
            )

        prepared_context = await conversation_context_builder.build(
            conversation_id=conversation_id,
            user_query=_extract_text(current_user_message.content),
            before_message_id=current_user_message_id,
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