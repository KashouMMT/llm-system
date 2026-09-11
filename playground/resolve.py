"""Map detected items onto catalog rows and attach what is known about them.

Two jobs:

`grouping_key(catalog)` builds the key `consensus.merge_runs` groups by, so that
synonyms ("table", "desk") are merged *per run*, before runs are combined. That
is the only place the merge can be done correctly — see `consensus.KeyFunction`.

`resolve(items, catalog)` then attaches each merged item's catalog row and
splits the result three ways. "We do not want it", "we do not recognise it" and
"here it is" are three situations demanding three responses, and flattening
them into one filtered list destroys exactly what a reviewer needs.
"""

from __future__ import annotations

from catalog import Catalog, CatalogItem, ItemMetadata
from consensus import KeyFunction, StableItem, is_unstable
from labels import collapse_key
from pydantic import BaseModel, Field

# Volume each additional unit adds when an item nests. Six stacked chairs
# occupy far less than six chair-shaped boxes; 0.4 is a rough approximation,
# and far closer to the truth than ignoring nesting, which overestimates by
# roughly 3x on the commonest items in a room.
NESTED_UNIT_VOLUME_FACTOR = 0.4


def grouping_key(catalog: Catalog) -> KeyFunction:
    """A consensus key that merges every label a catalog row answers to.

    Matched labels group under their catalog id; unmatched ones under their
    collapsed spelling. The prefixes keep the two namespaces apart, so an
    unmatched label can never collide with a catalog id that happens to be
    spelled the same.
    """

    def key(label: str) -> str:
        collapsed = collapse_key(label)
        if not collapsed:
            return ""
        item = catalog.match(label)
        return f"catalog:{item.id}" if item is not None else f"label:{collapsed}"

    return key


class ResolvedItem(BaseModel):
    """One catalog item, with the observation that produced it."""

    catalog_item: CatalogItem
    count: int
    count_min: int
    count_max: int
    runs_seen: int
    total_runs: int
    # Every spelling detection used for this item, kept so a reviewer can see
    # why two apparently different things became one row.
    observed_labels: list[str] = Field(default_factory=list)

    @property
    def label(self) -> str:
        return self.catalog_item.canonical_label

    @property
    def metadata(self) -> ItemMetadata:
        return self.catalog_item.metadata

    @property
    def total_weight_kg(self) -> float | None:
        weight = self.metadata.weight_kg
        return None if weight is None else weight * self.count

    @property
    def total_volume_m3(self) -> float | None:
        """Total occupied volume, discounted when the item nests."""
        unit = self.metadata.effective_volume_m3
        if unit is None:
            return None
        if self.metadata.nestable and self.count > 1:
            return unit * (1 + (self.count - 1) * NESTED_UNIT_VOLUME_FACTOR)
        return unit * self.count

    @property
    def count_is_unstable(self) -> bool:
        return is_unstable(self.count, self.count_min, self.count_max)


class UnmatchedItem(BaseModel):
    """Something detected that the catalog has never heard of.

    Not an error. This is how the catalog grows: a reviewer names it, and it
    becomes a new row. It must always be surfaced — an unmatched item silently
    dropped is an item that never gets collected.
    """

    label: str
    count: int
    runs_seen: int
    total_runs: int


class Resolution(BaseModel):
    """The full result of resolving one image's detections against a catalog."""

    matched: list[ResolvedItem] = Field(default_factory=list)
    excluded: list[ResolvedItem] = Field(default_factory=list)
    unmatched: list[UnmatchedItem] = Field(default_factory=list)

    @property
    def total_weight_kg(self) -> float | None:
        """Sum over matched items, or None if nothing has a known weight."""
        weights = [
            item.total_weight_kg
            for item in self.matched
            if item.total_weight_kg is not None
        ]
        return sum(weights) if weights else None

    @property
    def total_volume_m3(self) -> float | None:
        volumes = [
            item.total_volume_m3
            for item in self.matched
            if item.total_volume_m3 is not None
        ]
        return sum(volumes) if volumes else None

    @property
    def total_price(self) -> float | None:
        prices = [
            item.metadata.unit_price * item.count
            for item in self.matched
            if item.metadata.unit_price is not None
        ]
        return sum(prices) if prices else None

    @property
    def items_missing_metadata(self) -> list[ResolvedItem]:
        """Matched rows whose totals could not be computed.

        A total built from partial data is a lie unless you say what it left
        out, so the caller must report this alongside any sum.
        """
        return [
            item for item in self.matched if item.catalog_item.metadata.missing_fields()
        ]


def _review_order(item: ResolvedItem | UnmatchedItem) -> tuple[int, int, str]:
    """Most agreed-on first, then most numerous, then alphabetical."""
    return (-item.runs_seen, -item.count, item.label)


def resolve(items: list[StableItem], catalog: Catalog) -> Resolution:
    """Attach catalog rows to detections and split into three buckets.

    Expects `items` grouped with `grouping_key(catalog)`, which already merged
    synonyms per run. Given items grouped only by spelling instead, two labels
    can still land on one catalog row here — and at this point it is no longer
    knowable whether they were one object named twice or two objects. The
    merge below takes the larger count rather than the sum: undercounting a
    duplicate that should have been caught earlier is the safer error than
    doubling an object.
    """
    by_catalog_id: dict[str, ResolvedItem] = {}
    unmatched: list[UnmatchedItem] = []

    for item in items:
        catalog_item = catalog.match(item.label)

        if catalog_item is None:
            unmatched.append(
                UnmatchedItem(
                    label=item.label,
                    count=item.count,
                    runs_seen=item.runs_seen,
                    total_runs=item.total_runs,
                )
            )
            continue

        observed = item.labels or [item.label]
        existing = by_catalog_id.get(catalog_item.id)
        if existing is None:
            by_catalog_id[catalog_item.id] = ResolvedItem(
                catalog_item=catalog_item,
                count=item.count,
                count_min=item.count_min,
                count_max=item.count_max,
                runs_seen=item.runs_seen,
                total_runs=item.total_runs,
                observed_labels=list(observed),
            )
            continue

        existing.count = max(existing.count, item.count)
        existing.count_min = max(existing.count_min, item.count_min)
        existing.count_max = max(existing.count_max, item.count_max)
        existing.runs_seen = max(existing.runs_seen, item.runs_seen)
        existing.observed_labels.extend(
            label for label in observed if label not in existing.observed_labels
        )

    resolved = list(by_catalog_id.values())
    matched = sorted(
        (item for item in resolved if not item.catalog_item.excluded), key=_review_order
    )
    excluded = sorted(
        (item for item in resolved if item.catalog_item.excluded), key=_review_order
    )
    unmatched.sort(key=_review_order)

    return Resolution(matched=matched, excluded=excluded, unmatched=unmatched)
