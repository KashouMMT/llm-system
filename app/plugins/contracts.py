"""
The contract between the application and a tool plugin.

Small frozen dataclasses, deliberately: a plugin should be able to
declare itself without importing anything from the runtime, and the
runtime should be able to load a plugin without knowing what it does.

The one helper here, load_plugin_prompt, exists because every plugin that
contributes to the system prompt would otherwise write the same four
lines of file reading.
"""

from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from psycopg_pool import AsyncConnectionPool

from app.authentication.models import User
from app.database.agent_role import AgentRole
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.file_repository import FileRepository
from app.services.reply_blocks import ReplyBlocks
from app.storage.base import FileStorage
from app.utils.logger import logger

if TYPE_CHECKING:
    # Type-only: the contract names the router type without making every
    # importer of this module (the CLI included) load FastAPI.
    from fastapi import APIRouter

# The conventional name for a plugin's system-prompt contribution, read
# by load_plugin_prompt from beside the plugin's __init__.py.
PLUGIN_PROMPT_FILE = "plugin_prompt.txt"


def load_plugin_prompt(
    package_file: str,
    filename: str = PLUGIN_PROMPT_FILE,
) -> str:
    """
    Read a plugin's system-prompt contribution from a file beside its
    __init__.py. Call it as load_plugin_prompt(__file__).

    A plugin's model-facing text lives in one of two places and the split
    is deliberate:

    - `plugin_prompt.txt`, returned by this function and injected into the
      system prompt, so it is paid for on **every** turn. Only what a tool
      schema structurally cannot carry belongs here: how several tools fit
      together, lifecycle facts (what does and does not survive a turn),
      and when *not* to call something.
    - `prompts.py` inside the plugin, which holds the text the plugin says
      at runtime — tool descriptions, remedies, messages returned to the
      model. Paid for only when that tool is described or called.

    A missing or unreadable file is logged and returns "" rather than
    raising. The plugin's tools still work without its prompt; failing the
    whole plugin over a text file would be a worse trade than a loud log.
    """
    path = Path(package_file).resolve().parent / filename

    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as error:
        logger.error(
            "Plugin prompt unreadable | path=%s error=%s",
            path,
            error,
        )

        return ""


@dataclass(frozen=True)
class LLMAccess:
    """
    The app's own model, as facts rather than a client — provider, where to
    reach it, the credential, and which model id.

    Data only, deliberately never a "build me a client" factory: the moment
    a plugin can construct arbitrary clients, nothing in the app knows what
    models it is calling or what they cost. A plugin that wants a raw SDK
    client (recycling does — see the TODO's reasoning for the recycling
    plugin) builds exactly one, once, in its own factory closure, from
    these fields. A plugin that wants LangChain's interface instead takes
    ToolContext.chat_model.

    Never log a ToolContext — the api_key lives here.
    """

    provider: str
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class ToolContext:
    """
    Everything a plugin may ask for, assembled once by Application.

    Passed to every factory whether that factory needs a given field or
    not. The alternative — a plugin importing module globals to find its
    storage — is exactly what make_document_tools' closure factory exists
    to prevent: it makes the graph impossible to construct twice, and
    makes a plugin untestable without booting the whole application.

    Only the dependencies something actually uses are here. Adding one
    for a future subsystem is a field here and an argument at the single
    call site in Application. It is deliberately not a generic service
    registry keyed by string or type: a registry trades a type error at
    startup for a KeyError at the moment a tool is called, which is the
    worst possible time to discover a wiring mistake.

    chat_model and llm exist so any plugin can call the app's own model —
    the LangChain client the agent already uses, or the raw facts behind
    it — without a second configuration to keep in sync. Never log this
    object: llm.api_key is a live credential.
    """

    file_storage: FileStorage
    file_repository: FileRepository
    conversation_repository: ConversationRepository
    chat_model: BaseChatModel
    llm: LLMAccess
    # The application's own async pool, for a plugin that owns tables. By
    # convention everything such a plugin does with it lives in its
    # `database/` folder, so deleting the plugin folder removes the code
    # that knows the tables exist. The tables themselves stay behind;
    # accepted, the database is disposable.
    db_pool: AsyncConnectionPool
    # Where a tool puts Markdown the user must see exactly (a scan table),
    # bypassing the model. Pair with app.plugins.run_context for the
    # assistant_message_id to publish into.
    reply_blocks: ReplyBlocks
    # The only way model-written SQL reaches the database: a separate login
    # role that can read exactly what plugins grant it. A plugin grants its
    # own table or view from initialize (agent_role.grant_select) and runs
    # queries with agent_role.query — never through db_pool.
    agent_role: AgentRole


@dataclass(frozen=True)
class RouteContext:
    """
    What a plugin's router_factory gets: the ToolContext, plus the
    server's auth dependencies, which only exist once the API is built.

    The dependencies are the server's own, passed in rather than rebuilt,
    so a plugin route authenticates exactly like every core route. Every
    plugin route already requires sign-in (the server mounts them that
    way); a route that is admin-only adds
    `dependencies=[Depends(context.require_admin)]`, or takes
    `Annotated[User, Depends(context.current_user)]` to know who is asking.
    """

    tool: ToolContext
    current_user: Callable[..., Awaitable[User]]
    require_admin: Callable[..., Awaitable[User]]


