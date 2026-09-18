"""
Stills out of a video: ffmpeg decodes, Pillow judges and chooses.

Core rather than plugin code because video is a baseline attachment type:
the chat path shows sampled frames to a vision model, and the recycling
plugin's scan reuses the same function. A plugin may import core; core may
never import a plugin.

ffmpeg is a system binary, not a Python package — no wheel to match the
interpreter, and it handles rotation metadata and variable frame rate
correctly. Every quality measure here is Pillow, so this adds no Python
dependency.

Unusable frames are dropped before they cost a token, and every drop is
counted and reported. A scan that silently came back short would be
indistinguishable from a room with few items in it.
"""

import asyncio
import io
import json
import shutil
import statistics
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageStat

from app.utils.logger import logger

DEFAULT_FRAME_COUNT = 12

# Accepted range for a caller-supplied frame count (/recycle scan N, /recycle build_catalog N).
MIN_FRAME_COUNT = 4
MAX_FRAME_COUNT = 40

# Long edge of every extracted frame. Scaled inside ffmpeg, before anything
# else touches the pixels, so a 4K frame never costs 4K memory here.
DEFAULT_MAX_EDGE = 1024

# Below this many usable frames the video is refused rather than scanned:
# a result built on two frames looks like a result and is not one.
MIN_USABLE_FRAMES = 4

# Candidates are keyframes only, and phones write about one per second. A
# video may be up to the whole daily upload allowance (1 GB ≈ 10-20 minutes
# of 1080p), and ffmpeg stops at this many frames — anything recorded after
# is never seen. So this must cover the longest allowed video, not a typical
# one: 200 silently dropped everything past ~3 minutes. 1200 ≈ 20 minutes,
# ~100 MB of temporary JPEGs at worst, deleted when extraction ends.
_CANDIDATE_LIMIT = 1200

# Decoding 1200 keyframes on a shared vCPU is minutes, not seconds.
_FFMPEG_TIMEOUT_SECONDS = 600
_FFPROBE_TIMEOUT_SECONDS = 30

# One extraction at a time. ffmpeg saturates whatever cores it is given,
# and this process also serves SSE for every other conversation.
_EXTRACTION_LOCK = asyncio.Semaphore(1)

# 3x3 Laplacian: the variance of the convolved image is the standard blur
# metric. offset=128 only keeps negative responses representable in 8 bits;
# it moves the mean, not the variance.
_LAPLACIAN = ImageFilter.Kernel(
    (3, 3),
    (0, 1, 0, 1, -4, 1, 0, 1, 0),
    scale=1,
    offset=128,
)

# Quality thresholds. Deliberately extreme to start — each one only drops a
# frame that is useless beyond argument — and meant to be tightened against
# real footage, not tuned by guesswork. Luma is 0-255.
_BLACK_MEAN_LUMA = 16
_WHITE_MEAN_LUMA = 240
_FLAT_LUMA_STDDEV = 6
# Relative, never absolute: raw Laplacian variance swings with scene
# content, lighting and resolution, so "blurry" only means something
# compared with the other frames of the same video.
_BLUR_FRACTION_OF_MEDIAN = 0.25
# Mean absolute difference, 0-255, between tiny greyscale thumbnails of this
# frame and the last kept one. Measured 2026-09-17: consecutive keyframes of
# real handheld room sweeps differ by 25-85; a camera parked on a tripod by
# 0.0-0.1. 1.0 only catches the parked camera. (A synthetic test pattern sits
# at 2-3 — unrealistically still, so never calibrate this against one.)
_DUPLICATE_MEAN_DIFF = 1.0
# Warn-only: a bright window or a white sofa blows out exactly the same
# pixels as glare does, so dropping on this would remove real items.
_GLARE_BLOWN_FRACTION = 0.25

_SHORT_VIDEO_SECONDS = 10
_LOW_RESOLUTION_SHORT_EDGE = 720

