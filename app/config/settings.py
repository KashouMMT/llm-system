import os
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()


def get_bool(
    environment_name: str,
    default: bool,
) -> bool:
    raw = os.getenv(environment_name)

    if raw is None or not raw.strip():
        return default

    return raw.strip().lower() in ("1", "true", "yes", "on")


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

    return value


def get_valid_string(
    environment_name: str,
    default: str,
) -> str:
    value = os.getenv(environment_name, default)

    if not isinstance(value, str):
        raise ValueError(  # noqa: TRY004
            f"{environment_name} must be a string."
        )

    value = value.strip()

    if not value:
        raise ValueError(f"{environment_name} must not be empty.")

    return value


def read_prompt(filename: str) -> str:
    base_path = Path(__file__).resolve().parent.parent
    prompts_dir = base_path / "prompts"
    prompt_path = prompts_dir / filename

    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    content = prompt_path.read_text(encoding="utf-8").strip()

    if not content:
        raise ValueError(f"Prompt file must not be empty: {prompt_path}")

    return content


# LLM CONFIGURATION
LLM_PROVIDER = get_valid_string("LLM_PROVIDER", "ollama")  # "ollama" | "openai"
# Transient 429/5xx from shared free-tier pools are common; the OpenAI SDK
# retries these internally with backoff.
LLM_MAX_RETRIES = get_positive_int("LLM_MAX_RETRIES", 3)
LLM_TIMEOUT_SECONDS = get_positive_float("LLM_TIMEOUT_SECONDS", 120.0)
MODEL_NAME = get_valid_string("MODEL_NAME", "qwen3.5:4b")
SYSTEM_PROMPT = get_valid_string("SYSTEM_PROMPT", "default")
# Low temperature: this assistant must not invent facts it was not given.
TEMPERATURE = get_positive_float("TEMPERATURE", 0.3)
# A full 履歴書 + 職務経歴書 does not fit in 1024 tokens and gets cut off
# mid-document. Raise this before lowering CONTEXT_WINDOW.
MAX_TOKENS = get_positive_int("MAX_TOKENS", 2048)
# The system prompt alone is ~2,800 tokens. 8192 leaves too little room for
# summary + history once MAX_TOKENS is reserved for the reply, and Ollama
# truncates from the FRONT — silently dropping the system prompt.
CONTEXT_WINDOW = get_positive_int("CONTEXT_WINDOW", 16384)
TOP_K = get_positive_int("TOP_K", 40)
TOP_P = get_positive_float("TOP_P", 0.9)

# Only used when LLM_PROVIDER=ollama
OLLAMA_BASE_URL = get_valid_string("OLLAMA_BASE_URL", "http://localhost:11434")

# Only used when LLM_PROVIDER=openai (also covers OpenRouter/Groq/DeepSeek/etc,
# since they all speak the OpenAI Chat Completions API)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").strip()
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()

# SUMMARY CONFIGURATION
# The normal trigger. Sized so it fires before MAX_UNSUMMARIZED_MESSAGES
# does: the message cap is a floor against a flood of one-word turns, not
# the primary policy. If the WARNING in should_summarize is what you keep
# seeing in the logs, these two are inverted again.
SUMMARY_TOKEN_THRESHOLD = get_positive_int("SUMMARY_TOKEN_THRESHOLD", 3000)
# Checkpoint messages are never sent to the LLM (agent_node only reads the
# current turn), so this only bounds Postgres checkpoint row size. It is
# NOT context retention — see MIN_RETAINED_RAW_MESSAGES for that.
MAX_CHECKPOINT_MESSAGES = get_positive_int("MAX_CHECKPOINT_MESSAGES", 20)
# MAX_UNSUMMARIZED_MESSAGES ≤ MAX_CONTEXT_HISTORY_MESSAGES, with room to
# spare: at equality, a single late summarization silently drops the oldest
# unsummarized messages out of context.
MAX_CONTEXT_HISTORY_MESSAGES = get_positive_int("MAX_CONTEXT_HISTORY_MESSAGES", 40)
MAX_UNSUMMARIZED_MESSAGES = get_positive_int("MAX_UNSUMMARIZED_MESSAGES", 30)
# Messages held back from summarization so the model always sees recent
# turns verbatim. Summarizing the entire backlog leaves the next turn with
# a paraphrase and nothing literal, which is where the model loses track of
# what was just agreed and starts re-asking settled questions.
# Must be < MAX_UNSUMMARIZED_MESSAGES or summarization can never advance.
MIN_RETAINED_RAW_MESSAGES = get_positive_int("MIN_RETAINED_RAW_MESSAGES", 8)
MAX_SUMMARY_CHARS = get_positive_int("MAX_SUMMARY_CHARS", 6000)

