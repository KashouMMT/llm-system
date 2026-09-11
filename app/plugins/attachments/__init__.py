from langchain_core.tools import BaseTool

from app.plugins.attachments.tools import make_attachment_tools
from app.plugins.contracts import ToolContext, ToolPlugin


def _build(context: ToolContext) -> list[BaseTool]:
    return make_attachment_tools(
        file_repository=context.file_repository,
        file_storage=context.file_storage,
    )


PLUGIN = ToolPlugin(
    name="attachments",
    factory=_build,
    description="read_attachment — extracted text of an uploaded pdf/docx/text file, paginated",
)
