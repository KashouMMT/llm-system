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
MODEL_NAME = get_valid_string("MODEL_NAME", "")
SYSTEM_PROMPT = get_valid_string("SYSTEM_PROMPT", "default")
TEMPERATURE = get_positive_float("TEMPERATURE", 0.3)
MAX_TOKENS = get_positive_int("MAX_TOKENS", 1536)
CONTEXT_WINDOW = get_positive_int("CONTEXT_WINDOW", 8192)
TOP_K = get_positive_int("TOP_K", 40)
TOP_P = get_positive_float("TOP_P", 0.9)

# SUMMARY CONFIGURATION
SUMMARY_TOKEN_THRESHOLD = get_positive_int("SUMMARY_TOKEN_THRESHOLD", 2500)
MAX_CHECKPOINT_MESSAGES = get_positive_int("MAX_CHECKPOINT_MESSAGES", 50)
# MAX_UNSUMMARIZED_MESSAGES ≤ MAX_CONTEXT_HISTORY_MESSAGES.
MAX_CONTEXT_HISTORY_MESSAGES = get_positive_int("MAX_CONTEXT_HISTORY_MESSAGES", 16)
MAX_UNSUMMARIZED_MESSAGES = get_positive_int("MAX_UNSUMMARIZED_MESSAGES", 16)

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
