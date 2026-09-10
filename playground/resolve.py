"""Map detected items onto catalog rows and attach what is known about them.

This is the second grouping pass, and it is the one that finally merges
"table" and "desk". `consensus.py` groups by `collapse_key`, which can only
merge spelling variants; synonyms need the catalog's alias list. So detection
groups twice, on two different axes, and this is the second.

The output is deliberately three lists rather than one. "We do not want it",
"we do not recognise it" and "here it is" are three different situations that
demand three different responses, and flattening them into one filtered list
destroys exactly the information a reviewer needs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from catalog import Catalog, CatalogItem, ItemMetadata
from consensus import StableItem


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
        """Total occupied volume, discounted when the item nests.

        Six stacked chairs occupy far less than six chair-shaped boxes. The
        0.4 factor on the additional units is a rough approximation, and it is
        much closer to the truth than ignoring nesting entirely, which
        overestimates by roughly 3x on the commonest items in a room.
        """
        unit = self.metadata.effective_volume_m3
        if unit is None:
            return None
        if self.metadata.nestable and self.count > 1:
            return unit * (1 + (self.count - 1) * 0.4)
        return unit * self.count

    @property
    def count_is_unstable(self) -> bool:
        spread = self.count_max - self.count_min
        return spread > max(1, self.count // 2)


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


def resolve(items: list[StableItem], catalog: Catalog) -> Resolution:
    """Group detections by catalog item, splitting on what happened to each.

    Several `StableItem`s can collapse into one `ResolvedItem` — that is the
    point. Counts are summed across them, and the count range widens to span
    all contributors, because a spread that came from two labels is still a
    spread.
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

        existing = by_catalog_id.get(catalog_item.id)
        if existing is None:
            by_catalog_id[catalog_item.id] = ResolvedItem(
                catalog_item=catalog_item,
                count=item.count,
                count_min=item.count_min,
                count_max=item.count_max,
                runs_seen=item.runs_seen,
                total_runs=item.total_runs,
                observed_labels=[item.label],
            )
            continue

        # A second label for the same catalog item: "desk" arriving after
        # "table". Counts add; the range spans both; agreement takes the
        # stronger of the two, since either label appearing is evidence the
        # object is there.
        existing.count += item.count
        existing.count_min += item.count_min
        existing.count_max += item.count_max
        existing.runs_seen = max(existing.runs_seen, item.runs_seen)
        existing.observed_labels.append(item.label)

    resolved = list(by_catalog_id.values())
    matched = [item for item in resolved if not item.catalog_item.excluded]
    excluded = [item for item in resolved if item.catalog_item.excluded]

    matched.sort(key=lambda item: (-item.runs_seen, -item.count, item.label))
    excluded.sort(key=lambda item: (-item.runs_seen, -item.count, item.label))
    unmatched.sort(key=lambda item: (-item.runs_seen, -item.count, item.label))

    return Resolution(matched=matched, excluded=excluded, unmatched=unmatched)
