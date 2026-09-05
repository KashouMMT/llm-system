import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, replace

from app.config.settings import (
    CONTEXT_WINDOW,
    LOG_LEVEL,
    MAX_CHECKPOINT_MESSAGES,
    MAX_CONTEXT_HISTORY_MESSAGES,
    MAX_SUMMARY_CHARS,
    MAX_TOKENS,
    MAX_UNSUMMARIZED_MESSAGES,
    MIN_RETAINED_RAW_MESSAGES,
    SSE_HEARTBEAT_SECONDS,
    SSE_QUEUE_MAXSIZE,
    SUMMARY_TOKEN_THRESHOLD,
    SYSTEM_PROMPT,
    TEMPERATURE,
    TOP_K,
    TOP_P,
)

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Settings that survive a restart. log_level is deliberately absent: it is
# an operational lever, not a preference, and should return to whatever the
# command line or environment says on every start.
PERSISTED_FIELDS = frozenset(
    {
        "summary_token_threshold",
        "max_summary_chars",
        "max_unsummarized_messages",
        "max_context_history_messages",
        "min_retained_raw_messages",
        "sse_heartbeat_seconds",
        "sse_queue_maxsize",
        "temperature",
        "top_p",
        "top_k",
        "max_tokens",
        "context_window",
        "max_checkpoint_messages",
        "system_prompt_name",
    }
)


def _positive_int(name: str, value: object) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer.") from error

    if number < 1:
        raise ValueError(f"{name} must be greater than or equal to 1.")

    return number


def _positive_float(name: str, value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a number.") from error

    if number <= 0:
        raise ValueError(f"{name} must be greater than 0.")

    return number


def _log_level(name: str, value: object) -> str:
    level = str(value).strip().upper()

    if level not in LOG_LEVELS:
        raise ValueError(f"{name} must be one of {', '.join(LOG_LEVELS)}.")

    return level


def _bounded_float(minimum: float, maximum: float):
    """
    Range-checked float parser.

    Bounded rather than merely positive: temperature and top_p have
    meaningful ceilings, and an out-of-range value is rejected by some
    providers and silently clamped by others. Rejecting here means one
    predictable behaviour instead of two.
    """

    def parse(name: str, value: object) -> float:
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} must be a number.") from error

        if not (minimum <= number <= maximum):
            raise ValueError(f"{name} must be between {minimum} and {maximum}.")

        return number

    return parse


def _prompt_name(name: str, value: object) -> str:
    """
    A persona filename, without directory separators.

    Path traversal matters here: this value eventually becomes a filename
    under app/prompts/, and it will one day arrive from an HTTP request.
    """
    text = str(value).strip()

    if not text:
        raise ValueError(f"{name} must not be empty.")

    if not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise ValueError(
            f"{name} may contain only letters, digits, underscore and hyphen."
        )

    return text


# Doubles as the allowlist. A key with no parser cannot be set, by any
# caller, which is what keeps secrets and startup-only settings out of
# reach without a second list to keep in sync.
FIELD_PARSERS: dict[str, Callable[[str, object], object]] = {
    "log_level": _log_level,
    "summary_token_threshold": _positive_int,
    "max_summary_chars": _positive_int,
    "max_unsummarized_messages": _positive_int,
    "max_context_history_messages": _positive_int,
    "min_retained_raw_messages": _positive_int,
    "sse_heartbeat_seconds": _positive_float,
    "sse_queue_maxsize": _positive_int,
    # Sampling. Ceilings chosen to match what providers accept.
    "temperature": _bounded_float(0.0, 2.0),
    "top_p": _bounded_float(0.0, 1.0),
    "top_k": _positive_int,
    "max_tokens": _positive_int,
    "context_window": _positive_int,
    "max_checkpoint_messages": _positive_int,
    "system_prompt_name": _prompt_name,
}


