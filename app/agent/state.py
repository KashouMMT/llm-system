from collections.abc import Sequence

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """
    State carried through one LangGraph thread.

    messages:
        LangGraph workflow messages, including user messages, AI tool calls,
        tool results, and final AI responses.

    prepared_context:
        Stable background context prepared once per user request. It contains
        completed transcript history now and will later contain summaries,
        RAG results, and durable user-memory facts.
    """
    prepared_context: list[BaseMessage]
    
def get_current_turn_messages(
    messages: Sequence[BaseMessage]
) -> list[BaseMessage]:
    """
    Return the active turn, beginning at the most recent user message.

    Checkpoint state may contain earlier turns. The active turn must preserve
    all messages after its user message, especially AI tool-call and tool-result
    messages.
    """
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return list(messages[index:])

    raise ValueError(
        "Agent state does not contain a user message for the current turn."
    )