"""
Who a tool call is running for, read from the run configuration.

A tool function is built once at startup and shared by every user, so the
only trustworthy answer to "who is asking" is what the server put into the
run config for this turn (AgentGraph.stream). Never a tool argument: the
model writes those, and a user can talk it into writing anything.

`run_identity` also gives a tool the CommandContext a slash-command
handler expects, so a tool can reuse a command's handler unchanged rather
than keep a second implementation.
"""

from dataclasses import dataclass
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.authentication.authorization import is_admin
from app.authentication.models import User
from app.plugins.contracts import CommandContext

_REQUIRED_KEYS = ("thread_id", "user", "current_user_message_id", "assistant_message_id")


@dataclass(frozen=True)
class RunIdentity:
    conversation_id: UUID
    user: User
    user_message_id: int
    assistant_message_id: int

    @property
    def is_admin(self) -> bool:
        return is_admin(self.user)

    def command_context(self, subcommand: str, argument: str = "") -> CommandContext:
        return CommandContext(
            conversation_id=self.conversation_id,
            user=self.user,
            user_message_id=self.user_message_id,
            assistant_message_id=self.assistant_message_id,
            subcommand=subcommand,
            argument=argument,
        )


def run_identity(config: RunnableConfig) -> RunIdentity:
    """
    Raises RuntimeError when a key is missing. That is a wiring bug — a
    graph run started without going through ChatService.generate — and
    an admin check must fail closed on it, never default to someone.
    """
    configurable = config.get("configurable") or {}
    missing = [key for key in _REQUIRED_KEYS if configurable.get(key) is None]

    if missing:
        raise RuntimeError(f"Run config is missing {missing}; cannot identify the caller.")

    return RunIdentity(
        conversation_id=UUID(str(configurable["thread_id"])),
        user=configurable["user"],
        user_message_id=configurable["current_user_message_id"],
        assistant_message_id=configurable["assistant_message_id"],
    )
