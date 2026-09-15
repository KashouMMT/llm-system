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

from openai import OpenAI

from app.plugins.recycling.pipeline.catalog import Catalog
from app.plugins.recycling.pipeline.consensus import merge_runs
from app.plugins.recycling.pipeline.labels import normalize
from app.plugins.recycling.pipeline.resolve import Resolution, grouping_key, resolve
from app.plugins.recycling.pipeline.vision import DetectionError, detect_items_bytes

# Matches estimate.py's CLI defaults.
DEFAULT_RUNS = 3
DEFAULT_MIN_RUNS_SEEN = 2


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
    images: list[bytes],
    *,
    client: OpenAI,
    model: str,
    runs: int,
) -> dict[str, int]:
    """
    Concurrent, bytes-based equivalent of pipeline.build.harvest: for each
    image, `runs` independent single-image detection passes are merged with
    consensus, then each resulting label counts once per *photo* it
    appeared in — the harvest counts occurrences across photos, not units,
    exactly like the CLI's harvest stage.

    One bad photo (every one of its runs failing) is dropped from the
    count, not fatal to the whole harvest — the CLI's harvest() has the
    same tolerance, for the same reason: a long, paid run must not be
    thrown away over one corrupt image.
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

    per_image = await asyncio.gather(
        *(one_image(data) for data in images), return_exceptions=True
    )

    frequencies: Counter[str] = Counter()
    for result in per_image:
        if isinstance(result, BaseException):
            continue
        for item in result:
            frequencies[normalize(item.label)] += 1

    return dict(frequencies.most_common())
