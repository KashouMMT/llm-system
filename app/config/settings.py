import os
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()


def get_positive_int(
    environment_name: str,
    default: int,
) -> int:
    value = int(os.getenv(environment_name, str(default)))

    if value < 1:
        raise ValueError(f"{environment_name} must be greater than or equal to 1.")

    return value


def get_positive_float(
    environment_name: str,
    default: float,
) -> float:
    value = float(os.getenv(environment_name, str(default)))

    if value < 0:
        raise ValueError(f"{environment_name} must be greater than 0.")


# LLM CONFIGURATION
MODEL_NAME = os.getenv("MODEL_NAME", "dolphin-phi:latest")
TEMPERATURE = get_positive_float("TEMPERATURE", 0.7)
MAX_TOKENS = get_positive_int("MAX_TOKENS", 512)
CONTEXT_WINDOW = get_positive_int("CONTEXT_WINDOW", 4096)
TOP_P = get_positive_float("TOP_P", 0.9)

# PROMPT
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "default")
DEFAULT_PROMPT = """
You are a helpful, intelligent, and reliable AI assistant.
Provide clear, accurate, and thoughtful responses.
""".strip()

# SUMMARY CONFIGURATION
SUMMARY_TOKEN_THRESHOLD = get_positive_int("SUMMARY_TOKEN_THRESHOLD", 1200)
MAX_CONTEXT_HISTORY_MESSAGES = get_positive_int(
    "MAX_CONTEXT_HISTORY_MESSAGES",
    int(os.getenv("RECENT_MESSAGE_LIMIT", "20")),
)
MAX_CHECKPOINT_MESSAGES = get_positive_int(
    "MAX_CHECKPOINT_MESSAGES",
    50,
)
MAX_UNSUMMARIZED_MESSAGES = get_positive_int("MAX_UNSUMMARIZED_MESSAGES", 100)
SUMMARY_CHUNK_PROMPT = """
You are a memory compression system.

Extract durable conversation memory.

Rules:
- Extract only information explicitly stated by the user.
- Do not infer facts about the user.
- Do not store assistant assumptions.
- Do not store assistant opinions.
- Ignore fictional roleplay details unless confirmed by the user as real.
- Ignore temporary conversational details.
- Prefer long-term useful information.
- If no information exists for a section, leave it empty.

Return ONLY structured notes.

Format:

TOPICS:
- ...

USER_PREFERENCES:
- ...

USER_GOALS:
- ...

FACTS:
- ...

OPEN_ITEMS:
- ...

Conversation:

{conversation}
""".strip()
SUMMARY_MERGE_PROMPT = """
You are maintaining long-term memory.

Merge CURRENT SUMMARY and NEW SUMMARY.

Rules:
- Keep only useful future context.
- Remove duplicates.
- Preserve user preferences.
- Preserve user goals.
- Preserve durable facts.
- Preserve unresolved issues.
- Remove outdated information.
- Remove filler text.
- Keep the summary concise.
- Output ONLY structured memory notes.

Format:

TOPICS:
- ...

USER_PREFERENCES:
- ...

USER_GOALS:
- ...

FACTS:
- ...

OPEN_ITEMS:
- ...

CURRENT SUMMARY:

{current_summary}

NEW SUMMARY:

{chunk_summary}
""".strip()


# OTHER CONFIGURATION
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
CONSOLE_LOG = os.getenv("CONSOLE_LOG", "false")

# POSTGRESQL CONFIGURATION
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_NAME = os.getenv("DB_NAME", "llm_system")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

DATABASE_URL = (
    f"postgresql://"
    f"{DB_USER}:"
    f"{quote(DB_PASSWORD, safe='')}"
    f"@{DB_HOST}:"
    f"{DB_PORT}/"
    f"{DB_NAME}"
)
