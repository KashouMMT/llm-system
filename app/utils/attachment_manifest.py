"""
How attachments are described to the model.

Shared by app/services/chat_service.py (the turn an attachment was just
uploaded on) and app/agent/context/history_context_builder.py (every later
turn), so the two can never describe the same file in different words —
the model would otherwise read one claim about an attachment on the turn
it arrived and a different one when the transcript is replayed back to it.
"""

import json
from collections.abc import Sequence

from app.repositories.file_repository import FileRecord
from app.utils.detect import APPLICATION_PDF, IMAGE_CONTENT_TYPES, TEXT_PLAIN
from app.utils.filenames import clean_filename

# What read_attachment can extract text from. Anything else that is still
# in the files table — an upload from before .docx support was dropped —
# is described as unreadable up front, rather than inviting a tool call
# that can only fail.
READABLE_CONTENT_TYPES = frozenset({APPLICATION_PDF, TEXT_PLAIN})

# Named rather than written inline in the list it heads: a multi-line
# implicit concatenation sitting among other list elements reads like a
# missing comma, which is the ambiguity Ruff's formatter wraps in
# parentheses to resolve. A constant resolves it without the parentheses.
_EARLIER_ATTACHMENTS_HEADER = (
    "Files the user attached earlier in this conversation. Their original "
    "messages are no longer shown, but the files can still be read by id:"
)


def format_attachment_manifest_line(
    file: FileRecord,
    *,
    is_current_turn: bool,
    vision_enabled: bool = False,
    image_prepared: bool = False,
) -> str:
    """
    One line identifying an attachment, plus a note on how — if at all —
    the model can currently see its content.

    is_current_turn: whether this is the turn the attachment arrived on.
    Only that turn can carry image bytes; every later replay of it through
    history says so explicitly rather than letting the model assume an
    image is still in front of it.

    image_prepared: only meaningful when is_current_turn and vision_enabled
    are both true — whether the image actually made it into a content
    block. Reading and downscaling the bytes can fail; when it does, the
    line must not claim the image is shown below only for it to not be
    there, which is why this is a parameter rather than being inferred
    from vision_enabled alone.
    """
    # The name is JSON-quoted as well as cleaned: cleaning removes the
    # newlines and brackets that could forge a whole new line, and quoting
    # stops a name like 'a.pdf type=image/png' from impersonating the
    # fields that follow it.
    name = json.dumps(clean_filename(file.filename), ensure_ascii=False)

    identity = (
        f"[attachment id={file.id} name={name} "
        f"type={file.content_type} size={file.size_bytes}]"
    )

    if file.content_type in READABLE_CONTENT_TYPES:
        if is_current_turn:
            return f"{identity} Call read_attachment to read its contents."

        # An earlier turn's read is not in this turn's context: tool results
        # are never persisted to the transcript, so the model's only record
        # of the file is whatever it said about it at the time. Left at
        # "call read_attachment to read its contents", a model that has
        # already answered about a file treats it as read and answers the
        # next question from that summary — which is how a real test run
        # produced a confidently wrong qualification for the third employee
        # in a CSV it had never re-opened.
        return (
            f"{identity} You have NOT read this file in this turn. Call "
            "read_attachment before answering anything about its contents; "
            "do not rely on what you said about it earlier."
        )

    if file.content_type not in IMAGE_CONTENT_TYPES:
        return (
            f"{identity} This file type cannot be read. If its content "
            "matters, ask the user to send it as a PDF, a text file, or a "
            "screenshot."
        )

    if not is_current_turn:
        return (
            f"{identity} This image was visible to you only on the turn "
            "it was attached; it is not shown again here."
        )

    if not vision_enabled:
        return f"{identity} You cannot view images; vision is disabled."

    if image_prepared:
        return f"{identity} Shown below."

    return (
        f"{identity} Could not be prepared for viewing — treat it as not "
        "visible."
    )


def format_earlier_attachments(
    files: Sequence[FileRecord],
    *,
    omitted: int = 0,
) -> str:
    """
    The block listing attachments whose messages have left the recent
    history window — summarized away, or trimmed off the front.

    Without it an attachment exists for the model only while the message
    that carried it is still shown verbatim; after summarization its id
    is gone, and the model can no longer read a file the user sent twenty
    turns ago and is still asking about.

    omitted is how many older attachments were left out to bound the size
    of this block. It is stated rather than hidden, so the model knows the
    list is incomplete and can ask the user to re-send.
    """
    lines = [
        _EARLIER_ATTACHMENTS_HEADER,
        *(
            format_attachment_manifest_line(file, is_current_turn=False)
            for file in files
        ),
    ]

    if omitted:
        lines.append(
            f"({omitted} older attachment(s) not listed. If the user refers "
            "to one, ask them to attach it again.)"
        )

    return "\n".join(lines)
