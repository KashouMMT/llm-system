import os
from pathlib import Path
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
LLM_PROVIDER = get_valid_string("LLM_PROVIDER", "ollama") # "ollama" | "openai"
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
SUMMARY_TOKEN_THRESHOLD = get_positive_int("SUMMARY_TOKEN_THRESHOLD", 1200)
# Checkpoint messages are never sent to the LLM (agent_node only reads the
# current turn), so this only bounds Postgres checkpoint row size.
MAX_CHECKPOINT_MESSAGES = get_positive_int("MAX_CHECKPOINT_MESSAGES", 20)
# MAX_UNSUMMARIZED_MESSAGES ≤ MAX_CONTEXT_HISTORY_MESSAGES.
MAX_CONTEXT_HISTORY_MESSAGES = get_positive_int("MAX_CONTEXT_HISTORY_MESSAGES", 12)
MAX_UNSUMMARIZED_MESSAGES = get_positive_int("MAX_UNSUMMARIZED_MESSAGES", 12)

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

# OTHER CONFIGURATION
LOG_LEVEL = get_valid_string("LOG_LEVEL", "INFO")
CONSOLE_LOG = get_valid_string("CONSOLE_LOG", "false")

# REALTIME (SSE)
SSE_HEARTBEAT_SECONDS = get_positive_float("SSE_HEARTBEAT_SECONDS", 15.0)
# A subscriber that falls this far behind is dropped rather than buffered
# without bound. The client reconnects and refetches.
SSE_QUEUE_MAXSIZE = get_positive_int("SSE_QUEUE_MAXSIZE", 256)
