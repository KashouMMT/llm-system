import time
from collections.abc import Callable, Sequence
from uuid import UUID

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from app.agent.state import AgentState, get_current_turn_messages
from app.utils.logger import logger
from app.config.runtime_settings import RuntimeSettingsHolder
from app.llm.sampling import bind_sampling
from app.llm.system_prompt import load_system_prompt

AgentNode = Callable[[AgentState, RunnableConfig], dict]


def create_agent_node(
    llm: BaseChatModel,
    settings: RuntimeSettingsHolder,
    provider: str,
    tools: Sequence[BaseTool],
) -> AgentNode:
    """
    Create the LLM decision node.

    Prepared background context comes from the prepare_context node.
    The active tool sequence comes from LangGraph state.

    Sampling parameters and the persona are read per invocation rather
    than captured here, so a settings change reaches the next turn
    without rebuilding the graph.
    """
    llm_with_tools = llm.bind_tools(tools)

    async def agent_node(
        state: AgentState,
        config: RunnableConfig,
    ) -> dict:
        start = time.perf_counter()

        thread_id = config["configurable"]["thread_id"]
        conversation_id = UUID(thread_id)

        prepared_context = state.get("prepared_context")

        if prepared_context is None:
            raise RuntimeError(
                "Prepared context is missing. "
                "The prepare_context node must run before the agent node."
            )

        current_turn_messages = get_current_turn_messages(
            state["messages"],
        )

        logger.debug(
            "Agent node started | conversation=%s "
            "prepared_context_messages=%s current_turn_messages=%s",
            conversation_id,
            len(prepared_context),
            len(current_turn_messages),
        )
        
        # One snapshot for this whole turn. A change landing mid-stream
        # must not apply to half an answer.
        current_settings = settings.current

        system_prompt = load_system_prompt(current_settings.system_prompt_name)

        model = bind_sampling(
            llm_with_tools,
            current_settings,
            provider,
        )

        llm_start = time.perf_counter()

        logger.info(
            "LLM invocation started | conversation=%s",
            conversation_id,
        )

        gathered: AIMessageChunk | None = None

        async for chunk in model.astream(
            [
                SystemMessage(content=system_prompt),
                *prepared_context,
                *current_turn_messages,
            ],
            config=config,
        ):
            gathered = chunk if gathered is None else gathered + chunk

        if gathered is None:
            raise RuntimeError("LLM produced no output chunks for this turn.")

        response = gathered

        llm_elapsed = time.perf_counter() - llm_start

        logger.info(
            "LLM invocation completed | conversation=%s elapsed=%.2fs",
            conversation_id,
            llm_elapsed,
        )

        if response.tool_calls:
            logger.info(
                "LLM requested tools | conversation=%s tools=%s",
                conversation_id,
                [tool["name"] for tool in response.tool_calls],
            )
        else:
            logger.debug(
                "LLM returned final response | conversation=%s",
                conversation_id,
            )

        total_elapsed = time.perf_counter() - start

        logger.debug(
            "Agent node completed | conversation=%s elapsed=%.2fs",
            conversation_id,
            total_elapsed,
        )

        return {
            "messages": [response],
        }

    return agent_node
