from langchain_core.language_models.chat_models import BaseChatModel

from app.config.settings import LLM_PROVIDER
from app.llm import ollama_llm, openai_llm

_PROVIDERS = {
    "ollama": ollama_llm.create,
    "openai": openai_llm.create,
}


class LLMFactory:
    @staticmethod
    def create() -> BaseChatModel:
        try:
            factory = _PROVIDERS[LLM_PROVIDER]
        except KeyError:
            raise ValueError(
                f"Unknown LLM_PROVIDER '{LLM_PROVIDER}'. "
                f"Expected one of: {sorted(_PROVIDERS)}"
            ) from None

        return factory()
