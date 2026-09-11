"""
Image transforms for the vision path.

Separate from app/utils/detect.py on purpose: that module classifies
bytes, this one transforms them — different job, and detect.py must stay
free of Pillow's heavier decode path for the (common) case where nothing
here is ever called.
"""

import io

from PIL import Image

_PIL_FORMAT_BY_CONTENT_TYPE = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
}


def downscale_image(data: bytes, content_type: str, *, max_dimension: int) -> bytes:
    """
    Resize so the longer side is at most max_dimension, preserving aspect
    ratio and format.

    Returns the original bytes unchanged if already within the limit —
    re-encoding a small image would only cost quality for nothing. Raises
    on a corrupt or unreadable image; the caller decides how to report
    that, since "the image could not be prepared" means something
    different to a log line than it does to the model.
    """
    with Image.open(io.BytesIO(data)) as image:
        if max(image.size) <= max_dimension:
            return data

        image.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

        buffer = io.BytesIO()
        image.save(
            buffer,
            format=_PIL_FORMAT_BY_CONTENT_TYPE.get(content_type, image.format),
        )

        return buffer.getvalue()
