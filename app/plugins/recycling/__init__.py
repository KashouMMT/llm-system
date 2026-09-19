from langchain_core.tools import BaseTool

from app.config.settings import RECYCLING_VISION_MODEL
from app.plugins.contracts import (
    PluginCommand,
    ToolContext,
    ToolPlugin,
    load_plugin_prompt,
)
from app.plugins.recycling.commands import (
    RecycleRunner,
    make_recycle_commands,
    make_recycle_runners,
)
from app.plugins.recycling.catalog_tools import make_catalog_tools
from app.plugins.recycling.database import (
    CatalogRepository,
    EvidenceRepository,
    ensure_schema,
    grant_agent_read,
)
from app.plugins.recycling.pipeline.vision import build_client
from app.plugins.recycling.routes import make_routes
from app.plugins.recycling.tools import make_recycle_tools


async def _initialize(context: ToolContext) -> None:
    await ensure_schema(context.db_pool)
    # After ensure_schema, which recreates the view and so drops its old
    # grant. A False here is logged by AgentRole and only disables
    # recycle_query_catalog — the plugin itself keeps loading.
    await grant_agent_read(context.agent_role)


def _build_runners(context: ToolContext) -> dict[str, RecycleRunner]:
    # The raw openai SDK, not ToolContext.chat_model: vision.py's
    # structured-output .parse() call is the part of the pipeline most
    # likely to break in a LangChain rewrite, and it moved across unchanged
    # on purpose (see the TODO's §12 SDK-choice row).
    #
    # Called by both factories below, so startup builds two clients and two
    # sets of runners — once each, never per call. Sharing one would need a
    # cache keyed on the context; not worth it for two cheap objects.
    client = build_client(context.llm.api_key, context.llm.base_url or None)
    model = RECYCLING_VISION_MODEL or context.llm.model

    return make_recycle_runners(
        client=client,
        model=model,
        file_repository=context.file_repository,
        file_storage=context.file_storage,
        catalog_repository=CatalogRepository(context.db_pool),
        evidence_repository=EvidenceRepository(context.db_pool),
    )


def _build_tools(context: ToolContext) -> list[BaseTool]:
    return [
        *make_recycle_tools(_build_runners(context), context.reply_blocks),
        *make_catalog_tools(
            catalog_repository=CatalogRepository(context.db_pool),
            agent_role=context.agent_role,
            reply_blocks=context.reply_blocks,
        ),
    ]


def _build_commands(context: ToolContext) -> tuple[PluginCommand, ...]:
    return make_recycle_commands(_build_runners(context))


PLUGIN = ToolPlugin(
    name="recycling",
    # recycle_scan / recycle_build_catalog / recycle_show_catalog: the same
    # runners as /recycle, reachable from plain chat. Their tables reach
    # the user as reply blocks, never through the model. Plus the catalog
    # knowledge tools: SQL reads as the agent role, typed one-row edits.
    factory=_build_tools,
    description=(
        "/recycle scan / build_catalog / show_catalog as commands and tools, "
        "plus catalog query/create/update/delete tools"
    ),
    # When to call the tools, the confirmation rule, the force-build rule
    # and the capture rules. Here rather than in the meguru persona: they
    # describe this scanner, and must vanish when it is excluded.
    system_prompt=load_plugin_prompt(__file__),
    command_factory=_build_commands,
    # Creates recycling_catalog_items. No seeding: an empty table is an
    # empty catalog, and a catalog build is the only way rows arrive.
    initialize=_initialize,
    # GET /plugins/recycling/catalog, for the catalog browser under
    # Settings → Plugins (ui/src/plugins/recycling/).
    router_factory=make_routes,
)