# Reason keys, in the order they are reported.
_REASONS = ("blurry", "dark", "overexposed", "blank", "duplicate")

# What to tell someone whose video is refused, by the reason that removed
# the most frames. Instructions, not diagnoses: the person can act on them.
_REMEDIES = {
    "blurry": "Most of the video is too blurry. Move the camera slowly and steadily, and record again.",
    "dark": "Most of the video is too dark to see. Turn the lights on and record again.",
    "overexposed": "Most of the video is washed out. Avoid pointing the camera at windows or lights, and record again.",
    "blank": "Most of the video shows a single flat colour. Check the lens is not covered and the camera is not too close to a surface, then record again.",
    "duplicate": "The camera barely moved. Walk slowly around the room so every wall is filmed, and record again.",
}


class FrameExtractionError(RuntimeError):
    """The video could not be turned into usable frames. Message is user-facing."""


@dataclass(frozen=True)
class Frame:
    index: int
    jpeg: bytes
    # Comparable only between frames of the same video.
    sharpness: float


@dataclass(frozen=True)
class FrameSample:
    """The frames chosen from one video, and an account of everything else."""

    frames: list[Frame]
    candidates: int
    # Reason -> frames dropped for it. Only reasons that dropped something.
    skipped: dict[str, int] = field(default_factory=dict)
    # Sentences a person should read: problems that did not stop the scan.
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """One line, e.g. "12 of 60 frames used · skipped: blurry 5, dark 2"."""
        line = f"{len(self.frames)} of {self.candidates} frames used"

        if self.skipped:
            parts = ", ".join(f"{reason} {count}" for reason, count in self.skipped.items())
            line += f" · skipped: {parts}"

        return line


@dataclass
class _Candidate:
    index: int
    jpeg: bytes
    sharpness: float
    mean: float
    stddev: float
    blown_fraction: float
    portrait: bool
    thumbnail: Image.Image


def _require(binary: str) -> str:
    path = shutil.which(binary)

    if path is None:
        # A realistic state on a dev machine, and a process started before
        # ffmpeg was installed inherits a PATH without it.
        raise FrameExtractionError(
            f"{binary} is not installed or not on PATH, so video cannot be read."
        )

    return path


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[bytes]:
    """
    A blocking subprocess.run, meant to be called through asyncio.to_thread.

    Not asyncio.create_subprocess_exec: on Windows, app/main.py runs a
    SelectorEventLoop (psycopg's async driver needs one), and only the
    Proactor loop can spawn subprocesses there — the asyncio version raised
    NotImplementedError on the first real upload. A thread works on every
    loop and OS, and _EXTRACTION_LOCK already limits it to one at a time.
    """
    return subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


