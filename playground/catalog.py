"""The catalog: canonical items, their aliases, and their physical metadata.

This is a lookup table. It never sees an image. Detection produces a free-form
label; the catalog answers "which known item is that, and what do we know about
it." Everything the system knows that cannot be seen in a photograph — weight,
dimensions, material, price — lives here, because those are facts about a *kind
of object*, not about a particular picture of one.

Two design notes worth keeping:

The catalog owns exclusion. An item we deliberately ignore (a door, a wall) is a
normal row with `excluded=True`, not an absence. That way it still carries its
alias list, a reviewer flips one boolean instead of editing a second file, and
"deliberately excluded" never looks the same as "we failed to recognise it".

Metadata fields are all optional and every one records where it came from. A
partially known item is normal and useful; a missing weight must be visible as
missing rather than defaulted to zero, because zero silently produces a wrong
total while `None` forces the caller to decide what to do.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Literal

from pydantic import BaseModel, Field

from labels import collapse_key, normalize

# Where a metadata value came from, so a reviewer knows what to distrust.
# An LLM estimate of a washing machine's weight is a reasonable starting point;
# a client-supplied figure is authoritative. Never let them look alike.
MetadataSource = Literal["llm_estimate", "measured", "client_supplied", "unknown"]

CM3_PER_M3 = 1_000_000.0


class CatalogError(RuntimeError):
    """Raised when a catalog file is unusable — missing, malformed, or ambiguous."""


class Dimensions(BaseModel):
    """Bounding box of one unit, in centimetres. Any axis may be unknown."""

    length_cm: float | None = None
    width_cm: float | None = None
    height_cm: float | None = None

    @property
    def is_complete(self) -> bool:
        return None not in (self.length_cm, self.width_cm, self.height_cm)

    @property
    def volume_m3(self) -> float | None:
        """Bounding-box volume, or None if any axis is unknown.

        This is the *box* the item occupies, not the material volume — an
        office chair's bounding box is mostly air. That is the right number for
        anything to do with space, and the wrong one for anything to do with
        material content.
        """
        if not self.is_complete:
            return None
        return (self.length_cm * self.width_cm * self.height_cm) / CM3_PER_M3

    def __str__(self) -> str:
        if not self.is_complete:
            return "?"
        return f"{self.length_cm:g}x{self.width_cm:g}x{self.height_cm:g}cm"


class ItemMetadata(BaseModel):
    """Everything known about one unit of an item that a photo cannot tell you.

    Every field is optional. The scope is deliberately not limited to price:
    weight and volume are the primary estimate outputs, price is one field
    among several, and `extra` absorbs whatever a client cares about that we
    did not anticipate.
    """

    weight_kg: float | None = None
    weight_kg_min: float | None = None
    weight_kg_max: float | None = None

    dimensions: Dimensions = Field(default_factory=Dimensions)
    # Set explicitly only for items whose occupied volume is not their bounding
    # box — a rolled carpet, a bag of cables. Otherwise derived from dimensions.
    volume_m3: float | None = None

    material: str | None = None
    # Six chairs stack into roughly the volume of two; six microwaves do not.
    # Ignoring this overestimates volume by 3x on the most common items.
    nestable: bool | None = None
    stackable: bool | None = None

    unit_price: float | None = None
    currency: str | None = None

    # Client-specific fields we did not anticipate. Strings only, on purpose:
    # anything that deserves a real type deserves a real field.
    extra: dict[str, str] = Field(default_factory=dict)

    source: MetadataSource = "unknown"

    @property
    def effective_volume_m3(self) -> float | None:
        """Explicit volume if given, otherwise derived from the bounding box."""
        if self.volume_m3 is not None:
            return self.volume_m3
        return self.dimensions.volume_m3

    @property
    def weight_is_estimated(self) -> bool:
        """True when the range is wide enough that the point value is a guess."""
        if self.weight_kg is None:
            return False
        if self.weight_kg_min is None or self.weight_kg_max is None:
            return self.source == "llm_estimate"
        spread = self.weight_kg_max - self.weight_kg_min
        return spread > max(0.5, self.weight_kg * 0.4)

    def missing_fields(self) -> list[str]:
        """Which of the fields we actually rely on are absent."""
        missing = []
        if self.weight_kg is None:
            missing.append("weight_kg")
        if self.effective_volume_m3 is None:
            missing.append("volume_m3")
        return missing


class CatalogItem(BaseModel):
    """One canonical thing, the names it goes by, and what we know about it."""

    id: str
    canonical_label: str
    # Every other spelling detection has produced for this thing. This is what
    # finally merges "table"/"desk" and "headset"/"headphone" — string
    # normalisation cannot, because they are synonyms rather than variants.
    aliases: list[str] = Field(default_factory=list)
    # What an open-vocabulary detector should be told to look for. Several rows
    # may share one: "TV 32in" and "TV 55in" are both visually "television".
    visual_class: str = ""

    excluded: bool = False
    exclusion_reason: str | None = None

    # How many times this was seen while harvesting. A label seen once across
    # twenty photos is probably a hallucination; seen fourteen times, it is real.
    observations: int = 0

    metadata: ItemMetadata = Field(default_factory=ItemMetadata)

    @property
    def detector_class(self) -> str:
        return self.visual_class or self.canonical_label

    def match_keys(self) -> set[str]:
        """Every string that should resolve to this item."""
        names = [self.id, self.canonical_label, *self.aliases]
        return {key for key in (collapse_key(name) for name in names) if key}


class CatalogFile(BaseModel):
    """The on-disk shape. Separate from `Catalog` so the index is not serialised."""

    version: int = 1
    items: list[CatalogItem] = Field(default_factory=list)


class Catalog:
    """An in-memory catalog with a lookup index over every alias.

    Not a Pydantic model: it carries a derived index that has no business being
    written to disk, and building that index is where alias conflicts are caught.
    """

    def __init__(self, items: list[CatalogItem], *, version: int = 1) -> None:
        self.version = version
        self.items = items
        self._index: dict[str, CatalogItem] = {}

        for item in items:
            for key in item.match_keys():
                existing = self._index.get(key)
                if existing is not None and existing.id != item.id:
                    # Silently letting one win would make matching depend on
                    # file order, which is the worst kind of bug to chase.
                    raise CatalogError(
                        f"Alias conflict: '{key}' is claimed by both "
                        f"'{existing.id}' and '{item.id}'. Remove it from one."
                    )
                self._index[key] = item

    # ---- construction -------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> Catalog:
        if not path.is_file():
            raise CatalogError(f"No catalog at {path}. Build one first.")
        try:
            payload = CatalogFile.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise CatalogError(f"Could not read {path}: {exc}") from exc
        return cls(payload.items, version=payload.version)

    def save(self, path: Path) -> None:
        """Write atomically: a crash mid-write leaves a .part file, not a
        truncated catalog that looks complete."""
        payload = CatalogFile(version=self.version, items=self.items)
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_text(
            payload.model_dump_json(indent=2, exclude_none=False), encoding="utf-8"
        )
        temporary.replace(path)

    # ---- queries ------------------------------------------------------

    def match(self, label: str) -> CatalogItem | None:
        """Resolve a detected label to a catalog item, or None.

        Exact alias matching only, on the collapsed key. Returning None is a
        real answer — an honest abstention that the caller surfaces for review
        and that eventually becomes a new catalog row. It is not an error, and
        it must never be quietly discarded.

        A semantic fallback (embedding nearest-neighbour) belongs here later,
        but only once an abstention actually costs something. Until then this
        stays deterministic and free.
        """
        return self._index.get(collapse_key(label))

    def vocabulary(self, *, include_excluded: bool = False) -> list[str]:
        """Distinct detector classes — what an open-vocabulary model is given.

        Excluded items are omitted by default: a detector should not spend
        vocabulary slots on doors we intend to throw away. Pass True when you
        want them detected in order to report them as excluded.
        """
        classes = {
            item.detector_class
            for item in self.items
            if include_excluded or not item.excluded
        }
        return sorted(classes)

    def by_id(self, item_id: str) -> CatalogItem | None:
        return next((item for item in self.items if item.id == item_id), None)

    def incomplete(self) -> list[CatalogItem]:
        """Rows missing metadata we rely on. The reviewer's worklist."""
        return [
            item
            for item in self.items
            if not item.excluded and item.metadata.missing_fields()
        ]

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> Iterator[CatalogItem]:
        return iter(self.items)


def make_id(label: str) -> str:
    """A stable, readable id from a label: 'Washing Machine' -> 'washing_machine'.

    Readable rather than a UUID because a human edits this file by hand, and
    'washing_machine' in a diff is worth more than '7f3a...'.
    """
    return "_".join(normalize(label).split()) or "unnamed"


def write_json(path: Path, payload: object) -> None:
    """Shared atomic JSON write, used by the build script's intermediate files."""
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    temporary.replace(path)
