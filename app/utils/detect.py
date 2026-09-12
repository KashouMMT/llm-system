"""
File type detection for uploads, by content rather than by claim.

A declared Content-Type or filename extension is something the caller
wrote, not something the bytes prove — so the upload endpoint never
trusts either. Everything here reads the bytes themselves.

The allowlist is deliberately narrow, and it is an application decision
rather than any one persona's: png, jpeg and webp images, pdf, and plain
text in UTF-8 or Shift_JIS (which covers .txt, .md, .csv, .json and the
like — they are all just text). Office formats are out on purpose: a
.docx or .xlsx is mostly tables and layout, and extracting only its
paragraphs silently hands the model half a document. A user with one is
asked for a PDF or a screenshot instead.

No third-party sniffing library: python-magic needs the system libmagic,
which is an extra install step this project does not otherwise require.
Four fixed signatures plus a text decode attempt cover the whole
allowlist with the standard library and Pillow.
"""

import io
import re

from PIL import Image, UnidentifiedImageError

IMAGE_PNG = "image/png"
IMAGE_JPEG = "image/jpeg"
IMAGE_WEBP = "image/webp"
APPLICATION_PDF = "application/pdf"
TEXT_PLAIN = "text/plain"

# The one definition every caller checks against — the upload endpoint,
# the manifest, the vision path and read_attachment previously each kept
# their own copy, which is how a new image type ends up half supported.
IMAGE_CONTENT_TYPES = frozenset({IMAGE_PNG, IMAGE_JPEG, IMAGE_WEBP})

# What FileStorage.write() needs as the key's extension. Kept next to the
# content-type constants so the two cannot drift apart silently.
EXTENSION_BY_CONTENT_TYPE = {
    IMAGE_PNG: "png",
    IMAGE_JPEG: "jpg",
    IMAGE_WEBP: "webp",
    APPLICATION_PDF: "pdf",
    TEXT_PLAIN: "txt",
}

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_PDF_MAGIC = b"%PDF-"
_RIFF_MAGIC = b"RIFF"
_WEBP_FORM = b"WEBP"

# Tried in order. utf-8-sig rather than utf-8 so a BOM — which Windows
# Notepad and Excel both write — is stripped instead of reaching the model
# as a stray U+FEFF. cp932 rather than the strict shift_jis codec: it is
# what Windows actually writes under the name "Shift_JIS", including the
# NEC and IBM extensions (①, ㈱, 髙) that strict shift_jis rejects.
#
# UTF-8 goes first because the reverse order is wrong: a lot of UTF-8
# Japanese also happens to decode as cp932 — into mojibake — whereas
# cp932 text that is not plain ASCII almost never decodes as valid UTF-8.
TEXT_ENCODINGS = ("utf-8-sig", "cp932")

# C0 control bytes other than tab, newline, form feed and carriage return,
# plus DEL. Real text never contains them and nearly every binary format
# does. Checking the bytes is valid for both encodings: neither UTF-8 nor
# cp932 ever uses a byte below 0x40 as part of a multi-byte character, so
# a match here is always a real control character, never half of a kanji.
_BINARY_BYTES = re.compile(rb"[\x00-\x08\x0b\x0e-\x1f\x7f]")

# Generous for a phone photo (a 108MP sensor is ~108 million pixels) while
# still bounding decode cost — a small file can claim a huge frame size
# without the pixels ever being present, which is the decompression-bomb
# shape this guards against. Set once, at import: it is a process-wide
# Pillow setting, and app/utils/images.py relies on it being in force too.
Image.MAX_IMAGE_PIXELS = 120_000_000


def sniff_content_type(data: bytes) -> str | None:
    """
    Identify one of the allowed types from its bytes, or None.

    None means "reject" — the caller turns that into a 415. There is no
    partial match: a file that is not confidently one of the allowed
    shapes is not guessed at.
    """
    if data.startswith(_PNG_MAGIC):
        return IMAGE_PNG

    if data.startswith(_JPEG_MAGIC):
        return IMAGE_JPEG

    if data.startswith(_RIFF_MAGIC) and data[8:12] == _WEBP_FORM:
        return IMAGE_WEBP

    if data.startswith(_PDF_MAGIC):
        return APPLICATION_PDF

    if decode_text(data) is not None:
        return TEXT_PLAIN

    return None


def decode_text(data: bytes) -> str | None:
    """
    The text of a UTF-8 or Shift_JIS file, or None if it is neither.

    Shared by upload sniffing and read_attachment, so a file accepted as
    text is always decoded the same way when it is read. The encoding is
    not stored: re-detecting it is cheap, and a stored value would be one
    more column that could disagree with the bytes.
    """
    if _BINARY_BYTES.search(data):
        return None

    for encoding in TEXT_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue

    return None


def is_valid_image(data: bytes) -> bool:
    """
    Confirm an image sniffed as png/jpeg/webp actually decodes, within the
    pixel cap set above.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return False

    return True
