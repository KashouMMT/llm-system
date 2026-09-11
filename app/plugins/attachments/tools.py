import asyncio
import io
import time
from uuid import UUID

import pypdf
from docx import Document
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from app.repositories.file_repository import FileRepository
from app.storage.base import FileStorage
from app.utils.detect import APPLICATION_DOCX, APPLICATION_PDF, IMAGE_JPEG, IMAGE_PNG
from app.utils.logger import logger

_IMAGE_CONTENT_TYPES = {IMAGE_PNG, IMAGE_JPEG}

# A model-facing page size, not the file's own page count — a docx or a
# plain-text upload has no native "page" at all, so this is applied
# uniformly to whatever text extraction produced, regardless of format.
_PAGE_SIZE_CHARS = 8000

_READ_ATTACHMENT_DESCRIPTION = """\
Read the extracted text of a document (pdf, docx, or plain text) that was
attached to this conversation. Use the id from its [attachment id=...]
manifest line — never a filename.

Text comes back in pages of about 8,000 characters, one at a time. The
response tells you the page number and how many pages exist; call again
with a higher page to keep reading a long document.

For an image, this returns only its metadata: images are visible to you
only on the turn they were attached, never through this tool.

An id that does not belong to this conversation, or does not exist,
returns a not-found message rather than an error.
"""


class ReadAttachmentArgs(BaseModel):
    attachment_id: str = Field(
        description="The attachment's id, exactly as it appears in its "
        "[attachment id=...] manifest line.",
    )
    page: int = Field(
        default=1,
        ge=1,
        description="Which ~8,000-character page to read, starting at 1.",
    )


def _extract_text(data: bytes, content_type: str) -> str:
    """
    Full extracted text for one of the allowed document types.

    Raises on a corrupt or unparseable file — the caller decides how that
    becomes a message to the model; this function's only job is turning
    bytes into text or failing honestly.
    """
    if content_type == APPLICATION_PDF:
        reader = pypdf.PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]

        return "\n\n".join(pages).strip()

    if content_type == APPLICATION_DOCX:
        document = Document(io.BytesIO(data))
        paragraphs = [paragraph.text for paragraph in document.paragraphs]

        return "\n".join(paragraphs).strip()

    # TEXT_PLAIN, the only other non-image type in the upload allowlist.
    return data.decode("utf-8").strip()


def _paginate(text: str, *, page_size: int = _PAGE_SIZE_CHARS) -> list[str]:
    if not text:
        return []

    return [text[start : start + page_size] for start in range(0, len(text), page_size)]


def make_attachment_tools(
    file_repository: FileRepository,
    file_storage: FileStorage,
) -> list[BaseTool]:
    """
    Build the attachment-reading tools with their dependencies bound in —
    same closure-factory shape as make_document_tools, for the same reason:
    a tool needs storage and a repository, and module globals would make
    the graph impossible to construct twice.
    """

    async def read_attachment(
        config: RunnableConfig,
        attachment_id: str,
        page: int = 1,
    ) -> str:
        start = time.perf_counter()

        # Identity comes from the run configuration, never trusted from the
        # model's own argument — the id is model-supplied and could name a
        # file in a conversation that is not this one.
        configurable = config.get("configurable", {})
        conversation_id = UUID(configurable["thread_id"])

        try:
            file_id = UUID(attachment_id)
        except ValueError:
            return "Attachment not found."

        file = await file_repository.get_by_id(file_id)

        if file is None or file.conversation_id != conversation_id:
            return "Attachment not found."

        logger.info(
            "Tool started | tool=read_attachment conversation=%s file=%s page=%s",
            conversation_id,
            file.id,
            page,
        )

        if file.content_type in _IMAGE_CONTENT_TYPES:
            return (
                f"{file.filename} is an image ({file.content_type}, "
                f"{file.size_bytes} bytes). Images are visible to you only "
                "on the turn they were attached, not through this tool."
            )

        try:
            data = await file_storage.read(file.storage_key)
            text = await asyncio.to_thread(_extract_text, data, file.content_type)

        except Exception:  # noqa: BLE001
            # Reported to the model, not raised: an unreadable attachment is
            # data the user supplied, not an application failure, and the
            # model needs to know reading it failed rather than have the
            # turn fail silently around it.
            logger.exception(
                "Attachment extraction failed | conversation=%s file=%s",
                conversation_id,
                file.id,
            )

            return f"Could not read {file.filename}: the file could not be processed."

        pages = _paginate(text)

        elapsed = time.perf_counter() - start

        if not pages:
            logger.info(
                "Tool completed | tool=read_attachment file=%s pages=0 elapsed=%.4fs",
                file.id,
                elapsed,
            )

            return f"{file.filename} contains no extractable text."

        page_index = min(page, len(pages))

        logger.info(
            "Tool completed | tool=read_attachment file=%s page=%s of %s "
            "elapsed=%.4fs",
            file.id,
            page_index,
            len(pages),
            elapsed,
        )

        return (
            f"{file.filename} — page {page_index} of {len(pages)}:\n\n"
            f"{pages[page_index - 1]}"
        )

    return [
        StructuredTool.from_function(
            coroutine=read_attachment,
            name="read_attachment",
            description=_READ_ATTACHMENT_DESCRIPTION,
            args_schema=ReadAttachmentArgs,
        )
    ]
