from langchain_openai import ChatOpenAI

from app.config.settings import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_RETRIES,
    LLM_TIMEOUT_SECONDS,
    MAX_TOKENS,
    MODEL_NAME,
    REASONING_EFFORT,
    TEMPERATURE,
    TOP_P,
)
from app.utils.logger import logger


def create() -> ChatOpenAI:
    if not LLM_API_KEY:
        raise ValueError("LLM_API_KEY must be set when LLM_PROVIDER=openai.")

    if not MODEL_NAME:
        raise ValueError(
            "MODEL_NAME must be set when LLM_PROVIDER=openai "
            "(e.g. 'deepseek/deepseek-chat-v3.1:free' on OpenRouter)."
        )

    logger.info(
        "Loading LLM | provider=openai model=%s base_url=%s",
        MODEL_NAME,
        LLM_BASE_URL or "https://api.openai.com/v1",
    )

    # Sent only when set. Passing reasoning_effort to a model that has no
    # reasoning mode is rejected by OpenAI and by some OpenAI-compatible
    # hosts, so absence has to mean "do not send", not a default value.
    optional: dict[str, str] = {}

    if REASONING_EFFORT:
        optional["reasoning_effort"] = REASONING_EFFORT

    return ChatOpenAI(
        model=MODEL_NAME,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL or None,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        top_p=TOP_P,
        max_retries=LLM_MAX_RETRIES,
        timeout=LLM_TIMEOUT_SECONDS,
        **optional,
    )
