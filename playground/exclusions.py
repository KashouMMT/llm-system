"""The exclusion list: which detected labels are dropped before reporting.

Deliberately separate from `vision.py` and `consensus.py`. Those two report
what is in the image; this decides what we care about. Mixing them would mean
the only way to change policy is to edit a prompt, and a prompt is a bad place
to keep a list a non-programmer is meant to maintain.

The weak point, kept visible on purpose: matching is on the collapsed label
key. If the model says "doorway" and the list says "door", the item is NOT
excluded. That is why `partition` returns what it removed instead of silently
dropping rows — a filter you cannot see is a filter you cannot debug, and
"correctly excluded" must never look the same as "failed to match".
"""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from labels import collapse_key

# Any object with a `.label` works, so this serves DetectedItem and StableItem
# alike without either of them knowing about exclusions.
Labelled = TypeVar("Labelled")


def load_exclusions(path: Path) -> set[str]:
    """Read one label per line. Blank lines and `#` comments are ignored.

    A missing file means "exclude nothing" rather than an error: the list is
    optional policy, and failing a scan because a text file is absent would be
    the wrong trade.
    """
    if not path.is_file():
        return set()

    excluded: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0]
        key = collapse_key(entry)
        if key:
            excluded.add(key)
    return excluded


def partition(
    items: list[Labelled], excluded_keys: set[str]
) -> tuple[list[Labelled], list[Labelled]]:
    """Split items into (kept, excluded), preserving order in both."""
    kept: list[Labelled] = []
    dropped: list[Labelled] = []
    for item in items:
        target = dropped if collapse_key(item.label) in excluded_keys else kept
        target.append(item)
    return kept, dropped
