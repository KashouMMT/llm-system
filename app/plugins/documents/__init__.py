from langchain_core.tools import BaseTool

from app.plugins.contracts import ToolContext, ToolPlugin
from app.plugins.documents.tools import make_document_tools


def _build(context: ToolContext) -> list[BaseTool]:
    return make_document_tools(
        storage=context.file_storage,
        file_repository=context.file_repository,
        conversation_repository=context.conversation_repository,
    )


PLUGIN = ToolPlugin(
    name="documents",
    factory=_build,
    description="generate_rirekisho / generate_shokumu_keirekisho",
)
