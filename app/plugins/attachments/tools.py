import asyncio
import io
import time
from dataclasses import dataclass
from uuid import UUID

import pypdf
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from app.config.settings import LLM_SUPPORTS_VISION
from app.repositories.file_repository import FileRepository
from app.storage.base import FileStorage
from app.utils.attachment_manifest import READABLE_CONTENT_TYPES
from app.utils.detect import APPLICATION_PDF, IMAGE_CONTENT_TYPES, decode_text
from app.utils.filenames import clean_filename
from app.utils.logger import logger

# A model-facing page size, not the file's own page count — a plain-text
# upload has no native "page" at all, so this is applied uniformly to
# whatever text extraction produced, regardless of format.
_PAGE_SIZE_CHARS = 8000

# A PDF page yielding fewer non-whitespace characters than this is treated
# as having no text layer. Not zero: a scanned page often still carries a
# page number or a stamp that some tool added as real text.
_MIN_CHARS_PER_TEXT_PAGE = 20

# What the model should ask the user for when a PDF has no text to read.
# A screenshot only helps a model that can see it.
_NO_TEXT_REMEDY = (
    "Tell the user this, and ask them to send screenshots or photos of "
    "those pages instead — you can view images."
    if LLM_SUPPORTS_VISION
    else "Tell the user this, and ask them to paste or type the content you "
    "need — you cannot view images in this deployment."
)

_READ_ATTACHMENT_DESCRIPTION = """\
Read the extracted text of a PDF or plain-text file (UTF-8 or Shift_JIS)
that was attached to this conversation. Use the id from its
[attachment id=...] manifest line — never a filename.

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


class _PasswordProtected(Exception):
    """A PDF that cannot be opened without a password the user never gave."""


@dataclass(frozen=True)
class _Extracted:
    text: str
    # PDFs only: how many pages there are, and how many had no text layer.
    # Zero for plain text, which has neither.
    pdf_pages: int = 0
    pdf_pages_without_text: int = 0


def _extract_pdf(data: bytes) -> _Extracted:
    reader = pypdf.PdfReader(io.BytesIO(data))

    # Many "encrypted" PDFs only restrict printing or copying and open with
    # an empty password; only a real user password makes this fail.
    if reader.is_encrypted and not reader.decrypt(""):
        raise _PasswordProtected

    pages = [(page.extract_text() or "").strip() for page in reader.pages]

    return _Extracted(
        text="\n\n".join(page for page in pages if page),
        pdf_pages=len(pages),
        pdf_pages_without_text=sum(
            1 for page in pages if len("".join(page.split())) < _MIN_CHARS_PER_TEXT_PAGE
        ),
    )


def _extract(data: bytes, content_type: str) -> _Extracted:
    """
    Full extracted text for one of READABLE_CONTENT_TYPES.

    Raises on a corrupt file or on text in neither supported encoding —
    the caller decides how that becomes a message to the model; this
    function's only job is turning bytes into text or failing honestly.
    """
    if content_type == APPLICATION_PDF:
        return _extract_pdf(data)

    # TEXT_PLAIN — the only other readable type, so an explicit guard in
    # read_attachment has already turned anything else away.
    text = decode_text(data)

    if text is None:
        raise ValueError("Not decodable as UTF-8 or Shift_JIS.")

    return _Extracted(text=text.strip())


def _paginate(text: str, *, page_size: int = _PAGE_SIZE_CHARS) -> list[str]:
    if not text:
        return []

    return [text[start : start + page_size] for start in range(0, len(text), page_size)]


def _scanned_note(extracted: _Extracted) -> str:
    """
    A warning when some — not all — PDF pages had no text, stated on every
    page of output so the model sees it whichever page it reads.

    Without it, a PDF with a typed cover page and a scanned body reads as a
    one-page document, and the model answers from the cover as if it were
    everything.
    """
    if not extracted.pdf_pages_without_text:
        return ""

    return (
        f"Note: {extracted.pdf_pages_without_text} of {extracted.pdf_pages} "
        "pages contain no text — they are probably scanned images, and their "
        f"content is missing below. {_NO_TEXT_REMEDY}\n\n"
    )


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

        # Cleaned again here, not only at upload: rows written before
        # uploads were cleaned still hold whatever name they arrived with.
        name = clean_filename(file.filename)

        logger.info(
            "Tool started | tool=read_attachment conversation=%s file=%s page=%s",
            conversation_id,
            file.id,
            page,
        )

        if file.content_type in IMAGE_CONTENT_TYPES:
            return (
                f"{name} is an image ({file.content_type}, "
                f"{file.size_bytes} bytes). Images are visible to you only "
                "on the turn they were attached, not through this tool."
            )

        if file.content_type not in READABLE_CONTENT_TYPES:
            # An upload from before a type was dropped from the allowlist,
            # or a generated document. Answered explicitly rather than
            # falling through to a decoder that can only fail on it.
            return (
                f"{name} is a {file.content_type} file, which this tool "
                "cannot read. If its content matters, ask the user to send "
                "it as a PDF, a text file, or a screenshot."
            )

        try:
            data = await file_storage.read(file.storage_key)
            extracted = await asyncio.to_thread(_extract, data, file.content_type)

        except _PasswordProtected:
            return (
                f"{name} is password-protected and cannot be read. Ask the "
                "user to send a copy without the password."
            )

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

            return f"Could not read {name}: the file could not be processed."

        pages = _paginate(extracted.text)

        elapsed = time.perf_counter() - start

        if not pages:
            logger.info(
                "Tool completed | tool=read_attachment file=%s pages=0 elapsed=%.4fs",
                file.id,
                elapsed,
            )

            if extracted.pdf_pages:
                return (
                    f"{name} contains no text at all — it is almost certainly "
                    f"a scanned or photographed document ({extracted.pdf_pages} "
                    f"page(s)), which this tool cannot read. {_NO_TEXT_REMEDY}"
                )

            return f"{name} is empty."

        page_index = min(page, len(pages))

        logger.info(
            "Tool completed | tool=read_attachment file=%s page=%s of %s "
            "pages_without_text=%s elapsed=%.4fs",
            file.id,
            page_index,
            len(pages),
            extracted.pdf_pages_without_text,
            elapsed,
        )

        return (
            f"{_scanned_note(extracted)}"
            f"{name} — page {page_index} of {len(pages)}:\n\n"
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
