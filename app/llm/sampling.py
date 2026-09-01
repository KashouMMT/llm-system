from langchain_core.language_models.chat_models import BaseChatModel

from app.config.runtime_settings import RuntimeSettings

# Parameter names differ per provider, so the mapping lives here rather
# than being spread across callers.
_OLLAMA_KEYS = {
    "temperature": "temperature",
    "top_p": "top_p",
    "top_k": "top_k",
    "max_tokens": "num_predict",
    "context_window": "num_ctx",
}

_OPENAI_KEYS = {
    "temperature": "temperature",
    "top_p": "top_p",
    "max_tokens": "max_tokens",
}


def bind_sampling(
    llm: BaseChatModel,
    settings: RuntimeSettings,
    provider: str,
) -> BaseChatModel:
    """
    Return the model with the current sampling parameters applied.

    bind() layers per-invocation overrides on top of the client rather
    than rebuilding it, so a settings change cannot swap a client out
    from under a generation that is already streaming.

    top_k and context_window are Ollama-only; sending them to an
    OpenAI-compatible endpoint is rejected by some hosts and silently
    ignored by others, so they are simply not sent.
    """
    if provider == "ollama":
        # ChatOllama only reads temperature/top_p/top_k/num_predict/
        # num_ctx from its own pydantic fields when building the
        # request's "options" dict (see _chat_params in
        # langchain_ollama). bind() does not set model fields — it only
        # adds extra call-time kwargs — so passing these flat would
        # forward them straight to AsyncClient.chat(**chat_params),
        # which has no such top-level arguments. They must be nested
        # under "options" instead, which _chat_params passes through
        # unchanged when present.
        options = {
            parameter: getattr(settings, field)
            for field, parameter in _OLLAMA_KEYS.items()
        }
        return llm.bind(options=options)

    overrides = {
        parameter: getattr(settings, field) for field, parameter in _OPENAI_KEYS.items()
    }

    return llm.bind(**overrides)
