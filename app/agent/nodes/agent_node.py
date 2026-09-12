import json
import time
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from app.agent.state import AgentState, get_current_turn_messages
from app.config.runtime_settings import RuntimeSettingsHolder
from app.llm.sampling import bind_sampling
from app.llm.system_prompt import load_system_prompt
from app.utils import conversation_log
from app.utils.logger import logger

AgentNode = Callable[[AgentState, RunnableConfig], dict]


def _with_current_turn_images(
    messages: Sequence[BaseMessage],
    image_blocks: Sequence[dict[str, Any]],
) -> list[BaseMessage]:
    """
    The current turn's messages, with this turn's images joined onto the
    user's message.

    Built fresh for each model call and never returned into state: the
    HumanMessage in state stays plain text, so the checkpointer stores its
    text and not the images (see ChatService._build_turn_input). Every
    model call in the turn's tool loop gets the images again, which is
    what the model would have seen had they been in state.
    """
    if not image_blocks or not messages:
        return list(messages)

    first, *rest = messages

    if not isinstance(first, HumanMessage) or not isinstance(first.content, str):
        # Not a shape ChatService produces. Sending the text without the
        # images is recoverable; failing the turn is not — but it is logged,
        # because images the model never saw is exactly what must not pass
        # unnoticed.
        logger.error(
            "Could not attach %s image(s): current turn does not start with "
            "a text HumanMessage",
            len(image_blocks),
        )
        return list(messages)

    with_images = HumanMessage(
        content=[{"type": "text", "text": first.content}, *image_blocks],
        id=first.id,
    )

    return [with_images, *rest]


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

        current_turn_messages = _with_current_turn_images(
            get_current_turn_messages(state["messages"]),
            config["configurable"].get("current_turn_image_blocks") or [],
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

            # The arguments, not just the names: a wrong date or a dropped
            # 取得 suffix is a fact about what the model passed to the tool,
            # and nothing else in the logs shows it.
            if conversation_log.is_enabled():
                for tool_call in response.tool_calls:
                    logger.debug(
                        "Tool call arguments | conversation=%s tool=%s\n%s",
                        conversation_id,
                        tool_call["name"],
                        json.dumps(
                            tool_call["args"],
                            ensure_ascii=False,
                            indent=2,
                            # dates and UUIDs are not JSON types, and a
                            # logging call must never be what breaks a turn.
                            default=str,
                        ),
                        extra=conversation_log.CONVERSATION_ONLY,
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
