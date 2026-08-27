from langchain_ollama import ChatOllama

from app.config.settings import (
    CONTEXT_WINDOW,
    MAX_TOKENS,
    MODEL_NAME,
    OLLAMA_BASE_URL,
    TEMPERATURE,
    TOP_K,
    TOP_P,
)
from app.utils.logger import logger


def create() -> ChatOllama:
    logger.info(
        "Loading LLM | provider=ollama model=%s base_url=%s",
        MODEL_NAME,
        OLLAMA_BASE_URL,
    )

    return ChatOllama(
        model=MODEL_NAME,
        base_url=OLLAMA_BASE_URL,
        temperature=TEMPERATURE,
        num_ctx=CONTEXT_WINDOW,
        num_predict=MAX_TOKENS,
        top_k=TOP_K,
        top_p=TOP_P,
    )
