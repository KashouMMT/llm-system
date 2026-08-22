from langchain_ollama import ChatOllama

from app.config.settings import (
    CONTEXT_WINDOW,
    MAX_TOKENS,
    MODEL_NAME,
    TEMPERATURE,
    TOP_P,
)
from app.utils.logger import logger


class LLMFactory:
    @staticmethod
    def create() -> ChatOllama:
        logger.info(f"Loading LLM | model={MODEL_NAME}")

        return ChatOllama(
            model=MODEL_NAME,
            temperature=TEMPERATURE,
            num_ctx=CONTEXT_WINDOW,
            num_predict=MAX_TOKENS,
            top_p=TOP_P,
        )
