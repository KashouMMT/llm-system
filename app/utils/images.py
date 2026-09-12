"""
Image transforms for the vision path.

Separate from app/utils/detect.py on purpose: that module classifies
bytes, this one transforms them. It imports detect.py's content-type
constants, which also guarantees Pillow's pixel cap (set at detect.py's
import) is in force before anything here opens an image.
"""

import io

from PIL import ExifTags, Image, ImageOps

from app.utils.detect import IMAGE_JPEG, IMAGE_PNG, IMAGE_WEBP

_PIL_FORMAT_BY_CONTENT_TYPE = {
    IMAGE_PNG: "PNG",
    IMAGE_JPEG: "JPEG",
    IMAGE_WEBP: "WEBP",
}

# Pillow's default JPEG quality is 75, visibly soft on text and fine
# detail — exactly what a vision model is asked to read. PNG ignores it.
_LOSSY_QUALITY = 90

# 1 means "stored upright". Anything else is a phone saying "rotate me".
_UPRIGHT = 1


def downscale_image(data: bytes, content_type: str, *, max_dimension: int) -> bytes:
    """
    Upright, and at most max_dimension on the longer side, in the same
    format.

    A phone does not rotate the pixels of a portrait photo; it stores them
    sideways and records the rotation in an EXIF Orientation tag. Every
    viewer honours the tag, so the photo looks right everywhere — but
    re-encoding writes new pixels without the old EXIF, so a resized photo
    arrived at the model lying on its side. exif_transpose applies the
    rotation to the pixels first, which makes the tag unnecessary.

    Returns the original bytes unchanged only when they are already both
    small enough and upright — re-encoding would otherwise cost quality
    for nothing. Raises on a corrupt or unreadable image; the caller
    decides how to report that.
    """
    with Image.open(io.BytesIO(data)) as image:
        orientation = image.getexif().get(ExifTags.Base.Orientation, _UPRIGHT)

        if max(image.size) <= max_dimension and orientation == _UPRIGHT:
            return data

        upright = ImageOps.exif_transpose(image)
        upright.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

        pil_format = _PIL_FORMAT_BY_CONTENT_TYPE.get(content_type, image.format)

        buffer = io.BytesIO()
        upright.save(buffer, format=pil_format, quality=_LOSSY_QUALITY)

        return buffer.getvalue()
