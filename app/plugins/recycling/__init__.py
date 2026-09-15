from app.config.settings import RECYCLING_VISION_MODEL
from app.plugins.contracts import PluginCommand, ToolContext, ToolPlugin
from app.plugins.recycling.commands import make_recycle_commands
from app.plugins.recycling.pipeline.vision import build_client


def _build_commands(context: ToolContext) -> tuple[PluginCommand, ...]:
    # One raw openai SDK client, built once here — never per call, same
    # reason make_document_tools is a closure. The raw SDK, not
    # ToolContext.chat_model: vision.py's structured-output .parse() call
    # is the part of the pipeline most likely to break in a LangChain
    # rewrite, and it moved across unchanged on purpose (see the TODO's
    # §12 SDK-choice row).
    client = build_client(context.llm.api_key, context.llm.base_url or None)
    model = RECYCLING_VISION_MODEL or context.llm.model

    return make_recycle_commands(
        client=client,
        model=model,
        file_repository=context.file_repository,
        file_storage=context.file_storage,
    )


PLUGIN = ToolPlugin(
    name="recycling",
    # No tools: /recycle never enters the LLM's tool schema, by design —
    # a slash command cannot be confused with an `anna`-persona tool call
    # even when both plugins are loaded in the same deployment.
    factory=lambda _context: [],
    description="/recycle scan_image / scan_video / build_catalog / show_catalog",
    command_factory=_build_commands,
)
