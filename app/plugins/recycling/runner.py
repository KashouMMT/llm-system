"""Async orchestration around the (synchronous, CPU/IO-blocking) detection
pipeline.

pipeline/consensus.py's detect_stable and pipeline/build.py's harvest are
both sequential for-loops calling the OpenAI SDK directly — fine for a CLI,
fatal for a plugin: run either on the event loop that also serves SSE and
every other conversation stalls behind one scan. This module is the async
glue that fires runs concurrently via asyncio.to_thread and merges them
with pipeline.consensus.merge_runs, which stays untouched.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass

from openai import OpenAI

from app.plugins.recycling.pipeline.catalog import Catalog
from app.plugins.recycling.pipeline.consensus import merge_runs
from app.plugins.recycling.pipeline.labels import normalize
from app.plugins.recycling.pipeline.resolve import Resolution, grouping_key, resolve
from app.plugins.recycling.pipeline.vision import DetectionError, detect_items_bytes
from app.repositories.file_repository import FileRecord
from app.storage.base import FileStorage
from app.utils.video_frames import DEFAULT_FRAME_COUNT, FrameSample, extract_frames

# Matches estimate.py's CLI defaults.
DEFAULT_RUNS = 3
DEFAULT_MIN_RUNS_SEEN = 2


@dataclass(frozen=True)
class VideoScanOutcome:
    confident: Resolution
    low: Resolution
    sample: FrameSample


@dataclass(frozen=True)
class HarvestResult:
    # label -> number of *sources* (one photo, or one whole video) it
    # appeared in. What cluster() shows as "seen Nx" and assemble() stores
    # as a row's observations.
    frequencies: dict[str, int]
    # Photos or frames whose every detection run failed. Reported, never
    # just skipped: a label on a failed frame is missing from the catalog.
    failed_images: int


async def video_frames(
    file: FileRecord,
    *,
    file_storage: FileStorage,
    frame_count: int = DEFAULT_FRAME_COUNT,
) -> FrameSample:
    """
    Usable frames from one stored video — the step scan_video and
    /recycle build_catalog share, so a catalog is built from the same
    quality-gated frames a scan sees.

    Raises FrameExtractionError with a remedy when too few frames survive.
    """
    async with file_storage.temporary_path(file.storage_key) as path:
        return await extract_frames(path, count=frame_count)


async def scan_video(
    file: FileRecord,
    *,
    file_storage: FileStorage,
    client: OpenAI,
    model: str,
    catalog: Catalog,
    frame_count: int = DEFAULT_FRAME_COUNT,
) -> VideoScanOutcome:
    """
    One stored video → usable frames → the same multi-view scan a set of
    photos gets.

    The single entry point for scanning a video, deliberately shaped so the
    /recycle command today and an agent tool later both call it: two copies
    of this sequence would drift, and a scan must give the same answer
    however it was started.

    Raises FrameExtractionError (unusable video, with a remedy) or
    DetectionError (model failure); callers turn either into a message.
    """
    sample = await video_frames(file, file_storage=file_storage, frame_count=frame_count)

    confident, low = await scan(
        [frame.jpeg for frame in sample.frames],
        client=client,
        model=model,
        catalog=catalog,
    )

    return VideoScanOutcome(confident=confident, low=low, sample=sample)


async def scan(
    images: list[bytes],
    *,
    client: OpenAI,
    model: str,
    catalog: Catalog,
    runs: int = DEFAULT_RUNS,
    min_runs_seen: int = DEFAULT_MIN_RUNS_SEEN,
) -> tuple[Resolution, Resolution]:
    """
    Run `runs` independent detection passes over `images` concurrently —
    each pass sees every image in one call (detect_items_bytes picks the
    open-scan or multi-view prompt by image count, so cross-view dedup
    applies automatically whenever more than one photo is attached) —
    merge them through the catalog's grouping key exactly like estimate.py's
    CLI, and resolve against the catalog.

    Returns (confident, low_agreement): the same split estimate.py prints,
    so a command's renderer can produce the same sections it does.
    """

    async def one_run() -> list:
        result = await asyncio.to_thread(
            detect_items_bytes, images, client=client, model=model,
        )
        return result.items

    results = await asyncio.gather(
        *(one_run() for _ in range(runs)), return_exceptions=True
    )

    observations = []
    failures = []
    for result in results:
        if isinstance(result, DetectionError):
            failures.append(result)
            continue
        if isinstance(result, BaseException):
            raise result
        observations.append(result)

    if not observations:
        last = failures[-1] if failures else "unknown error"
        raise DetectionError(f"All {runs} detection runs failed. Last error: {last}")

    stable = merge_runs(observations, key=grouping_key(catalog))

    confident = [item for item in stable if item.runs_seen >= min_runs_seen]
    low = [item for item in stable if item.runs_seen < min_runs_seen]

    return resolve(confident, catalog), resolve(low, catalog)


async def harvest(
    sources: list[list[bytes]],
    *,
    client: OpenAI,
    model: str,
    runs: int,
) -> HarvestResult:
    """
    Concurrent, bytes-based equivalent of pipeline.build.harvest: for each
    image, `runs` independent single-image detection passes are merged with
    consensus, then each resulting label counts once per *source* it
    appeared in — occurrences across captures, not units, like the CLI's
    harvest stage.

    A source is one capture: a photo is a source of one image, a video is
    one source of all its frames. Counting per frame instead would make one
    sofa filmed across 12 frames "seen 12x", which cluster() reads as a
    common item and assemble() stores as 12 observations. Detection still
    runs per frame rather than one multi-view call per video: building a
    catalog wants every distinct label, and a single frame at full size
    shows small items a 12-image call misses.

    One bad image (every one of its runs failing) does not abort the
    harvest — a long, paid run must not be thrown away over one corrupt
    frame — but it is counted in failed_images for the caller to report.
    """

    async def one_image(data: bytes) -> list:
        async def one_run():
            result = await asyncio.to_thread(
                detect_items_bytes, [data], client=client, model=model,
            )
            return result.items

        results = await asyncio.gather(
            *(one_run() for _ in range(runs)), return_exceptions=True
        )
        observations = [r for r in results if not isinstance(r, BaseException)]
        if not observations:
            raise DetectionError("All detection runs failed for one image.")
        return merge_runs(observations)

    # Flattened so every image of every source runs concurrently, then
    # regrouped by source index below.
    owners = [index for index, images in enumerate(sources) for _ in images]
    per_image = await asyncio.gather(
        *(one_image(data) for images in sources for data in images),
        return_exceptions=True,
    )

    labels_by_source: list[set[str]] = [set() for _ in sources]
    failed_images = 0

    for owner, result in zip(owners, per_image):
        if isinstance(result, BaseException):
            failed_images += 1
            continue
        labels_by_source[owner].update(normalize(item.label) for item in result)

    frequencies: Counter[str] = Counter()
    for labels in labels_by_source:
        frequencies.update(labels)

    return HarvestResult(
        frequencies=dict(frequencies.most_common()),
        failed_images=failed_images,
    )
