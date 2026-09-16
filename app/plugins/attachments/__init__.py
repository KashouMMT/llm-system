from langchain_core.tools import BaseTool

from app.plugins.attachments.tools import make_attachment_tools
from app.plugins.contracts import ToolContext, ToolPlugin, load_plugin_prompt


def _build(context: ToolContext) -> list[BaseTool]:
    return make_attachment_tools(
        file_repository=context.file_repository,
        file_storage=context.file_storage,
    )


PLUGIN = ToolPlugin(
    name="attachments",
    factory=_build,
    description="read_attachment — extracted text of an uploaded pdf or text file, paginated",
    # plugin_prompt.txt, not the tool's own description: it tells the model
    # that an attachment's contents do not survive the turn, which is a
    # fact about the conversation rather than about calling this tool, and
    # the model has to know it on the turn it decides *whether* to call.
    # It used to live in the shared RESPONSE_FORMAT block, where it was
    # sent even to deployments that do not load this plugin.
    system_prompt=load_plugin_prompt(__file__),
)
