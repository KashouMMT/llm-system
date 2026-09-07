"""
Blank forms for download.

The agent's generate_* tools produce a finished document from data the
user confirmed in conversation. This is the other case: a user who just
wants the empty form to print and fill in by hand. Same templates, same
renderers, but no data, no stored file, and no database row — there is
nothing about a blank form worth persisting.

Kept in its own module rather than in tools.py: this is an HTTP surface,
not a tool the model calls, so it is built from schemas and renderers
alone with none of tools.py's LangChain, storage, or repository wiring.
The web layer imports BLANK_DOCUMENTS from here; the plugin still owns the
list of what a blank form is and how it is rendered.
"""

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from app.plugins.documents.renderers.base import Renderer
from app.plugins.documents.renderers.docx_renderer import DocxRenderer
from app.plugins.documents.renderers.xlsx_renderer import XlsxRenderer
from app.plugins.documents.schemas_rirekisho import Rirekisho
from app.plugins.documents.schemas_shokumu import ShokumuKeirekisho


class BlankableSchema(Protocol):
    """
    A document schema that can hand back an all-empty instance of itself.

    Mirrors the Renderer protocol next door: the concrete type is known
    here, but stating the shape keeps BlankDocument from depending on which
    schema it holds.
    """

    @classmethod
    def blank(cls) -> BaseModel: ...


@dataclass(frozen=True)
class BlankDocument:
    """One document type offered as an empty, fill-by-hand form."""

    schema_cls: type[BlankableSchema]
    renderer: Renderer
    filename: str

    def render(self) -> bytes:
        """The empty form's bytes, rendered fresh on each request."""
        return self.renderer.render(self.schema_cls.blank())


# Keyed by the path segment in GET /documents/blank/{doc_type}. The
# filenames are Japanese on purpose — the file lands on the user's disk,
# and server._attachment_header already carries a UTF-8 name.
#
# dated=False: a blank form must not carry a generation date, or it is
# stale the moment the year turns.
BLANK_DOCUMENTS: dict[str, BlankDocument] = {
    "rirekisho": BlankDocument(
        schema_cls=Rirekisho,
        renderer=XlsxRenderer(dated=False),
        filename="履歴書.xlsx",
    ),
    "shokumu_keirekisho": BlankDocument(
        schema_cls=ShokumuKeirekisho,
        renderer=DocxRenderer(dated=False),
        filename="職務経歴書.docx",
    ),
}
