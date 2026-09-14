"""
The contract between the application and a tool plugin.

Two small frozen dataclasses, deliberately: a plugin should be able to
declare itself without importing anything from the runtime, and the
runtime should be able to load a plugin without knowing what it does.
"""

from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool

from app.authentication.models import User
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.file_repository import FileRepository
from app.storage.base import FileStorage


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
    """

    file_storage: FileStorage
    file_repository: FileRepository
    conversation_repository: ConversationRepository


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


# Returns the Markdown written as the assistant message, verbatim — a
# command's output is never passed through the LLM.
CommandHandler = Callable[[CommandContext], Coroutine[Any, Any, str]]


@dataclass(frozen=True)
class PluginCommand:
    """
    One plugin's slash-command namespace, exported alongside its tools.

    ChatService routes a message whose first token is `/<namespace>`
    straight to `handler` before the LLM ever runs — a command is
    deterministic, not a tool the model chooses to call. `help_text` is
    for a human (the "unknown command" listing); it is never sent to a
    model, unlike a tool's description.
    """

    namespace: str
    handler: CommandHandler
    help_text: str = ""


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

    `commands` is optional and independent of `factory`/tools — a plugin
    may offer either, both, or neither.
    """

    name: str
    factory: Callable[[ToolContext], Sequence[BaseTool]]
    description: str = ""
    commands: Sequence[PluginCommand] = ()
