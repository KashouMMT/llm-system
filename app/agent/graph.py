import time
from collections.abc import AsyncIterator, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.agent.context.conversation_context_builder import (
    ConversationContextBuilder,
)
from app.agent.nodes.agent_node import create_agent_node
from app.agent.nodes.compact_checkpoint_state_node import (
    create_compact_checkpoint_state_node,
)
from app.agent.nodes.prepare_context_node import (
    create_prepare_context_node,
)
from app.agent.state import AgentState
from app.config.runtime_settings import RuntimeSettingsHolder
from app.utils.logger import logger


def _report_tool_error(error: Exception) -> str:
    """
    Log a rejected tool call, then hand the reason back to the model.

    ToolNode otherwise swallows the exception into a ToolMessage and nothing
    reaches the log at all — an argument rejected by a tool's schema leaves
    no trace, so "the assistant kept asking me for things" is impossible to
    diagnose after the fact.

    The return value is what the model reads, so it must stay specific:
    Pydantic's message names the offending field and why, which is exactly
    what lets the model ask the user the right question.
    """
    logger.warning(
        "Tool call rejected | error=%s: %s",
        type(error).__name__,
        error,
    )

    return (
        f"The tool rejected this call: {error}\n"
        "Correct the arguments, or ask the user for what is missing. "
        "Do not invent a value to satisfy the tool."
    )


class AgentGraph:
    """
    Builds and executes the LangGraph agent.

    Workflow:

        START
          ↓
        prepare_context
          ↓
        agent
          ├─ tool call → tools → agent
          └─ final answer → compact_checkpoint_state → END
    """

    def __init__(
        self,
        llm: BaseChatModel,
        settings: RuntimeSettingsHolder,
        provider: str,
        tools: Sequence[BaseTool],
        checkpointer: AsyncPostgresSaver,
        conversation_context_builder: ConversationContextBuilder,
    ) -> None:
        self.llm = llm
        self.settings = settings
        self.provider = provider
        self.tools = tools
        self.checkpointer = checkpointer
        self.conversation_context_builder = conversation_context_builder

        logger.debug(
            "Initializing AgentGraph | tools=%s provider=%s",
            [tool.name for tool in tools],
            provider,
        )

        self.graph = self._build_graph()

        logger.info("AgentGraph initialized")

    def _build_graph(self):
        builder = StateGraph(AgentState)

        prepare_context_node = create_prepare_context_node(
            conversation_context_builder=self.conversation_context_builder,
        )

        agent_node = create_agent_node(
            llm=self.llm,
            settings=self.settings,
            provider=self.provider,
            tools=self.tools,
        )

        tool_node = ToolNode(self.tools, handle_tool_errors=_report_tool_error)

        compact_checkpoint_state_node = create_compact_checkpoint_state_node(
            settings=self.settings,
        )

        logger.debug("Adding graph node | node=prepare_context")
        builder.add_node("prepare_context", prepare_context_node)

        logger.debug("Adding graph node | node=agent")
        builder.add_node("agent", agent_node)

        logger.debug("Adding graph node | node=tools")
        builder.add_node("tools", tool_node)

        logger.debug("Adding graph node | node=compact_checkpoint_state")
        builder.add_node(
            "compact_checkpoint_state",
            compact_checkpoint_state_node,
        )

        logger.debug("Adding graph edge | START -> prepare_context")
        builder.add_edge(START, "prepare_context")

        logger.debug("Adding graph edge | prepare_context -> agent")
        builder.add_edge("prepare_context", "agent")

        logger.debug(
            "Adding conditional edges | agent -> tools/compact_checkpoint_state"
        )
        builder.add_conditional_edges(
            "agent",
            tools_condition,
            {
                "tools": "tools",
                END: "compact_checkpoint_state",
            },
        )

        logger.debug("Adding graph edge | tools -> agent")
        builder.add_edge("tools", "agent")

        logger.debug("Adding graph edge | compact_checkpoint_state -> END")
        builder.add_edge("compact_checkpoint_state", END)

        graph = builder.compile(
            checkpointer=self.checkpointer,
        )

        logger.info("Agent graph compiled successfully")

        return graph

    async def stream(
        self,
        input_messages: Sequence[BaseMessage],
        thread_id: str,
        current_user_message_id: int | None = None,
        assistant_message_id: int | None = None,
    ) -> AsyncIterator[tuple[BaseMessage, dict]]:
        start = time.perf_counter()

        logger.debug(
            "Graph execution started | thread=%s input_messages=%s",
            thread_id,
            len(input_messages),
        )

        config: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                # The current turn is already persisted when generation
                # starts. prepare_context uses this to exclude it from
                # history, so the model does not see the question twice.
                "current_user_message_id": current_user_message_id,
                # The assistant row this run is writing into. A tool that
                # produces a file attaches it here, so the identity comes
                # from the server rather than from the model.
                "assistant_message_id": assistant_message_id,
            }
        }

        async for message_chunk, metadata in self.graph.astream(
            {"messages": input_messages},
            config=config,
            stream_mode="messages",
        ):
            yield message_chunk, metadata

        elapsed = time.perf_counter() - start

        logger.debug(
            "Graph execution completed | thread=%s elapsed=%.2fs",
            thread_id,
            elapsed,
        )