async def _run_ffmpeg(source: Path, output_dir: Path, max_edge: int) -> None:
    command = [
        _require("ffmpeg"),
        "-nostdin",
        "-hide_banner",
        "-loglevel", "error",
        # Input option, so it reaches the decoder: non-keyframes are never
        # decoded at all, which is 10-50x cheaper than decoding forward.
        "-skip_frame", "nokey",
        "-i", str(source),
        # Rotation needs nothing: ffmpeg applies the display matrix by
        # default, so a portrait recording arrives as portrait frames.
        "-vf",
        f"scale=w={max_edge}:h={max_edge}:force_original_aspect_ratio=decrease",
        # Phone video is variable frame rate; the default constant-rate
        # output would duplicate frames that were never recorded.
        "-fps_mode", "passthrough",
        "-frames:v", str(_CANDIDATE_LIMIT),
        "-q:v", "3",
        str(output_dir / "f_%04d.jpg"),
    ]

    try:
        completed = await asyncio.to_thread(_run, command, _FFMPEG_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        # subprocess.run has already killed the child by the time this raises.
        raise FrameExtractionError(
            f"Reading the video timed out after {_FFMPEG_TIMEOUT_SECONDS}s."
        ) from None

    if completed.returncode != 0:
        # The tail only: the last line names the failure, the rest is
        # stream metadata nobody reading an error message needs.
        message = completed.stderr.decode("utf-8", "replace").strip()[-400:]
        raise FrameExtractionError(f"ffmpeg could not read this video: {message}")


async def _probe(source: Path) -> tuple[float | None, int | None, int | None]:
    """
    (duration seconds, width, height) of the stored video, or Nones.

    Best-effort by design: it only feeds warnings. A probe failure must not
    block a scan that ffmpeg itself decoded fine.
    """
    try:
        command = [
            _require("ffprobe"),
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format=duration:stream=width,height",
            "-of", "json",
            str(source),
        ]
        completed = await asyncio.to_thread(_run, command, _FFPROBE_TIMEOUT_SECONDS)
        data = json.loads(completed.stdout or b"{}")
        stream = (data.get("streams") or [{}])[0]
        duration = data.get("format", {}).get("duration")

        return (
            float(duration) if duration is not None else None,
            stream.get("width"),
            stream.get("height"),
        )
    except (FrameExtractionError, subprocess.TimeoutExpired, ValueError, OSError):
        logger.warning("ffprobe failed; video-level warnings skipped | path=%s", source.name)
        return None, None, None


def _measure(paths: list[Path]) -> list[_Candidate]:
    candidates: list[_Candidate] = []

    for index, path in enumerate(paths):
        data = path.read_bytes()

        try:
            with Image.open(io.BytesIO(data)) as image:
                portrait = image.height > image.width
                grey = image.convert("L")
        except OSError:
            # The pool is redundant by construction; one bad frame is not
            # worth failing the whole video over.
            logger.warning("Unreadable video frame skipped | frame=%s", path.name)
            continue

        stats = ImageStat.Stat(grey)
        histogram = grey.histogram()
        blown = sum(histogram[250:]) / max(1, grey.width * grey.height)

        # Measured small: every metric here only has to compare frames of
        # one video, and full resolution is ~20x slower for the same order.
        small = grey.copy()
        small.thumbnail((320, 320), Image.BILINEAR)

        candidates.append(
            _Candidate(
                index=index,
                jpeg=data,
                sharpness=ImageStat.Stat(small.filter(_LAPLACIAN)).var[0],
                mean=stats.mean[0],
                stddev=stats.stddev[0],
                blown_fraction=blown,
                portrait=portrait,
                thumbnail=grey.resize((32, 18), Image.BILINEAR),
            )
        )

    return candidates


def _triage(candidates: list[_Candidate]) -> tuple[list[_Candidate], Counter[str]]:
    """Usable candidates in time order, and why each of the rest was dropped."""
    skipped: Counter[str] = Counter()
    exposed: list[_Candidate] = []

    for candidate in candidates:
        if candidate.mean < _BLACK_MEAN_LUMA:
            skipped["dark"] += 1
        elif candidate.mean > _WHITE_MEAN_LUMA:
            skipped["overexposed"] += 1
        elif candidate.stddev < _FLAT_LUMA_STDDEV:
            skipped["blank"] += 1
        else:
            exposed.append(candidate)

    # The blur baseline comes from the frames that survived exposure checks:
    # a black frame has near-zero edge variance and would drag the median
    # down until nothing counted as blurry.
    if len(exposed) >= 3:
        floor = statistics.median(c.sharpness for c in exposed) * _BLUR_FRACTION_OF_MEDIAN
    else:
        floor = 0.0

    usable: list[_Candidate] = []

    for candidate in exposed:
        if candidate.sharpness < floor:
            skipped["blurry"] += 1
            continue

        if usable:
            difference = ImageStat.Stat(
                ImageChops.difference(candidate.thumbnail, usable[-1].thumbnail)
            ).mean[0]

            if difference < _DUPLICATE_MEAN_DIFF:
                # Keep whichever of the two is sharper, in the earlier slot.
                skipped["duplicate"] += 1
                if candidate.sharpness > usable[-1].sharpness:
                    usable[-1] = candidate
                continue

        usable.append(candidate)

    return usable, skipped


def select_frames(candidates: list[Frame], count: int) -> list[Frame]:
    """
    The sharpest frame from each of `count` equal slices of the timeline.

    Even spacing alone lands on mid-pan frames — blurred, and starved of
    bits by the encoder. Sharpest overall takes every frame from the one
    moment the camera stood still and misses the rest of the room. One
    sharpest-per-slice gets coverage and sharpness together.

    Slices are by candidate index, which approximates time because
    keyframes are roughly evenly spaced.
    """
    if count >= len(candidates):
        return candidates

    kept: list[Frame] = []

    for bucket in range(count):
        start = bucket * len(candidates) // count
        end = (bucket + 1) * len(candidates) // count
        window = candidates[start:end]

        if window:
            kept.append(max(window, key=lambda frame: frame.sharpness))

    return kept


def _warnings(
    usable: list[_Candidate],
    duration: float | None,
    width: int | None,
    height: int | None,
) -> list[str]:
    warnings: list[str] = []

    # From the decoded frames, not the probe: ffmpeg has already applied the
    # rotation matrix, so this is the orientation a person actually saw.
    if usable and sum(c.portrait for c in usable) > len(usable) / 2:
        warnings.append(
            "Recorded in portrait. Landscape is required: it covers more of "
            "the room per frame."
        )

    glare = sum(c.blown_fraction > _GLARE_BLOWN_FRACTION for c in usable)
    if glare:
        warnings.append(
            f"{glare} frame(s) have large overexposed areas (glare, a window, "
            "or a light). Items in those areas may be missed."
        )

    if duration is not None and duration < _SHORT_VIDEO_SECONDS:
        warnings.append(
            f"The video is only {duration:.1f}s long, likely too short to "
            "cover the whole room."
        )

    if width and height and min(width, height) < _LOW_RESOLUTION_SHORT_EDGE:
        warnings.append(
            f"Low resolution ({width}x{height}). Small items may be missed."
        )

    return warnings


async def extract_frames(
    video: Path,
    *,
    count: int = DEFAULT_FRAME_COUNT,
    max_edge: int = DEFAULT_MAX_EDGE,
) -> FrameSample:
    """
    Up to `count` usable JPEG frames from `video`, in time order, with an
    account of what was dropped and why.

    Raises FrameExtractionError when the video cannot be decoded, or when
    fewer than MIN_USABLE_FRAMES survive — with a remedy for the reason that
    removed the most frames.
    """
    async with _EXTRACTION_LOCK:
        with tempfile.TemporaryDirectory(prefix="video_frames_") as directory:
            output = Path(directory)

            await _run_ffmpeg(video, output, max_edge)

            paths = sorted(output.glob("f_*.jpg"))

            if not paths:
                raise FrameExtractionError(
                    "No frames could be read from this video. It may be "
                    "corrupt, or too short to contain a keyframe."
                )

            candidates = await asyncio.to_thread(_measure, paths)

        duration, width, height = await _probe(video)

    usable, skipped = _triage(candidates)

    if len(usable) < MIN_USABLE_FRAMES:
        dominant = skipped.most_common(1)
        remedy = (
            _REMEDIES[dominant[0][0]]
            if dominant
            else "The video is too short to scan. Record a slow sweep of the whole room."
        )
        raise FrameExtractionError(
            f"Only {len(usable)} of {len(candidates)} frames were usable. {remedy}"
        )

    frames = select_frames(
        [Frame(index=c.index, jpeg=c.jpeg, sharpness=c.sharpness) for c in usable],
        count,
    )

    sample = FrameSample(
        frames=frames,
        candidates=len(candidates),
        skipped={reason: skipped[reason] for reason in _REASONS if skipped[reason]},
        warnings=_warnings(usable, duration, width, height),
    )

    logger.info(
        "Video frames extracted | %s | warnings=%s",
        sample.summary(),
        len(sample.warnings),
    )

    return sample
