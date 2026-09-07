"""
Filesystem loading for the persona + summarization prompt set.

A *prompt set* is a directory under ``app/prompts/`` named by
``SYSTEM_PROMPT`` (or the runtime ``system_prompt_name``). Each set holds
three files:

    system_prompt.txt         the persona
    summary_chunk_prompt.txt  instruction for summarizing one batch of messages
    summary_merge_prompt.txt  instruction for folding a chunk into the summary

The set is all-or-nothing. If the named folder is missing or has an empty
copy of any one of the three files, the whole set is rejected and the
loader falls back to the ``default`` set, logging a warning. This is
deliberate: a half-populated folder must never leave the persona from set
A silently paired with a summarization prompt from ``default``.

This module imports nothing from the rest of the app on purpose —
``settings`` imports it at module load, before the logger is configured,
so a dependency back on ``settings`` (directly or through the app logger)
would be circular.
"""

import logging
from pathlib import Path

logger = logging.getLogger("llm_app")

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# The set used whenever the requested one is incomplete. It must always be
# complete itself; an incomplete default is a broken install, not a
# runtime condition to paper over, so it raises rather than warns.
DEFAULT_SET = "default"

SYSTEM_PROMPT_FILE = "system_prompt.txt"
SUMMARY_CHUNK_PROMPT_FILE = "summary_chunk_prompt.txt"
SUMMARY_MERGE_PROMPT_FILE = "summary_merge_prompt.txt"

REQUIRED_FILES = (
    SYSTEM_PROMPT_FILE,
    SUMMARY_CHUNK_PROMPT_FILE,
    SUMMARY_MERGE_PROMPT_FILE,
)

# Optional per-set file: the assistant's opening message, seeded into a
# conversation when it is created (see system_prompt.load_first_message).
# Not in REQUIRED_FILES — a set without one simply opens with no greeting,
# so adding it must not turn every existing set incomplete.
FIRST_MESSAGE_FILE = "first_message.txt"

# Optional per-set file: the instruction used to name a conversation from
# its first user message (see system_prompt.load_title_prompt). Also not in
# REQUIRED_FILES — a set without one falls back to the built-in
# DEFAULT_TITLE_PROMPT, so titling keeps working for every existing set.
TITLE_PROMPT_FILE = "title_prompt.txt"


def _missing_files(set_dir: Path) -> list[str]:
    """Names of the required files that are absent or empty in ``set_dir``."""
    missing: list[str] = []

    for filename in REQUIRED_FILES:
        path = set_dir / filename

        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            missing.append(filename)

    return missing


def resolve_prompt_set(name: str) -> Path:
    """
    Return the directory of the prompt set to load from.

    Falls back to the ``default`` set, with a warning, when ``name`` names
    a set that is missing or has empty any of its three required files.
    Raises ``FileNotFoundError`` if the ``default`` set itself is
    incomplete.
    """
    requested_dir = PROMPTS_DIR / name
    missing = _missing_files(requested_dir)

    if not missing:
        return requested_dir

    default_dir = PROMPTS_DIR / DEFAULT_SET

    if name == DEFAULT_SET:
        raise FileNotFoundError(
            f"Default prompt set is incomplete: {default_dir} is missing "
            f"or has empty: {', '.join(missing)}."
        )

    logger.warning(
        "Prompt set '%s' is incomplete (missing or empty: %s) — falling "
        "back to the '%s' set for the whole set | path=%s",
        name,
        ", ".join(missing),
        DEFAULT_SET,
        requested_dir,
    )

    default_missing = _missing_files(default_dir)

    if default_missing:
        raise FileNotFoundError(
            f"Default prompt set is incomplete: {default_dir} is missing "
            f"or has empty: {', '.join(default_missing)}."
        )

    return default_dir


def read_prompt_file(set_dir: Path, filename: str) -> str:
    """
    Read one required prompt file from an already-resolved set directory.

    ``resolve_prompt_set`` has verified the file exists and is non-empty;
    the checks here guard against a race or a bad caller, not the normal
    path.
    """
    path = set_dir / filename

    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")

    content = path.read_text(encoding="utf-8").strip()

    if not content:
        raise ValueError(f"Prompt file must not be empty: {path}")

    return content


def read_optional_prompt_file(set_dir: Path, filename: str) -> str | None:
    """
    Read one optional prompt file, or return ``None`` if it is absent or
    empty.

    Unlike ``read_prompt_file`` this never raises for a missing or blank
    file: an optional file that is not there is a normal state, not a
    misconfiguration.
    """
    path = set_dir / filename

    if not path.is_file():
        return None

    content = path.read_text(encoding="utf-8").strip()

    return content or None
