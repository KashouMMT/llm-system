"""Catalog health checks — fixed rules in code, no model involved.

Tier 1 of the catalog-scale plan (documentation/claude/
Recycling_Agent_Tools_Plan.md): a live test showed the model inventing
thresholds and writing broken SQL when asked "what looks wrong?". These
rules are the same every run, cost nothing, and scale to any catalog size;
the model's job is only what rules cannot do — judging whether a value is
plausible for what the label names.

Pure: rows in, findings out. No I/O, no Catalog index — an alias claimed
by two rows makes Catalog() raise, and a health check must *report* that,
not fail on it.

Every threshold is a named constant with its reasoning. A finding is a
prompt for a human, never an automatic change: nothing here edits a row.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from statistics import median

from app.plugins.recycling.pipeline.catalog import CatalogItem
from app.plugins.recycling.pipeline.labels import collapse_key, normalize

# Bounding-box density, kg/m³. The box is mostly air for most furniture (a
# 7 kg chair in a 0.36 m³ box is ~19 kg/m³), so the floor is low; only a
# near-weightless value for its size is flagged. The ceiling is above
# stone and concrete (~2,400): a household item denser than that, measured
# by its whole box, means a weight or a dimension is wrong.
MIN_DENSITY_KG_M3 = 2.0
MAX_DENSITY_KG_M3 = 3000.0

# Weight against the median of its visual_class. Rows sharing a class are
# visually alike ("TV 32in" and "TV 55in" are both "television"), so a
# factor of 4 either way leaves room for real size spread and still catches
# a unit mistake (grams typed as kilograms is 1000x).
CLASS_RATIO_LIMIT = 4.0
# A median of two or three rows is one outlier away from meaningless.
MIN_CLASS_SIZE_FOR_RATIO = 4

# An explicit volume_m3 is for items that occupy LESS than their box (a
# rolled carpet). More than the box is impossible; 5% absorbs rounding.
VOLUME_OVER_BOX_TOLERANCE = 1.05

# No household item a crew carries is 10 m along one side.
MAX_DIMENSION_CM = 1000.0

# difflib ratio for "probably the same thing, spelled differently"
# ("office chair" / "office chairs" ≈ 0.96, "desk" / "disk" = 0.75).
NEAR_DUPLICATE_RATIO = 0.88
# Near-duplicates are compared pairwise within one visual_class. A class
# this large is itself a finding for a human (it is not one visual kind of
# thing any more), and comparing it pairwise would grow quadratically.
MAX_CLASS_SIZE_FOR_PAIRS = 300

# The catalog is English-only (scan matching, the enrich prompt and the
# agent all assume it). Anything outside printable ASCII is flagged.
_NON_ASCII = re.compile(r"[^\x20-\x7e]")

# Display order and headings. Most actionable first: a conflict breaks
# matching outright; missing metadata only weakens an estimate.
KIND_TITLES: dict[str, str] = {
    "duplicate_name": "Name used by more than one row",
    "near_duplicate": "Near-duplicate labels",
    "weight_range": "Weight range inconsistent",
    "density": "Implausible weight for its size",
    "class_outlier": "Weight far from its class",
    "volume_over_box": "Volume larger than its box",
    "dimension_extreme": "Extreme dimension",
    "missing_metadata": "Collectable row missing weight or size",
    "excluded_without_reason": "Excluded without a reason",
    "non_english": "Text that is not English",
}


@dataclass(frozen=True)
class Finding:
    item_id: str
    kind: str
    detail: str


@dataclass
class HealthReport:
    checked: int
    findings: list[Finding] = field(default_factory=list)
    # What was not checked, and why — so a clean report never overstates
    # what it covered.
    notes: list[str] = field(default_factory=list)

    def by_kind(self) -> dict[str, list[Finding]]:
        """Findings grouped by kind, in KIND_TITLES order, empty kinds omitted."""
        grouped: dict[str, list[Finding]] = defaultdict(list)
        for finding in self.findings:
            grouped[finding.kind].append(finding)
        return {kind: grouped[kind] for kind in KIND_TITLES if grouped.get(kind)}

    @property
    def flagged_rows(self) -> int:
        return len({finding.item_id for finding in self.findings})


def _fmt(value: float) -> str:
    return f"{value:g}"


def _fmt_scaled(value: float) -> str:
    """A ratio or density for a sentence: whole numbers with separators
    when large, two significant digits when small — never 3.6e+02."""
    return f"{value:,.0f}" if value >= 10 else f"{value:.2g}"


def _class_of(item: CatalogItem) -> str:
    return normalize(item.visual_class or item.canonical_label)


def _duplicate_names(items: list[CatalogItem], report: HealthReport) -> None:
    """A name (id, label or alias, as matching collapses it) claimed by two
    rows. Catalog() refuses to load this; scans cannot match reliably."""
    owners: dict[str, dict[str, str]] = defaultdict(dict)

    for item in items:
        # Label first, id last: the name shown is the first this row
        # claims a key by, and a reviewer recognises a label over an id.
        for name in (item.canonical_label, *item.aliases, item.id):
            key = collapse_key(name)
            if key:
                owners[key].setdefault(item.id, name)

    for claimants in owners.values():
        if len(claimants) < 2:
            continue
        for item_id, name in claimants.items():
            others = ", ".join(f"`{other}`" for other in claimants if other != item_id)
            report.findings.append(
                Finding(item_id, "duplicate_name", f"'{name}' also names {others}")
            )


def _near_duplicates(items: list[CatalogItem], report: HealthReport) -> None:
    by_class: dict[str, list[CatalogItem]] = defaultdict(list)
    for item in items:
        by_class[_class_of(item)].append(item)

    for visual_class, members in by_class.items():
        if len(members) > MAX_CLASS_SIZE_FOR_PAIRS:
            report.notes.append(
                f"Near-duplicates not checked in class '{visual_class}' "
                f"({len(members)} rows, over {MAX_CLASS_SIZE_FOR_PAIRS}) — a class "
                "that large is worth splitting."
            )
            continue

        for index, first in enumerate(members):
            first_label = normalize(first.canonical_label)
            for second in members[index + 1 :]:
                second_label = normalize(second.canonical_label)
                # Identical after collapsing is duplicate_name's finding.
                if collapse_key(first_label) == collapse_key(second_label):
                    continue
                ratio = SequenceMatcher(None, first_label, second_label).ratio()
                if ratio >= NEAR_DUPLICATE_RATIO:
                    report.findings.append(
                        Finding(
                            second.id,
                            "near_duplicate",
                            f"'{second.canonical_label}' is close to "
                            f"'{first.canonical_label}' (`{first.id}`) — same item?",
                        )
                    )


def _per_row(item: CatalogItem, report: HealthReport) -> None:
    if not item.excluded:
        _metadata_checks(item, report)

    if item.excluded and not (item.exclusion_reason or "").strip():
        report.findings.append(Finding(item.id, "excluded_without_reason", "no reason given"))

    texts = {
        "label": item.canonical_label,
        "aliases": " ".join(item.aliases),
        "visual_class": item.visual_class,
        "material": item.metadata.material or "",
        "exclusion_reason": item.exclusion_reason or "",
        "extra": " ".join(item.metadata.extra.values()),
    }
    fields = [name for name, text in texts.items() if _NON_ASCII.search(text)]
    if fields:
        report.findings.append(
            Finding(item.id, "non_english", "non-English text in " + ", ".join(fields))
        )


def _metadata_checks(item: CatalogItem, report: HealthReport) -> None:
    """Weight and size rules — collectable rows only: an excluded row is
    never estimated, so its metadata cannot put a wrong number in a quote."""
    metadata = item.metadata
    weight = metadata.weight_kg
    low, high = metadata.weight_kg_min, metadata.weight_kg_max

    if low is not None and high is not None and low > high:
        report.findings.append(
            Finding(item.id, "weight_range", f"min {_fmt(low)} kg is above max {_fmt(high)} kg")
        )
    elif weight is not None and (
        (low is not None and weight < low) or (high is not None and weight > high)
    ):
        report.findings.append(
            Finding(
                item.id,
                "weight_range",
                f"{_fmt(weight)} kg is outside its range "
                f"{_fmt(low) if low is not None else '?'}–{_fmt(high) if high is not None else '?'} kg",
            )
        )

    volume = metadata.effective_volume_m3
    if weight is not None and volume:
        density = weight / volume
        if density > MAX_DENSITY_KG_M3 or density < MIN_DENSITY_KG_M3:
            report.findings.append(
                Finding(
                    item.id,
                    "density",
                    f"{_fmt(weight)} kg in {volume:.3g} m³ = {_fmt_scaled(density)} kg/m³ "
                    f"(plausible {_fmt(MIN_DENSITY_KG_M3)}–{MAX_DENSITY_KG_M3:,.0f})",
                )
            )

    box = metadata.dimensions.volume_m3
    if metadata.volume_m3 is not None and box and metadata.volume_m3 > box * VOLUME_OVER_BOX_TOLERANCE:
        report.findings.append(
            Finding(
                item.id,
                "volume_over_box",
                f"volume_m3 {metadata.volume_m3:.3g} exceeds its box {box:.3g} m³ "
                f"({metadata.dimensions})",
            )
        )

    dimensions = metadata.dimensions
    for axis, value in (
        ("length", dimensions.length_cm),
        ("width", dimensions.width_cm),
        ("height", dimensions.height_cm),
    ):
        if value is not None and (value <= 0 or value > MAX_DIMENSION_CM):
            report.findings.append(
                Finding(item.id, "dimension_extreme", f"{axis} {_fmt(value)} cm")
            )

    if missing := metadata.missing_fields():
        report.findings.append(
            Finding(item.id, "missing_metadata", "missing " + ", ".join(missing))
        )


def _class_outliers(items: list[CatalogItem], report: HealthReport) -> None:
    weights: dict[str, list[tuple[CatalogItem, float]]] = defaultdict(list)
    for item in items:
        if not item.excluded and item.metadata.weight_kg:
            weights[_class_of(item)].append((item, item.metadata.weight_kg))

    comparable = {
        visual_class: members
        for visual_class, members in weights.items()
        if len(members) >= MIN_CLASS_SIZE_FOR_RATIO
    }

    if not comparable:
        # Otherwise a clean report would read as "no outliers" when the
        # rule never ran — e.g. a catalog where every row is its own class.
        report.notes.append(
            f"Weight-vs-class not checked: no visual_class has "
            f"{MIN_CLASS_SIZE_FOR_RATIO}+ collectable rows with a weight to compare."
        )

    for visual_class, members in comparable.items():
        middle = median(weight for _, weight in members)
        for item, weight in members:
            ratio = weight / middle
            if ratio > CLASS_RATIO_LIMIT or ratio < 1 / CLASS_RATIO_LIMIT:
                report.findings.append(
                    Finding(
                        item.id,
                        "class_outlier",
                        f"{_fmt(weight)} kg is {_fmt_scaled(ratio)}× the '{visual_class}' "
                        f"median of {_fmt(middle)} kg ({len(members)} rows)",
                    )
                )


def check_catalog(items: list[CatalogItem]) -> HealthReport:
    """Run every rule over the catalog. Order of findings within a kind
    follows catalog order."""
    report = HealthReport(checked=len(items))

    _duplicate_names(items, report)
    _near_duplicates(items, report)
    for item in items:
        _per_row(item, report)
    _class_outliers(items, report)

    return report
