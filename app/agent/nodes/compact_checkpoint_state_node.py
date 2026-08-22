from collections.abc import Callable, Sequence

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    RemoveMessage,
)
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from app.agent.state import AgentState
from app.utils.logger import logger

CompactCheckpointStateNode = Callable[[AgentState], dict]


def select_recent_complete_turns(
    messages: Sequence[BaseMessage],
    max_checkpoint_messages: int,
) -> list[BaseMessage]:
    """
    Keep recent complete turns while respecting the configured limit where
    possible.

    A retained history must begin with a HumanMessage. If the configured limit
    would cut through an active tool sequence, this keeps the entire most recent
    turn instead of creating an invalid AI/tool message sequence.
    """
    if len(messages) <= max_checkpoint_messages:
        return list(messages)

    candidate_start = len(messages) - max_checkpoint_messages

    for index in range(candidate_start, len(messages)):
        if isinstance(messages[index], HumanMessage):
            return list(messages[index:])

    for index in range(candidate_start - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return list(messages[index:])

    logger.warning(
        "Checkpoint message compaction skipped because no HumanMessage "
        "was found in state."
    )

    return list(messages)


def create_compact_checkpoint_state_node(
    max_checkpoint_messages: int,
) -> CompactCheckpointStateNode:
    """
    Create the end-of-turn node that bounds retained checkpoint state.

    It runs only after the agent produced a final response, never in the
    middle of a tool loop.
    """
    if max_checkpoint_messages < 1:
        raise ValueError(
            "max_checkpoint_messages must be greater than or equal to 1."
        )

    def compact_checkpoint_state_node(
        state: AgentState,
    ) -> dict:
        current_messages = state["messages"]

        retained_messages = select_recent_complete_turns(
            messages=current_messages,
            max_checkpoint_messages=max_checkpoint_messages,
        )

        update: dict = {
            # Prepared context is temporary. The next request rebuilds it.
            "prepared_context": [],
        }

        if len(retained_messages) < len(current_messages):
            logger.info(
                "Checkpoint state compacted | before=%s after=%s limit=%s",
                len(current_messages),
                len(retained_messages),
                max_checkpoint_messages,
            )

            update["messages"] = [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *retained_messages,
            ]

        return update

    return compact_checkpoint_state_node