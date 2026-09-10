"""Turn several unstable single-pass detections into one stable result.

Three runs of the same photo produced 24, 22 and 22 kinds; grape counts of 25,
32 and 20; and "table" once but "desk" twice. A single call is a sample, not a
measurement, so this module takes several and reports what they agree on.

Two things fall out of that, and the second is the more valuable:

1. Marginal items ("coin", "strap", "paper" — each seen once in three runs) are
   dropped, and counts become a median rather than whichever number the model
   happened to produce.
2. **Agreement across runs is a real confidence signal.** The model's own
   `confidence` field is self-reported and uncalibrated — it said 0.99 for
   things it then failed to mention at all on the next run. How often an item
   survives independent runs is measured rather than claimed, and it is the
   number to route the review queue by.

Cost scales linearly with `runs`. Three is a good default; more buys little.
"""

from __future__ import annotations

import statistics
from collections import Counter
from pathlib import Path

from labels import collapse_key, normalize
from openai import OpenAI
from pydantic import BaseModel
from vision import DetectionError, detect_items


class StableItem(BaseModel):
    """One item, as agreed across several independent runs."""

    label: str
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
        """True when the runs disagreed enough that the count needs a human.

        A spread wider than half the median means the model is estimating rather
        than counting — which is what it does past roughly eight identical
        objects.
        """
        spread = self.count_max - self.count_min
        return spread > max(1, self.count // 2)


def detect_stable(
    image_path: Path,
    *,
    client: OpenAI,
    model: str,
    runs: int = 3,
    targets: list[str] | None = None,
    temperature: float | None = None,
) -> list[StableItem]:
    """Run detection `runs` times and merge the results.

    Returns **every** item any run reported, each carrying `runs_seen` so the
    caller can decide where to draw the line. Thresholding deliberately does not
    happen here: a one-off sighting is still an observation, and a module that
    silently discarded it would hide the same failure this module exists to
    expose. `detect.py` applies the threshold, and shows what fell below it.

    Raises `DetectionError` only if *every* run fails — a single transient
    failure is absorbed, since the whole point here is redundancy.
    """
    if runs < 1:
        raise ValueError("runs must be at least 1")

    observations: list[list] = []
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

    # Group every observation by its matching key, so "mouse pad" and "mousepad"
    # land together. Within a run the same key can appear twice (the model
    # occasionally splits what it should have grouped), so counts are summed
    # per run before being compared across runs.
    per_run_counts: dict[str, list[int]] = {}
    surface_forms: dict[str, Counter] = {}
    confidences: dict[str, list[float]] = {}

    for items in observations:
        run_totals: dict[str, int] = {}
        for item in items:
            if item.count <= 0:
                continue
            key = collapse_key(item.label)
            if not key:
                continue
            run_totals[key] = run_totals.get(key, 0) + item.count
            surface_forms.setdefault(key, Counter())[normalize(item.label)] += 1
            confidences.setdefault(key, []).append(item.confidence)
        for key, total in run_totals.items():
            per_run_counts.setdefault(key, []).append(total)

    stable: list[StableItem] = []
    for key, counts in per_run_counts.items():
        stable.append(
            StableItem(
                # The spelling the runs used most often, not the first one seen.
                label=surface_forms[key].most_common(1)[0][0],
                count=int(statistics.median(counts)),
                count_min=min(counts),
                count_max=max(counts),
                runs_seen=len(counts),
                total_runs=len(observations),
                mean_confidence=sum(confidences[key]) / len(confidences[key]),
            )
        )

    # Most agreed-on first, then most numerous — the order a reviewer wants.
    stable.sort(key=lambda item: (-item.runs_seen, -item.count, item.label))
    return stable
