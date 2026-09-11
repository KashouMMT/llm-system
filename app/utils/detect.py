"""
File type detection for uploads, by content rather than by claim.

A declared Content-Type or filename extension is something the caller
wrote, not something the bytes prove — so the upload endpoint never
trusts either. Everything here reads the bytes themselves. The allowlist
is deliberately narrow: png, jpeg, pdf, docx, and utf-8 text are the
shapes a job-application conversation actually needs (a photo for the
rirekisho, an existing resume draft, or pasted plain text) — every
additional type is another sniffer to keep correct and another shape of
input to trust.

No third-party sniffing library: python-magic needs the system libmagic,
which is an extra install step this project does not otherwise require.
Five fixed signatures plus a zip-member check plus a utf-8 decode attempt
covers the whole allowlist with the standard library alone.
"""

import io
import zipfile

from PIL import Image, UnidentifiedImageError

IMAGE_PNG = "image/png"
IMAGE_JPEG = "image/jpeg"
APPLICATION_PDF = "application/pdf"
APPLICATION_DOCX = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
TEXT_PLAIN = "text/plain"

# What FileStorage.write() needs as the key's extension. Kept next to the
# content-type constants so the two cannot drift apart silently.
EXTENSION_BY_CONTENT_TYPE = {
    IMAGE_PNG: "png",
    IMAGE_JPEG: "jpg",
    APPLICATION_PDF: "pdf",
    APPLICATION_DOCX: "docx",
    TEXT_PLAIN: "txt",
}

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"

# A docx is a zip whose package happens to contain this part. Nothing else
# in the allowlist is a zip, so this single member check is enough to tell
# a real docx from an arbitrary zip wearing the extension.
_DOCX_MEMBER = "word/document.xml"

# Generous for a phone photo (a 108MP sensor is ~108 million pixels) while
# still bounding decode cost — a small file can claim a huge frame size
# without the pixels ever being present, which is the decompression-bomb
# shape this guards against.
_MAX_IMAGE_PIXELS = 120_000_000


def sniff_content_type(data: bytes) -> str | None:
    """
    Identify one of the allowed types from its bytes, or None.

    None means "reject" — the caller turns that into a 415. There is no
    partial match: a file that is not confidently one of the five allowed
    shapes is not guessed at.
    """
    if data.startswith(_PNG_MAGIC):
        return IMAGE_PNG

    if data.startswith(_JPEG_MAGIC):
        return IMAGE_JPEG

    if data.startswith(_PDF_MAGIC):
        return APPLICATION_PDF

    if data.startswith(_ZIP_MAGIC):
        return _sniff_zip(data)

    return _sniff_text(data)


def _sniff_zip(data: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return None

    if _DOCX_MEMBER in names:
        return APPLICATION_DOCX

    return None


def _sniff_text(data: bytes) -> str | None:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None

    return TEXT_PLAIN


def is_valid_image(data: bytes) -> bool:
    """
    Confirm an image sniffed as png/jpeg actually decodes, within a pixel
    cap that guards against a decompression bomb (a small file claiming an
    enormous frame size).
    """
    Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return False

    return True