# USER INPUT
MAX_USER_INPUT_CHARS = get_positive_int("MAX_USER_INPUT_CHARS", 4000)

# PROMPT
DEFAULT_PROMPT = """
You are a helpful, intelligent, and reliable AI assistant.
Provide clear, accurate, and thoughtful responses.
""".strip()
SUMMARY_CHUNK_PROMPT = read_prompt("default_summary_chunk_prompt.txt")
SUMMARY_MERGE_PROMPT = read_prompt("default_summary_merge_prompt.txt")

# POSTGRESQL CONFIGURATION
DB_HOST = get_valid_string("DB_HOST", "localhost")
DB_PORT = get_positive_int("DB_PORT", 5432)
DB_NAME = get_valid_string("DB_NAME", "llm_system")
DB_USER = get_valid_string("DB_USER", "postgres")
DB_PASSWORD = get_valid_string("DB_PASSWORD", "")
# psycopg_pool keeps this many connections open and reuses them. Opening a
# connection per query costs a TCP handshake plus a Postgres backend fork,
# which is wasted work on every single repository call.
DB_POOL_MIN_SIZE = get_positive_int("DB_POOL_MIN_SIZE", 2)
DB_POOL_MAX_SIZE = get_positive_int("DB_POOL_MAX_SIZE", 10)
DATABASE_URL = (
    f"postgresql://"
    f"{DB_USER}:"
    f"{quote(DB_PASSWORD, safe='')}"
    f"@{DB_HOST}:"
    f"{DB_PORT}/"
    f"{DB_NAME}"
)

# REALTIME (SSE)
SSE_HEARTBEAT_SECONDS = get_positive_float("SSE_HEARTBEAT_SECONDS", 15.0)
# A subscriber that falls this far behind is dropped rather than buffered
# without bound. The client reconnects and refetches.
SSE_QUEUE_MAXSIZE = get_positive_int("SSE_QUEUE_MAXSIZE", 256)

# AUTHENTICATION
# The root user is seeded from these on startup if no root exists yet.
# Leaving them empty means nobody can log in until a root is created.
# Not stripped: leading/trailing spaces are legitimate in a password.
AUTH_BOOTSTRAP_USERNAME = os.getenv("AUTH_BOOTSTRAP_USERNAME", "").strip()
AUTH_BOOTSTRAP_PASSWORD = os.getenv("AUTH_BOOTSTRAP_PASSWORD", "")

# Absolute session lifetime. No sliding expiry — that is a write on every
# request. 720h = 30 days.
SESSION_TTL_HOURS = get_positive_int("SESSION_TTL_HOURS", 720)

SESSION_COOKIE_NAME = get_valid_string("SESSION_COOKIE_NAME", "session_id")

# Secure cannot be set over plain-HTTP localhost, so it defaults off and is
# turned on in any real deployment. SameSite=Lax already blocks the
# cross-site POST cookie, which is most of the CSRF surface.
COOKIE_SECURE = get_bool("COOKIE_SECURE", False)
COOKIE_SAMESITE = get_valid_string("COOKIE_SAMESITE", "lax")  # lax | strict | none

if COOKIE_SAMESITE not in ("lax", "strict", "none"):
    raise ValueError("COOKIE_SAMESITE must be one of: lax, strict, none")

# LOG CONFIGURATION
LOG_LEVEL = get_valid_string("LOG_LEVEL", "INFO")
CONSOLE_LOG = get_valid_string("CONSOLE_LOG", "false")

# FILE STORAGE
# Relative to the working directory, like app/logs — the process must be
# started from the repository root either way.
FILE_STORAGE_DIR = get_valid_string("FILE_STORAGE_DIR", "app/generated_files")

# Reasoning models reject function tools on /v1/chat/completions unless
# reasoning is explicitly off. Empty means the parameter is not sent at all,
# which is what non-reasoning models and other OpenAI-compatible hosts want.
REASONING_EFFORT = os.getenv("REASONING_EFFORT", "").strip()

# Writes every root-user turn — the user's text, the assistant's reply, and
# each tool call's arguments — to app/logs/conversation_log.log. Deliberately
# separate from LOG_LEVEL: this decides whether conversation *content* is
# written to disk, which is a different question from how verbose logging is.
CONVERSATION_LOG = get_bool("CONVERSATION_LOG", False)
