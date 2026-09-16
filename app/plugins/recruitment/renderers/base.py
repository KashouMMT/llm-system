from typing import Protocol

from pydantic import BaseModel


class Renderer(Protocol):
    """
    Turns validated document data into file bytes.

    Deliberately narrow. A renderer knows a schema and a template and
    nothing else — no database, no storage, no LLM. That is what makes the
    .txt implementation swappable for .docx and .xlsx without touching
    anything above it.
    """

    @property
    def extension(self) -> str:
        """File extension without the dot, e.g. 'txt'."""
        ...

    @property
    def content_type(self) -> str:
        """MIME type for the HTTP download response."""
        ...

    def render(self, data: BaseModel) -> bytes: ...
