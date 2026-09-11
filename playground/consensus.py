"""Turn several unstable single-pass detections into one stable result.

Three runs of the same photo produced 24, 22 and 22 kinds; grape counts of 25,
32 and 20; and "table" once but "desk" twice. A single call is a sample, not a
measurement, so this module takes several and reports what they agree on.

Two things fall out of that, and the second is the more valuable:

1. Counts become a median rather than whichever number the model happened to
   produce, with the spread kept so an estimate looks like one.
2. **Agreement across runs is a real confidence signal.** The model's own
   `confidence` field is self-reported and uncalibrated — it said 0.99 for
   things it then failed to mention at all on the next run. How often an item
   survives independent runs is measured rather than claimed.

The work is split in two so the interesting half can be tested without an API
call: `detect_stable` collects runs, `merge_runs` is pure arithmetic over them.

Cost scales linearly with `runs`. Three is a good default; more buys little.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from labels import collapse_key, normalize
from openai import OpenAI
from pydantic import BaseModel, Field
from vision import DetectedItem, DetectionError, detect_items

# Maps a raw label to the key its observations are grouped under.
#
# The default, `collapse_key`, merges spelling variants only. `estimate.py`
# passes a key that maps through the catalog, so that synonyms ("table" and
# "desk") are merged here as well. It has to happen here: this is the last
# place that still knows which run each label came from. Merging synonyms any
# later — after runs are combined — cannot tell "one table, named differently
# in different runs" from "a table and a desk", and double counts the first.
KeyFunction = Callable[[str], str]


def is_unstable(count: int, count_min: int, count_max: int) -> bool:
    """True when runs disagreed enough that the count needs a human.

    A spread wider than half the median means the model was estimating rather
    than counting — which is what it does past roughly eight identical objects.
    The `max(1, ...)` stops a count of 1 being flagged by any variation at all.
    """
    return (count_max - count_min) > max(1, count // 2)


class StableItem(BaseModel):
    """One item, as agreed across several independent runs."""

    label: str
    # Every spelling the runs used for this item, most common first. With a
    # catalog key this can hold synonyms: ["table", "desk"].
    labels: list[str] = Field(default_factory=list)
    count: int
    count_min: int
    count_max: int
    runs_seen: int
    total_runs: int
    mean_confidence: float

    @property
    def agreement(self) -> float:
        """Fraction of runs that reported this item at all. The real confidence."""
        return self.runs_seen / self.total_runs

    @property
    def count_is_unstable(self) -> bool:
        return is_unstable(self.count, self.count_min, self.count_max)


def merge_runs(
    observations: list[list[DetectedItem]],
    *,
    key: KeyFunction = collapse_key,
) -> list[StableItem]:
    """Merge several runs' detections into one list. Pure: no I/O, no API.

    Returns every item any run reported, each carrying `runs_seen`, so the
    caller decides where to draw the line. Nothing is thresholded here: a
    one-off sighting is still an observation, and discarding it silently would
    hide the very failure this module exists to expose.
    """
    if not observations:
        return []

    # Grouping happens at two levels, and getting them backwards multiplies
    # every count by the number of runs.
    #   Within one run, the same key appearing twice is summed: the model listed
    #   two rows for things of the same kind ("table" and "desk" when the
    #   catalog says both are tables — two objects of one type).
    #   Across runs, each run's total is a separate observation, combined by
    #   median: three runs each seeing one laptop is one laptop, not three.
    per_run_counts: dict[str, list[int]] = {}
    surface_forms: dict[str, Counter[str]] = {}
    confidences: dict[str, list[float]] = {}

    for items in observations:
        run_totals: dict[str, int] = {}
        for item in items:
            if item.count <= 0:
                continue
            group = key(item.label)
            if not group:
                continue
            run_totals[group] = run_totals.get(group, 0) + item.count
            surface_forms.setdefault(group, Counter())[normalize(item.label)] += 1
            confidences.setdefault(group, []).append(item.confidence)
        for group, total in run_totals.items():
            per_run_counts.setdefault(group, []).append(total)

    stable: list[StableItem] = []
    for group, counts in per_run_counts.items():
        spellings = [label for label, _ in surface_forms[group].most_common()]
        stable.append(
            StableItem(
                # The spelling the runs used most often, not the first one seen.
                label=spellings[0],
                labels=spellings,
                count=int(statistics.median(counts)),
                count_min=min(counts),
                count_max=max(counts),
                runs_seen=len(counts),
                total_runs=len(observations),
                mean_confidence=sum(confidences[group]) / len(confidences[group]),
            )
        )

    # Most agreed-on first, then most numerous — the order a reviewer wants.
    stable.sort(key=lambda item: (-item.runs_seen, -item.count, item.label))
    return stable


def detect_stable(
    image_path: Path,
    *,
    client: OpenAI,
    model: str,
    runs: int = 3,
    targets: list[str] | None = None,
    temperature: float | None = None,
    key: KeyFunction = collapse_key,
) -> list[StableItem]:
    """Run detection `runs` times and merge the results with `merge_runs`.

    Raises `DetectionError` only if *every* run fails — a single transient
    failure is absorbed, since the whole point here is redundancy.
    """
    if runs < 1:
        raise ValueError("runs must be at least 1")

    observations: list[list[DetectedItem]] = []
    failures: list[DetectionError] = []

    for _ in range(runs):
        try:
            result = detect_items(
                image_path,
                client=client,
                model=model,
                targets=targets,
                temperature=temperature,
            )
        except DetectionError as exc:
            failures.append(exc)
            continue
        observations.append(result.items)

    if not observations:
        raise DetectionError(
            f"All {runs} detection runs failed. Last error: {failures[-1]}"
        )

    return merge_runs(observations, key=key)
