from app.config.settings import RECYCLING_VISION_MODEL
from app.plugins.contracts import (
    PluginCommand,
    ToolContext,
    ToolPlugin,
    load_plugin_prompt,
)
from app.plugins.recycling.commands import make_recycle_commands
from app.plugins.recycling.database import CatalogRepository, ensure_schema
from app.plugins.recycling.pipeline.vision import build_client


async def _initialize(context: ToolContext) -> None:
    await ensure_schema(context.db_pool)


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
        catalog_repository=CatalogRepository(context.db_pool),
    )


PLUGIN = ToolPlugin(
    name="recycling",
    # No tools yet: /recycle does not enter the LLM's tool schema. Agent
    # tools are the planned next step — see README.md, "Direction: agent
    # tools".
    factory=lambda _context: [],
    description="/recycle scan / build_catalog / show_catalog",
    # The model cannot run /recycle, so this tells it the commands exist and
    # carries the capture rules. Here rather than in the meguru persona: the
    # rules describe this scanner, and must vanish when it is excluded.
    system_prompt=load_plugin_prompt(__file__),
    command_factory=_build_commands,
    # Creates recycling_catalog_items. No seeding: an empty table is an
    # empty catalog, and /recycle build_catalog is the only way rows arrive.
    initialize=_initialize,
)
