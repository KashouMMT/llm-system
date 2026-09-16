"""
Every piece of model-facing text this plugin says at runtime.

The split this module exists for: `plugin_prompt.txt` beside it is the
plugin's *standing* contribution to the system prompt, paid for on every
turn whether or not an attachment is involved. Everything here is said
only when a tool is described or called, so it can afford to be specific.

Keeping it in one file rather than inline in tools.py means the wording
the model reads can be reviewed — and changed — without reading the
extraction logic, and makes it obvious when a message has quietly grown
into an instruction that belonged in the system prompt instead.

Templates use str.format placeholders. The page-size ones take
`page_size` from tools.py's _PAGE_SIZE_CHARS rather than restating the
number, so the text and the pagination can never disagree.
"""

from app.config.settings import LLM_SUPPORTS_VISION

# What the model should ask the user for when a PDF has no text to read.
# A screenshot only helps a model that can see it.
NO_TEXT_REMEDY = (
    "Tell the user this, and ask them to send screenshots or photos of "
    "those pages instead — you can view images."
    if LLM_SUPPORTS_VISION
    else "Tell the user this, and ask them to paste or type the content you "
    "need — you cannot view images in this deployment."
)

# Sent to the model on every single call as part of the tool schema,
# alongside the argument descriptions below.
READ_ATTACHMENT_DESCRIPTION = """\
Read the extracted text of a PDF or plain-text file (UTF-8 or Shift_JIS)
that was attached to this conversation. Use the id from its
[attachment id=...] manifest line — never a filename.

Text comes back in pages of about {page_size:,} characters, one at a time.
The response tells you the page number and how many pages exist; call again
with a higher page to keep reading a long document.

For an image, this returns only its metadata: images are visible to you
only on the turn they were attached, never through this tool.

An id that does not belong to this conversation, or does not exist,
returns a not-found message rather than an error.
"""

ATTACHMENT_ID_ARG = (
    "The attachment's id, exactly as it appears in its "
    "[attachment id=...] manifest line."
)

PAGE_ARG = "Which ~{page_size:,}-character page to read, starting at 1."

# Deliberately the same answer for a malformed id, a missing row, and a
# row belonging to another conversation. The model supplied the id, so
# distinguishing them would say whether a file it cannot reach exists.
NOT_FOUND = "Attachment not found."

IMAGE_ONLY = (
    "{name} is an image ({content_type}, {size_bytes} bytes). Images are "
    "visible to you only on the turn they were attached, not through this "
    "tool."
)

UNREADABLE_TYPE = (
    "{name} is a {content_type} file, which this tool cannot read. If its "
    "content matters, ask the user to send it as a PDF, a text file, or a "
    "screenshot."
)

PASSWORD_PROTECTED = (
    "{name} is password-protected and cannot be read. Ask the user to send "
    "a copy without the password."
)

EXTRACTION_FAILED = "Could not read {name}: the file could not be processed."

EMPTY = "{name} is empty."

NO_TEXT_AT_ALL = (
    "{name} contains no text at all — it is almost certainly a scanned or "
    "photographed document ({pdf_pages} page(s)), which this tool cannot "
    "read. {remedy}"
)

# Prefixed to every page of output when only *some* pages lack text, so
# the model sees it whichever page it reads. Without it, a PDF with a
# typed cover page and a scanned body reads as a one-page document.
PARTIAL_SCAN_NOTE = (
    "Note: {pages_without_text} of {pdf_pages} pages contain no text — they "
    "are probably scanned images, and their content is missing below. "
    "{remedy}\n\n"
)

PAGE_RESULT = "{note}{name} — page {page} of {total}:\n\n{text}"
