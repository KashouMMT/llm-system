"""
The contract between the application and a tool plugin.

Two small frozen dataclasses, deliberately: a plugin should be able to
declare itself without importing anything from the runtime, and the
runtime should be able to load a plugin without knowing what it does.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from langchain_core.tools import BaseTool

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
class ToolPlugin:
    """
    One plugin's declaration, exported as PLUGIN from its package.

    `factory` is called once at startup and returns the tools the plugin
    provides. It may return an empty sequence — a plugin that decides it
    has nothing to offer is not an error.

    `description` is for the startup log and for a human reading the
    folder. It is never sent to the model; what the model reads is each
    tool's own name and description.
    """

    name: str
    factory: Callable[[ToolContext], Sequence[BaseTool]]
    description: str = ""
