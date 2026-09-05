import logging
from contextvars import ContextVar
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from app.authentication.authorization import ROLE_ROOT
from app.config.settings import CONVERSATION_LOG

if TYPE_CHECKING:
    from app.authentication.models import User

# Modules whose records belong in the conversation log. Each already logs
# what this file needs — the turn lifecycle, the model's tool decisions,
# each tool's start and finish, and rejected tool calls — so routing them
# here costs no changes at their call sites.
#
# Matched against LogRecord.module, the source file's stem: every module in
# this project shares the one "llm_app" logger, so record.name cannot tell
# them apart. Renaming one of these files silently drops it from the log.
_INCLUDED_MODULES = frozenset(
    {
        "chat_service",
        "agent_node",
        "document_tool",
        "graph",
    }
)

LOG_PATH = Path("app/logs/conversation_log.log")

# Named so set_log_level can leave this handler alone: it must stay at
# DEBUG even when the ordinary handlers are lifted to INFO.
HANDLER_NAME = "conversation_log"


@dataclass(frozen=True)
class Actor:
    """Who the current turn is being generated for."""

    user_id: UUID
    username: str
    role: str


# Set once per turn, in ChatService.begin_turn. asyncio copies the current
# context into every task it creates, so the value set there reaches the
# spawned generation task, the graph run inside it, and each tool call —
# without threading a parameter through any of them. begin_turn is awaited
# rather than spawned, so the set lands in the caller's context, which is
# what the generation task is then copied from.
_actor: ContextVar[Actor | None] = ContextVar(
    "conversation_log_actor",
    default=None,
)


def set_actor(user: "User") -> None:
    _actor.set(Actor(user_id=user.id, username=user.username, role=user.role))


def is_enabled() -> bool:
    """
    Whether the current turn is one the conversation log wants.

    Call sites guard on this before building a message containing the
    user's personal data, so that data is never assembled into a log record
    at all unless this file is on and the actor is root — LOG_LEVEL=DEBUG
    alone must not be enough to write a conversation to the daily log.
    """
    if not CONVERSATION_LOG:
        return False

    actor = _actor.get()

    return actor is not None and actor.role == ROLE_ROOT


# Marks a record as carrying conversation content: the user's own words,
# the assistant's reply, or a tool call's arguments. Records marked this way
# belong to the conversation log and go nowhere else.
CONVERSATION_ONLY = {"conversation_only": True}


class ExcludeConversationContent(logging.Filter):
    """
    Keep conversation content out of the ordinary handlers.

    The daily log and the console take every record at their own level, so
    at LOG_LEVEL=DEBUG they would otherwise copy every name, address and
    phone number the user typed into a second file whose handling nobody
    reasoned about. is_enabled() stops those records existing when
    conversation logging is off; this stops them spreading when it is on.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(record, "conversation_only", False)


class _RootConversationFilter(logging.Filter):
    """
    Admit only root's turns, and only from the modules that describe one.

    Two independent conditions, both required: without the module check the
    file fills with unrelated infrastructure logging, and without the actor
    check another user's conversation lands in a file meant for debugging
    your own.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.module not in _INCLUDED_MODULES:
            return False

        actor = _actor.get()

        return actor is not None and actor.role == ROLE_ROOT


def setup_conversation_log(logger: logging.Logger) -> None:
    """
    Attach the conversation-log handler to the application logger.

    A second handler on the existing logger rather than a logger of its
    own: the records worth reading are already being emitted, and a
    separate logger would mean rewriting every one of those call sites to
    target it.
    """
    if not CONVERSATION_LOG:
        return

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        # Explicit because this file holds Japanese by definition, and the
        # platform default on Windows is a codepage that cannot encode it.
        encoding="utf-8",
    )

    handler.name = HANDLER_NAME
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(module)s | %(message)s"))
    handler.addFilter(_RootConversationFilter())

    logger.addHandler(handler)
