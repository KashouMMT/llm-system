"""Single-image item detection via a vision-capable LLM.

This module answers exactly one question: what physical objects are visible in
this image, and how many of each. It knows nothing about exclusion lists,
catalogs or pricing — those are policy, and policy belongs to the caller.
Keeping this boundary is what will let the same function serve the CLI today,
an agent tool later, and a batch job after that.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from openai import OpenAI
from PIL import Image
from pydantic import BaseModel, Field

# Phone photos are 4000px wide and cost tokens proportional to their area, while
# adding nothing a model needs to tell a chair from a microwave. Downscaling is
# the single cheapest cost lever in the whole pipeline.
MAX_IMAGE_EDGE = 1024

# Only .jpg/.png are accepted rather than "whatever Pillow opens", because the
# data URL has to declare a MIME type the API actually supports.
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


class DetectedItem(BaseModel):
    """One kind of object seen in the image, with how many of it there are."""

    label: str = Field(
        description=(
            "The object as a simple lowercase singular common noun, e.g. "
            "'ceiling fan', 'laptop', 'plastic bottle'. No brand, no model, "
            "no adjectives unless they change what the object is."
        )
    )
    count: int = Field(
        description=(
            "How many of this object are visible. Use 0 only when you were "
            "explicitly asked to look for this object and it is absent."
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "How sure you are that this object is present and correctly named, "
            "from 0.0 to 1.0."
        ),
    )


class DetectionResult(BaseModel):
    items: list[DetectedItem]


class DetectionError(RuntimeError):
    """Raised when an image cannot be read or the model returns nothing usable."""


_OPEN_SCAN_PROMPT = """\
List every distinct physical object visible in this image.

Rules:
- Use simple lowercase singular common nouns ("laptop", not "Dell XPS 13 laptop").
- Group identical objects into ONE entry with a count. Six identical chairs is
  one entry with count 6, not six entries.
- Group objects of the same kind even if they differ in colour or size.
- Do NOT identify brands or models. A 2K TV and a 4K TV are both "tv".
- Do NOT assess condition or damage.
- Include structural parts of the room (door, wall, window, floor, ceiling) if
  you see them. The caller filters those out; that is not your job.
- If you are unsure what something is, still list it with your best guess and a
  low confidence rather than omitting it.
"""

_TARGETED_PROMPT = """\
Count how many of each of these objects are visible in this image:

{targets}

Rules:
- Return exactly one entry per object in the list above, in that order.
- Use the object name exactly as written above as the label.
- If an object is not present, return it with count 0.
- Do NOT report anything that is not on the list.
"""


def build_client(api_key: str, base_url: str | None = None) -> OpenAI:
    """Build the API client. Separated so tests can inject a fake."""
    return OpenAI(api_key=api_key, base_url=base_url or None)


def encode_image(image_path: Path) -> str:
    """Read an image, downscale it, and return it as a base64 data URL.

    Re-encoding as JPEG regardless of the input format keeps the payload small
    and the MIME type predictable. Transparency is flattened onto white, since a
    PNG with an alpha channel cannot be saved as JPEG.
    """
    if not image_path.is_file():
        raise DetectionError(f"No such image: {image_path}")
    if image_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise DetectionError(
            f"Unsupported image type '{image_path.suffix}'. "
            f"Expected one of: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )

    try:
        with Image.open(image_path) as image:
            image.load()
            if image.mode in ("RGBA", "LA", "P"):
                flattened = Image.new("RGB", image.size, (255, 255, 255))
                rgba = image.convert("RGBA")
                flattened.paste(rgba, mask=rgba.split()[-1])
                image = flattened
            else:
                image = image.convert("RGB")

            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.LANCZOS)

            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
    except OSError as exc:
        raise DetectionError(f"Could not read {image_path}: {exc}") from exc

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def detect_items(
    image_path: Path,
    *,
    client: OpenAI,
    model: str,
    targets: list[str] | None = None,
    temperature: float | None = None,
) -> DetectionResult:
    """Detect objects in one image.

    With `targets`, the model counts only those objects (inclusion mode). Without
    it, the model enumerates everything it can see (open scan). Open scan is the
    default because an exclusion list can only remove what was reported in the
    first place.

    `temperature` is omitted by default because gpt-5.6-luna rejects the
    parameter outright ("Only the default (1) value is supported"), as reasoning
    models generally do. Pass a float only for a model that accepts one — and
    note that even at 0.0 it would not remove all drift, since some of the
    variation is the model making a genuine judgement call (is that a "table" or
    a "desk"?) rather than sampling noise. Stabilisation is `consensus.py`'s job,
    not the sampler's.
    """
    data_url = encode_image(image_path)

    if targets:
        instruction = _TARGETED_PROMPT.format(
            targets="\n".join(f"- {name}" for name in targets)
        )
    else:
        instruction = _OPEN_SCAN_PROMPT

    # Built as a dict so an unset temperature is *absent* rather than None —
    # reasoning models reject the parameter outright rather than ignoring it.
    optional: dict[str, object] = {}
    if temperature is not None:
        optional["temperature"] = temperature

    try:
        completion = client.chat.completions.parse(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            response_format=DetectionResult,
            **optional,
        )
    except Exception as exc:  # the SDK raises a family of errors; all are fatal here
        raise DetectionError(f"Model call failed: {exc}") from exc

    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise DetectionError(
            "The model returned no parseable result "
            f"(finish_reason={completion.choices[0].finish_reason})."
        )
    return parsed
