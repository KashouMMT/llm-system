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

from app.plugins.recycling.pipeline import prompts

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


def build_client(api_key: str, base_url: str | None = None) -> OpenAI:
    """Build the API client. Separated so tests can inject a fake."""
    return OpenAI(api_key=api_key, base_url=base_url or None)


def _encode_bytes(data: bytes) -> str:
    """Downscale raw image bytes and return them as a base64 data URL.

    Shared by encode_image (reads a Path first) and encode_image_bytes
    (already has bytes, e.g. from FileStorage) so the actual downscale/
    re-encode logic exists in exactly one place. Re-encoding as JPEG
    regardless of the input format keeps the payload small and the MIME
    type predictable. Transparency is flattened onto white, since a PNG
    with an alpha channel cannot be saved as JPEG.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
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
        raise DetectionError(f"Could not decode image: {exc}") from exc

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def encode_image(image_path: Path) -> str:
    """Read an image from disk, downscale it, and return a base64 data URL.

    Used by the playground CLIs, which have a filesystem Path. The plugin
    has bytes instead — see encode_image_bytes.
    """
    if not image_path.is_file():
        raise DetectionError(f"No such image: {image_path}")
    if image_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise DetectionError(
            f"Unsupported image type '{image_path.suffix}'. "
            f"Expected one of: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )

    try:
        data = image_path.read_bytes()
    except OSError as exc:
        raise DetectionError(f"Could not read {image_path}: {exc}") from exc

    return _encode_bytes(data)


def encode_image_bytes(data: bytes) -> str:
    """Downscale image bytes already in memory and return a base64 data URL.

    The plugin's entry point: it gets bytes from FileStorage, never a
    filesystem Path. Same processing as encode_image otherwise.
    """
    return _encode_bytes(data)


def _call_vision(
    data_urls: list[str],
    instruction: str,
    *,
    client: OpenAI,
    model: str,
    temperature: float | None = None,
) -> DetectionResult:
    """Shared model call behind detect_items, detect_items_multi and
    detect_items_bytes — one image or several, one instruction, one
    parsed result. Not part of the public module surface.
    """
    content: list[dict[str, object]] = [{"type": "text", "text": instruction}]
    for data_url in data_urls:
        content.append({"type": "image_url", "image_url": {"url": data_url}})

    # Built as a dict so an unset temperature is *absent* rather than None —
    # reasoning models reject the parameter outright rather than ignoring it.
    optional: dict[str, object] = {}
    if temperature is not None:
        optional["temperature"] = temperature

    try:
        completion = client.chat.completions.parse(
            model=model,
            messages=[{"role": "user", "content": content}],
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
        instruction = prompts.TARGETED.format(
            targets="\n".join(f"- {name}" for name in targets)
        )
    else:
        instruction = prompts.OPEN_SCAN

    return _call_vision(
        [data_url], instruction, client=client, model=model, temperature=temperature
    )


def detect_items_multi(
    image_paths: list[Path],
    *,
    client: OpenAI,
    model: str,
    temperature: float | None = None,
) -> DetectionResult:
    """Detect objects across several images of ONE scene, in a single call.

    Unlike `detect_items`, which looks at one image, this sends every image
    together and asks the model to deduplicate objects that recur across
    views — the open question behind §11a's video decision: can the model
    tell "the same sofa from another angle" from "a second sofa"? Existing
    single-image callers (detect.py, estimate.py, build_catalog.py) are
    unaffected; this is an addition, not a change to `detect_items`.
    """
    data_urls = [encode_image(path) for path in image_paths]

    return _call_vision(
        data_urls,
        prompts.MULTI_VIEW,
        client=client,
        model=model,
        temperature=temperature,
    )


def detect_items_bytes(
    images: list[bytes],
    *,
    client: OpenAI,
    model: str,
    temperature: float | None = None,
) -> DetectionResult:
    """Detect objects from image bytes already in memory (e.g. FileStorage) —
    the plugin's entry point, since it never has a filesystem Path.

    One image uses the open-scan prompt (detect_items' behaviour); several
    use the multi-view prompt (detect_items_multi's behaviour), so a scan
    naturally deduplicates across views whenever more than one photo is
    attached, with no separate call for the caller to choose between.
    """
    if not images:
        raise DetectionError("No images given.")

    data_urls = [encode_image_bytes(data) for data in images]
    instruction = prompts.OPEN_SCAN if len(data_urls) == 1 else prompts.MULTI_VIEW

    return _call_vision(
        data_urls, instruction, client=client, model=model, temperature=temperature
    )
