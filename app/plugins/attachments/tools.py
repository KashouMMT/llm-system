import asyncio
import io
import time
from dataclasses import dataclass
from uuid import UUID

import pypdf
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from app.plugins.attachments import prompts
from app.repositories.file_repository import FileRepository
from app.storage.base import FileStorage
from app.utils.attachment_manifest import READABLE_CONTENT_TYPES
from app.utils.detect import APPLICATION_PDF, IMAGE_CONTENT_TYPES, decode_text
from app.utils.filenames import clean_filename
from app.utils.logger import logger

# A model-facing page size, not the file's own page count — a plain-text
# upload has no native "page" at all, so this is applied uniformly to
# whatever text extraction produced, regardless of format.
#
# The two prompt templates that quote this number take it from here, so
# the text the model reads cannot drift from what pagination does.
_PAGE_SIZE_CHARS = 8000

# A PDF page yielding fewer non-whitespace characters than this is treated
# as having no text layer. Not zero: a scanned page often still carries a
# page number or a stamp that some tool added as real text.
_MIN_CHARS_PER_TEXT_PAGE = 20


class ReadAttachmentArgs(BaseModel):
    attachment_id: str = Field(description=prompts.ATTACHMENT_ID_ARG)
    page: int = Field(
        default=1,
        ge=1,
        description=prompts.PAGE_ARG.format(page_size=_PAGE_SIZE_CHARS),
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

    return prompts.PARTIAL_SCAN_NOTE.format(
        pages_without_text=extracted.pdf_pages_without_text,
        pdf_pages=extracted.pdf_pages,
        remedy=prompts.NO_TEXT_REMEDY,
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
            return prompts.NOT_FOUND

        file = await file_repository.get_by_id(file_id)

        if file is None or file.conversation_id != conversation_id:
            return prompts.NOT_FOUND

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
            return prompts.IMAGE_ONLY.format(
                name=name,
                content_type=file.content_type,
                size_bytes=file.size_bytes,
            )

        if file.content_type not in READABLE_CONTENT_TYPES:
            # An upload from before a type was dropped from the allowlist,
            # or a generated document. Answered explicitly rather than
            # falling through to a decoder that can only fail on it.
            return prompts.UNREADABLE_TYPE.format(
                name=name,
                content_type=file.content_type,
            )

        try:
            data = await file_storage.read(file.storage_key)
            extracted = await asyncio.to_thread(_extract, data, file.content_type)

        except _PasswordProtected:
            return prompts.PASSWORD_PROTECTED.format(name=name)

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

            return prompts.EXTRACTION_FAILED.format(name=name)

        pages = _paginate(extracted.text)

        elapsed = time.perf_counter() - start

        if not pages:
            logger.info(
                "Tool completed | tool=read_attachment file=%s pages=0 elapsed=%.4fs",
                file.id,
                elapsed,
            )

            if extracted.pdf_pages:
                return prompts.NO_TEXT_AT_ALL.format(
                    name=name,
                    pdf_pages=extracted.pdf_pages,
                    remedy=prompts.NO_TEXT_REMEDY,
                )

            return prompts.EMPTY.format(name=name)

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

        return prompts.PAGE_RESULT.format(
            note=_scanned_note(extracted),
            name=name,
            page=page_index,
            total=len(pages),
            text=pages[page_index - 1],
        )

    return [
        StructuredTool.from_function(
            coroutine=read_attachment,
            name="read_attachment",
            description=prompts.READ_ATTACHMENT_DESCRIPTION.format(
                page_size=_PAGE_SIZE_CHARS,
            ),
            args_schema=ReadAttachmentArgs,
        )
    ]
