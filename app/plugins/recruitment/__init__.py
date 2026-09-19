from langchain_core.tools import BaseTool

from app.plugins.contracts import ToolContext, ToolPlugin, load_plugin_prompt
from app.plugins.recruitment.routes import make_routes
from app.plugins.recruitment.tools import make_document_tools


def _build(context: ToolContext) -> list[BaseTool]:
    return make_document_tools(
        storage=context.file_storage,
        file_repository=context.file_repository,
        conversation_repository=context.conversation_repository,
    )


PLUGIN = ToolPlugin(
    # Named for the business domain, not for the file format it happens to
    # emit: this plugin is the recruitment product (interviewing a job
    # seeker, validating what they gave, producing 履歴書/職務経歴書 and
    # blank forms), and "documents" read as though any feature that writes
    # a file belonged here. The recycling plugin writes files too.
    name="recruitment",
    factory=_build,
    description="generate_rirekisho / generate_shokumu_keirekisho, plus the blank forms",
    # The recruitment domain knowledge that used to live in anna.txt: which
    # fields the interview collects, what to check before generating, the
    # two tools, and the blank forms. It belongs to the plugin because it
    # is only true while the plugin is loaded — anna.txt kept instructing
    # the model to call generate_rirekisho even in a deployment that had
    # named this plugin in EXCLUDED_TOOL_PLUGINS. The persona file now
    # describes only who Anna is and how she behaves.
    system_prompt=load_plugin_prompt(__file__),
    # GET /plugins/recruitment/blank/{doc_type}, for the sidebar's blank
    # forms (ui/src/plugins/recruitment/).
    router_factory=make_routes,
)