@dataclass(frozen=True)
class RuntimeSettings:
    """
    The settings that may change while the process runs.

    Frozen on purpose. Readers take one snapshot and use it throughout a
    unit of work, so a change landing mid-turn cannot produce behaviour
    that is half old and half new.
    """

    log_level: str
    summary_token_threshold: int
    max_summary_chars: int
    max_unsummarized_messages: int
    max_context_history_messages: int
    min_retained_raw_messages: int
    sse_heartbeat_seconds: float
    sse_queue_maxsize: int
    temperature: float
    top_p: float
    top_k: int
    max_tokens: int
    context_window: int
    max_checkpoint_messages: int
    system_prompt_name: str

    def __post_init__(self) -> None:
        if self.max_tokens >= self.context_window:
            raise ValueError(
                "max_tokens must be less than context_window: the reply is "
                "generated from the same budget as the prompt."
            )
        # A backlog larger than the history window means the oldest
        # unsummarized messages are invisible to the model, with nothing
        # summarizing them. Enforced here so a runtime edit cannot create
        # the state the settings comment only warned about.
        if self.max_unsummarized_messages > self.max_context_history_messages:
            raise ValueError(
                "max_unsummarized_messages must be less than or equal to "
                "max_context_history_messages."
            )
        # Retaining as much as the trigger allows means summarization fires
        # and then has nothing left to fold, so the watermark never moves
        # and the backlog grows until the history window starts dropping it.
        if self.min_retained_raw_messages >= self.max_unsummarized_messages:
            raise ValueError(
                "min_retained_raw_messages must be less than "
                "max_unsummarized_messages: summarization must always have "
                "messages left to fold after the raw tail is held back."
            )

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        return cls(
            log_level=LOG_LEVEL.upper(),
            summary_token_threshold=SUMMARY_TOKEN_THRESHOLD,
            max_summary_chars=MAX_SUMMARY_CHARS,
            max_unsummarized_messages=MAX_UNSUMMARIZED_MESSAGES,
            max_context_history_messages=MAX_CONTEXT_HISTORY_MESSAGES,
            min_retained_raw_messages=MIN_RETAINED_RAW_MESSAGES,
            sse_heartbeat_seconds=SSE_HEARTBEAT_SECONDS,
            sse_queue_maxsize=SSE_QUEUE_MAXSIZE,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            top_k=TOP_K,
            max_tokens=MAX_TOKENS,
            context_window=CONTEXT_WINDOW,
            max_checkpoint_messages=MAX_CHECKPOINT_MESSAGES,
            system_prompt_name=SYSTEM_PROMPT,
        )

    def persisted_values(self) -> dict[str, str]:
        """The persistable subset, as the strings the table stores."""
        return {
            field.name: str(getattr(self, field.name))
            for field in fields(self)
            if field.name in PERSISTED_FIELDS
        }


class RuntimeSettingsHolder:
    """
    Holds the current RuntimeSettings and swaps it atomically.

    Readers go through `current`, never through a captured value, because
    a value imported or stored at construction time can never change.

    No lock: everything runs on one event loop, and an attribute swap
    cannot be interleaved with a read.
    """

    def __init__(self, initial: RuntimeSettings) -> None:
        self._current = initial

    @property
    def current(self) -> RuntimeSettings:
        return self._current

    def apply(self, changes: Mapping[str, object]) -> RuntimeSettings:
        """
        Validate and apply changes, returning the new settings.

        Rejects the whole batch if any key is unknown or any value is
        invalid, so a partially applied update is not a state the system
        can reach.
        """
        if not changes:
            return self._current

        parsed: dict[str, object] = {}

        for key, value in changes.items():
            parser = FIELD_PARSERS.get(key)

            if parser is None:
                raise ValueError(f"Unknown or non-editable setting: {key}")

            parsed[key] = parser(key, value)

        # replace() runs __post_init__, so cross-field invariants are
        # checked against the merged result rather than the change alone.
        self._current = replace(self._current, **parsed)

        return self._current
