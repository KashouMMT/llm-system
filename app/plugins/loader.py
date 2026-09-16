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

from app.plugins.contracts import PluginCommand, ToolContext, ToolPlugin
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

# Deliberately no budget constant for plugin prompts, unlike tool schemas
# above. A tool schema's size creeps up per plugin folder without anyone
# deciding to spend it; a plugin_prompt.txt is written by hand, one file,
# read in full by whoever wrote it. The recruitment plugin's is
# persona-sized on purpose. The combined size is logged at startup so it
# can be measured, and SYSTEM_PROMPT_TOKEN_BUDGET still bounds the total
# prompt that is actually sent.


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


def _discover(
    excluded: Collection[str],
    *,
    quiet: bool = False,
) -> tuple[list[ToolPlugin], list[str]]:
    """
    Import every plugin package and collect its PLUGIN declaration.

    `excluded` names the plugin folders to leave out; everything else
    present is loaded. An excluded plugin is never imported at all, so its
    module-level code does not run and its dependencies are never touched.

    Returns the plugins and the names that failed, so a single run
    reports everything that is broken rather than only the first thing.

    `quiet` suppresses only the per-plugin "excluded" line. Startup calls
    this more than once — tools, then commands, then prompts — and the
    exclusion decision is the same every time, so repeating it would make
    the startup log look like three different decisions. Import and
    declaration failures are never quiet.
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

        if info.name in excluded:
            if not quiet:
                logger.info(
                    "Tool plugin skipped | plugin=%s "
                    "reason=in_EXCLUDED_TOOL_PLUGINS",
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
    excluded: Collection[str] = (),
    strict: bool = False,
) -> list[BaseTool]:
    """
    Every tool the agent may call, from every plugin that loaded.

    `excluded` is a denylist of plugin folder names; empty means load
    whatever is present.

    A plugin that fails to import or whose factory raises is logged and
    skipped, so one broken plugin does not take the process down with
    it. `strict` turns that into a startup failure instead, which is the
    right setting anywhere the absence of a tool is not acceptable: the
    user-visible symptom of a silently skipped recruitment plugin is the
    assistant apologising that it cannot make a 履歴書, which reads like
    a model problem rather than a load problem.
    """
    plugins, failed = _discover(excluded)

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


def load_commands(
    context: ToolContext,
    *,
    excluded: Collection[str] = (),
) -> dict[str, PluginCommand]:
    """
    Every slash command namespace, from every plugin that loaded.

    Collected the same way load_tools collects tools: one pass over the
    same plugin discovery, respecting the same EXCLUDED_TOOL_PLUGINS
    denylist automatically — an excluded plugin contributes neither tools
    nor commands, so `/recycle` is not merely refused but unknown. Each plugin's command_factory is called
    with the same ToolContext load_tools hands to its factory, for the
    same reason: a command handler that needs storage or the app's model
    access gets it through a bound closure, never a module global.

    No `strict` parameter: a plugin that fails to import already failed
    inside load_tools's own _discover call, and TOOL_PLUGINS_STRICT already
    turned that into a startup failure there when set; here it just yields
    no commands from that plugin, the same outcome load_tools reaches when
    not strict. A command_factory that raises is treated the same way — a
    broken plugin's commands must not be able to take startup down when its
    tools alone would not have either.

    Two plugins naming the same namespace is never survivable, exactly
    like a duplicate tool name — an ambiguous `/foo` is not something a
    user can route around.
    """
    plugins, _failed = _discover(excluded)

    commands: dict[str, PluginCommand] = {}
    provider_of: dict[str, str] = {}

    for plugin in plugins:
        try:
            provided = list(plugin.command_factory(context))
        except Exception:  # noqa: BLE001
            logger.exception(
                "Plugin command_factory failed | plugin=%s", plugin.name
            )
            continue

        for command in provided:
            if command.namespace in provider_of:
                raise ValueError(
                    f"Duplicate command namespace '/{command.namespace}': "
                    f"provided by both plugin '{provider_of[command.namespace]}' "
                    f"and plugin '{plugin.name}'. Namespaces must be unique."
                )

            provider_of[command.namespace] = plugin.name
            commands[command.namespace] = command

    logger.info(
        "Slash commands ready | namespaces=%s",
        sorted(commands),
    )

    return commands


def load_plugin_prompts(*, excluded: Collection[str] = ()) -> str:
    """
    The system-prompt contributions of every loaded plugin, joined into
    one block for app.llm.system_prompt to append to the persona.

    Collected from the same discovery pass and the same denylist as tools
    and commands, which is the whole point: a plugin that is not loaded
    must not be able to tell the model about tools that are not there.
    Excluding `attachments` has to remove "call read_attachment" from the
    prompt as well as removing the tool.

    Order follows plugin name, like the tool list and for the same
    reason — a prompt that reshuffles itself between restarts busts
    provider-side prompt caching for no benefit.

    No `strict` parameter: a plugin that could not be imported already
    failed inside load_tools' own discovery, where TOOL_PLUGINS_STRICT
    decided what that means. Here it simply contributes nothing.
    """
    plugins, _failed = _discover(excluded, quiet=True)

    sections: list[str] = []
    contributors: list[str] = []

    for plugin in plugins:
        prompt = plugin.system_prompt.strip()

        if not prompt:
            continue

        sections.append(prompt)
        contributors.append(plugin.name)

    combined = "\n\n".join(sections)
    estimated_tokens = _estimate_tokens(combined)

    logger.info(
        "Plugin prompts ready | plugins=%s characters=%s estimated_tokens=%s",
        contributors,
        len(combined),
        estimated_tokens,
    )

    return combined