@dataclass(frozen=True)
class CommandContext:
    """
    Everything a slash-command handler needs, assembled by
    ChatService.begin_turn.

    Identity comes from here — conversation_id and user, both resolved
    from the authenticated request/session — never from `argument`. Same
    rule read_attachment and the document tools already follow: text the
    model or user supplied is data, not authorization.
    """

    conversation_id: UUID
    user: User
    user_message_id: int
    assistant_message_id: int
    subcommand: str
    argument: str


@dataclass(frozen=True)
class CommandReply:
    """
    A command's reply when what the user sees and what later turns
    remember must differ.

    `content` is shown and saved as the message, verbatim. `context_content`
    replaces it in the model's history and in summarization — a one-line
    placeholder for output that is only for display (a whole catalog
    table), which would otherwise ride along in every later turn's context.
    None means remember `content` itself, the same as returning a plain str.
    """

    content: str
    context_content: str | None = None


# Returns the Markdown written as the assistant message, verbatim — a
# command's output is never passed through the LLM. A CommandReply instead
# of a str also says what the model's history should keep.
CommandHandler = Callable[[CommandContext], Coroutine[Any, Any, "str | CommandReply"]]


@dataclass(frozen=True)
class SubcommandSpec:
    """
    One subcommand, described as data.

    The single source for everything that lists commands: the SLASH
    COMMANDS block in the system prompt, the "unknown subcommand" reply,
    and GET /commands for the frontend's autocomplete — all rendered by
    app/plugins/command_help.py. Written once here so a rename cannot leave
    one of those saying the old thing.

    `admin_only` is enforced by ChatService before the handler runs, and
    hides the subcommand from non-admins in every listing. A handler never
    re-checks it.

    `aliases` are old or alternative names. ChatService resolves them and
    hands the handler the canonical `name`, so a plugin's dispatch table
    holds each subcommand once. They are listed to the frontend (to match
    what a user types) but never to the model, which should only ever
    suggest the current name.
    """

    name: str
    summary: str
    # Argument hint shown after the name, e.g. "[frames]".
    usage: str = ""
    # What to attach to the message, e.g. "one room video, or photos".
    # Empty means the subcommand takes no attachments.
    attachments: str = ""
    aliases: tuple[str, ...] = ()
    admin_only: bool = False


@dataclass(frozen=True)
class PluginCommand:
    """
    One plugin's slash-command namespace, exported alongside its tools.

    ChatService routes a message whose first token is `/<namespace>`
    straight to `handler` before the LLM ever runs — a command is
    deterministic, not a tool the model chooses to call.

    `subcommands` describes what the handler dispatches on. When it is
    non-empty, ChatService answers an unknown subcommand and refuses an
    admin_only one itself, and the handler only ever receives a canonical
    subcommand name. Empty keeps the old contract: every subcommand string
    reaches the handler as typed, and nothing is listed anywhere.
    """

    namespace: str
    handler: CommandHandler
    subcommands: tuple[SubcommandSpec, ...] = ()

    def find(self, subcommand: str) -> SubcommandSpec | None:
        """The spec `subcommand` names, by canonical name or alias."""
        for spec in self.subcommands:
            if subcommand == spec.name or subcommand in spec.aliases:
                return spec

        return None


@dataclass(frozen=True)
class ToolPlugin:
    """
    One plugin's declaration, exported as PLUGIN from its package.

    `factory` is called once at startup and returns the tools the plugin
    provides. It may return an empty sequence — a plugin that decides it
    has nothing to offer is not an error.

    `description` is for the startup log and for a human reading the
    folder. It is never sent to the model; what the model reads is each
    tool's own name and description.

    `system_prompt` is the opposite: text appended to the persona's system
    prompt for as long as this plugin is loaded, so the agent knows how
    the plugin's tools fit together rather than only what each one does.
    Usually `load_plugin_prompt(__file__)`. It rides on every request, so
    a plugin that has nothing a tool description cannot already say should
    leave it empty — which is the default, and the common case.

    `command_factory` is optional and independent of `factory`/tools — a
    plugin may offer either, both, or neither. Same shape as `factory`,
    called once at startup with the same ToolContext, for the same reason:
    a command handler that needs storage or the app's model access still
    gets it through a bound closure, never a module global.

    `initialize` is optional async setup, awaited once after the database
    pool opens and before `factory`/`command_factory` run — the place a
    plugin creates its own tables and seeds them. Async because the pool
    is; the factories stay sync because they only bind closures. A plugin
    whose initialize raises is treated as not loaded: its tools, commands
    and prompt would all describe storage that is not there.

    `router_factory` is optional: the plugin's own HTTP routes, for its UI
    half under ui/src/plugins/<name>/. Called once when the API is built
    (never in CLI mode) and mounted under /plugins/<name>/, only if the
    plugin loaded — so an excluded plugin's endpoints do not exist. FastAPI
    reaches into the plugin only through the router it returns, in the
    plugin's own routes.py.
    """

    name: str
    factory: Callable[[ToolContext], Sequence[BaseTool]]
    description: str = ""
    system_prompt: str = ""
    command_factory: Callable[[ToolContext], Sequence[PluginCommand]] = (
        lambda _context: ()
    )
    initialize: Callable[[ToolContext], Awaitable[None]] | None = None
    router_factory: Callable[[RouteContext], "APIRouter"] | None = None
