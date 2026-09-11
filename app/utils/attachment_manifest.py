"""
The manifest line describing one attachment to the model.

Shared by app/services/chat_service.py (the turn an attachment was just
uploaded on) and app/agent/context/history_context_builder.py (every later
turn), so the two can never describe the same file in different words —
the model would otherwise read one claim about an attachment on the turn
it arrived and a different one when the transcript is replayed back to it.
"""

from app.repositories.file_repository import FileRecord
from app.utils.detect import IMAGE_JPEG, IMAGE_PNG

_IMAGE_CONTENT_TYPES = {IMAGE_PNG, IMAGE_JPEG}


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
    identity = (
        f"[attachment id={file.id} name={file.filename} "
        f"type={file.content_type} size={file.size_bytes}]"
    )

    if file.content_type not in _IMAGE_CONTENT_TYPES:
        return f"{identity} Call read_attachment to read its contents."

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
