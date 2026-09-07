"""
Discovers and loads tool plugins at startup.

A plugin is a *folder* under app/plugins/ whose package exports a
module-level PLUGIN of type ToolPlugin. Folders only: the loader ignores
plain modules in this directory, which is what lets contracts.py and
this file sit beside the plugins without a skip list that someone has
to remember to update.

Loading happens once, in Application.initialize(). There is no reload
and no runtime enable/disable — adding a tool is: drop the folder in,
restart the process.
"""

import importlib
import json
import pkgutil
from collections.abc import Collection
from pathlib import Path

from langchain_core.tools import BaseTool

from app.plugins.contracts import ToolContext, ToolPlugin
from app.utils.logger import logger

PLUGINS_DIR = Path(__file__).resolve().parent

# Every tool's name, description and argument schema is sent to the model
# on every single call, exactly like the system prompt — and a document
# schema's field descriptions are long, because they are instructions.
# A folder scan makes it easy to triple that cost without noticing, so
# the estimate is logged at startup and warned about past this. Crossing
# it is a prompt to disable a plugin, not a failure.
#
# Tune this against the estimated_tokens value in the startup log rather
# than by guessing.
TOOL_SCHEMA_TOKEN_BUDGET = 3000


def _estimate_tokens(text: str) -> int:
    """
    Rough token count, using the same 4-chars-per-token heuristic as
    system_prompt and SummarizationService so the three do not drift
    apart. Undercounts Japanese badly; adequate for a budget warning.
    """
    return len(text) // 4


def _estimate_tool_tokens(tool: BaseTool) -> int:
    try:
        arguments = json.dumps(tool.args, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        # A budget warning must never be the reason startup fails, and
        # how a BaseTool exposes its schema is a LangChain detail this
        # module has no business asserting on.
        logger.debug("Could not read tool schema | tool=%s", tool.name)
        arguments = ""

    return _estimate_tokens(f"{tool.name}{tool.description}{arguments}")


def _discover(enabled: Collection[str]) -> tuple[list[ToolPlugin], list[str]]:
    """
    Import every plugin package and collect its PLUGIN declaration.

    Returns the plugins and the names that failed, so a single run
    reports everything that is broken rather than only the first thing.
    """
    plugins: list[ToolPlugin] = []
    failed: list[str] = []

    # Sorted, because the resulting tool list is prompt text: unsorted
    # filesystem order would change the prompt between restarts for no
    # reason, which busts provider-side prompt caching and makes two
    # runs incomparable.
    candidates = sorted(
        (info for info in pkgutil.iter_modules([str(PLUGINS_DIR)]) if info.ispkg),
        key=lambda info: info.name,
    )

    for info in candidates:
        if info.name.startswith("_"):
            continue

        if enabled and info.name not in enabled:
            logger.info(
                "Tool plugin skipped | plugin=%s reason=not_in_ENABLED_TOOL_PLUGINS",
                info.name,
            )
            continue

        try:
            module = importlib.import_module(f"{__package__}.{info.name}")
        except Exception:  # noqa: BLE001
            logger.exception("Tool plugin failed to import | plugin=%s", info.name)
            failed.append(info.name)
            continue

        plugin = getattr(module, "PLUGIN", None)

        if not isinstance(plugin, ToolPlugin):
            reason = (
                "package exports no PLUGIN"
                if plugin is None
                else f"PLUGIN is {type(plugin).__name__}, expected ToolPlugin"
            )
            logger.error(
                "Tool plugin is not usable | plugin=%s reason=%s",
                info.name,
                reason,
            )
            failed.append(info.name)
            continue

        plugins.append(plugin)

    return plugins, failed


def load_tools(
    context: ToolContext,
    *,
    enabled: Collection[str] = (),
    strict: bool = False,
) -> list[BaseTool]:
    """
    Every tool the agent may call, from every plugin that loaded.

    `enabled`, when non-empty, is an allowlist of plugin names; empty
    means load whatever is present.

    A plugin that fails to import or whose factory raises is logged and
    skipped, so one broken plugin does not take the process down with
    it. `strict` turns that into a startup failure instead, which is the
    right setting anywhere the absence of a tool is not acceptable: the
    user-visible symptom of a silently skipped document plugin is the
    assistant apologising that it cannot make a 履歴書, which reads like
    a model problem rather than a load problem.
    """
    plugins, failed = _discover(enabled)

    tools: list[BaseTool] = []
    provider_of: dict[str, str] = {}

    for plugin in plugins:
        try:
            provided = list(plugin.factory(context))
        except Exception:  # noqa: BLE001
            logger.exception("Tool plugin factory failed | plugin=%s", plugin.name)
            failed.append(plugin.name)
            continue

        for tool in provided:
            if tool.name in provider_of:
                # Never survivable, strict or not. Two tools sharing a
                # name means the model is handed an ambiguous schema and
                # chooses between them arbitrarily — a bug that surfaces
                # as the wrong document being generated, days later.
                raise ValueError(
                    f"Duplicate tool name '{tool.name}': provided by both "
                    f"plugin '{provider_of[tool.name]}' and plugin "
                    f"'{plugin.name}'. Tool names must be unique."
                )

            provider_of[tool.name] = plugin.name

        tools.extend(provided)

        logger.info(
            "Tool plugin loaded | plugin=%s tools=%s",
            plugin.name,
            [tool.name for tool in provided],
        )

    estimated_tokens = sum(_estimate_tool_tokens(tool) for tool in tools)

    logger.info(
        "Tool plugins ready | loaded=%s failed=%s tools=%s estimated_tokens=%s",
        [plugin.name for plugin in plugins],
        failed,
        len(tools),
        estimated_tokens,
    )

    if estimated_tokens > TOOL_SCHEMA_TOKEN_BUDGET:
        logger.warning(
            "Tool schemas exceed token budget | estimated_tokens=%s budget=%s "
            "tools=%s. This is paid on every model call.",
            estimated_tokens,
            TOOL_SCHEMA_TOKEN_BUDGET,
            len(tools),
        )

    if not tools:
        # Not fatal — a conversation-only deployment is legitimate — but
        # it is almost always a misconfigured allowlist.
        logger.warning("No tools loaded; the agent will not be able to call any")

    if failed and strict:
        raise RuntimeError(
            f"Tool plugins failed to load: {failed}. "
            "Set TOOL_PLUGINS_STRICT=false to boot without them."
        )

    return tools
