"""Build a catalog from photographs, with no reference images and no data entry.

    python build_catalog.py ..\\images\\catalog
    python build_catalog.py --from-harvest      # redo clustering + enrichment
    python build_catalog.py --from-clusters     # redo enrichment only

Four stages, each caching its output so an expensive stage is never repeated
by accident:

    1. HARVEST    every photo -> raw labels + how often each was seen   harvest.json
    2. CLUSTER    raw labels  -> canonical items with aliases           clusters.json
    3. ENRICH     canonical items -> weight, dimensions, material
    4. ASSEMBLE   everything -> catalog.json

Nobody photographs a reference item and nobody fills in a spreadsheet. The
catalog is assembled from what the detector already said, then reviewed by a
human once. That review is the only manual step and it is not optional: the
model produces inconsistent granularity and occasionally invents a category.

Every stage reports what it could not place rather than dropping it. A label
the clustering model forgot comes back as its own row; an enrichment answer
that cannot be matched is reported; a duplicate cluster is folded into the row
that owns its name. The reviewer sees all of it in the closing summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from catalog import (
    Catalog,
    CatalogError,
    CatalogItem,
    Dimensions,
    ItemMetadata,
    make_id,
    write_json,
)
from config import PLAYGROUND_DIR, default_model, load_env, make_client
from consensus import detect_stable
from labels import collapse_key, normalize
from openai import OpenAI
from pydantic import BaseModel, Field
from vision import SUPPORTED_SUFFIXES, DetectionError

# Enrichment is batched: one call per chunk of items. Small enough that a long
# reply cannot be truncated, large enough that the model sees related items
# together and keeps its units consistent across them.
ENRICH_BATCH_SIZE = 15


# --------------------------------------------------------------------------
# Stage 2 schema: clustering
# --------------------------------------------------------------------------


class ClusteredItem(BaseModel):
    canonical_label: str = Field(
        description="The best single name for this thing, lowercase singular."
    )
    aliases: list[str] = Field(
        description=(
            "Every OTHER observed label that means this same thing. Copy them "
            "exactly as they appeared in the input list. Do not invent new ones."
        )
    )
    visual_class: str = Field(
        description=(
            "What a visual detector should be told to look for. Usually the "
            "canonical label; broader when several rows look identical."
        )
    )
    excluded: bool = Field(
        description=(
            "True if this should NOT be collected: part of the building, a "
            "person, clothing, food, or rubbish."
        )
    )
    reason: str = Field(
        description=(
            "One short line: why excluded, or why these labels were merged. "
            "This exists so a human review is skimmable."
        )
    )


class ClusterResult(BaseModel):
    items: list[ClusteredItem]


_CLUSTER_PROMPT = """\
Below is every object label a vision model produced across a set of photographs,
with how many times each appeared. Group them into canonical items.

Merge two labels ONLY if they name the same physical object AND would be handled
identically. "table" and "desk" merge. "headset" and "headphone" merge.
"mouse" and "mouse pad" do NOT merge - they are different objects that happen to
have similar names. "office chair" and "plastic chair" do NOT merge - same
category, different objects.

Mark `excluded` for anything that is not a collectable item:
- structure of the building: wall, floor, ceiling, window, door, curtain
- people and clothing
- food, drink, and rubbish
- surfaces and fixtures that stay with the room

Every input label must appear exactly once, either as a canonical_label or in
exactly one aliases list. Do not drop any, and do not invent labels that are not
in the input.

Observed labels:
{labels}
"""


# --------------------------------------------------------------------------
# Stage 3 schema: metadata enrichment
# --------------------------------------------------------------------------


class EnrichedItem(BaseModel):
    canonical_label: str = Field(description="Copy exactly from the input list.")
    weight_kg: float | None = Field(
        description="Typical weight of ONE unit in kilograms. Null if unknowable."
    )
    weight_kg_min: float | None = Field(description="Low end of the plausible range.")
    weight_kg_max: float | None = Field(description="High end of the plausible range.")
    length_cm: float | None = Field(description="Longest dimension, centimetres.")
    width_cm: float | None = Field(description="Second dimension, centimetres.")
    height_cm: float | None = Field(description="Third dimension, centimetres.")
    material: str | None = Field(
        description="Dominant material, e.g. 'steel', 'plastic', 'wood'."
    )
    nestable: bool | None = Field(
        description="Do several of these stack into much less space? Chairs yes."
    )
    stackable: bool | None = Field(
        description="Can other items safely be placed on top of it?"
    )


class EnrichResult(BaseModel):
    items: list[EnrichedItem]


_ENRICH_PROMPT = """\
For each item below, give typical physical properties of ONE unit, as commonly
found in a household or small warehouse.

Rules:
- Estimate from general knowledge. These are approximations and are labelled as
  such downstream, so a reasonable estimate is far better than null.
- Use null only when the item is so variable that any number would mislead.
- Dimensions are the bounding box in centimetres, largest dimension first.
- Give a min and max weight that honestly reflect how much this varies.
- Do NOT estimate price. Price is not your job and a plausible wrong price is
  worse than no price.

Items:
{labels}
"""


# --------------------------------------------------------------------------
# Stage 1: harvest
# --------------------------------------------------------------------------


def find_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise DetectionError(f"Not a folder: {folder}")
    images = sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not images:
        raise DetectionError(f"No images in {folder}")
    return images


def harvest(
    images: list[Path], *, client: OpenAI, model: str, runs: int
) -> dict[str, int]:
    """Detect over every image and count how many photos each label appeared in.

    Counts *label occurrences*, not object counts: six chairs in one photo is
    one observation of "chair". The question this answers is "is this label
    real", not "how many are there".
    """
    frequencies: Counter[str] = Counter()

    for index, image in enumerate(images, start=1):
        print(f"  [{index}/{len(images)}] {image.name}", file=sys.stderr)
        try:
            items = detect_stable(image, client=client, model=model, runs=runs)
        except DetectionError as exc:
            # One bad photo must not throw away the rest of a long, paid run.
            print(f"      skipped: {exc}", file=sys.stderr)
            continue
        for item in items:
            frequencies[normalize(item.label)] += 1

    return dict(frequencies.most_common())


def load_harvest(path: Path) -> dict[str, int]:
    if not path.is_file():
        raise DetectionError(f"No cached harvest at {path}. Run a harvest first.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DetectionError(f"Could not read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DetectionError(f"{path} is not a label -> count mapping.")
    return {str(label): int(count) for label, count in payload.items()}


# --------------------------------------------------------------------------
# Stage 2: cluster
# --------------------------------------------------------------------------


def cluster(
    frequencies: dict[str, int], *, client: OpenAI, model: str
) -> list[ClusteredItem]:
    listing = "\n".join(
        f"- {label} (seen {count}x)" for label, count in frequencies.items()
    )
    try:
        completion = client.chat.completions.parse(
            model=model,
            messages=[
                {"role": "user", "content": _CLUSTER_PROMPT.format(labels=listing)}
            ],
            response_format=ClusterResult,
        )
    except Exception as exc:
        raise DetectionError(f"Clustering call failed: {exc}") from exc

    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise DetectionError("Clustering returned no parseable result.")
    return parsed.items


def reconcile(
    clusters: list[ClusteredItem], labels: list[str]
) -> tuple[list[ClusteredItem], list[str]]:
    """Check the clustering accounted for every input label; restore any it lost.

    The prompt asks the model to place every label. Asking is not checking: on
    a long list it reliably forgets a few. A forgotten label is returned as its
    own unmerged row, marked for review, rather than vanishing.

    Idempotent, so it is safe to run again on cached clusters.
    """
    covered: set[str] = set()
    for item in clusters:
        covered.add(collapse_key(item.canonical_label))
        covered.update(collapse_key(alias) for alias in item.aliases)

    missing = [
        label
        for label in labels
        if collapse_key(label) and collapse_key(label) not in covered
    ]
    restored = [
        ClusteredItem(
            canonical_label=label,
            aliases=[],
            visual_class=label,
            excluded=False,
            reason="Not placed by the clustering model; added unmerged for review.",
        )
        for label in missing
    ]
    return [*clusters, *restored], missing


def load_clusters(path: Path) -> list[ClusteredItem]:
    if not path.is_file():
        raise DetectionError(f"No cached clusters at {path}. Run without --from-clusters.")
    try:
        return ClusterResult.model_validate_json(path.read_text(encoding="utf-8")).items
    except (OSError, ValueError) as exc:
        raise DetectionError(f"Could not read {path}: {exc}") from exc


def save_clusters(path: Path, clusters: list[ClusteredItem]) -> None:
    write_json(path, ClusterResult(items=clusters).model_dump())


# --------------------------------------------------------------------------
# Stage 3: enrich
# --------------------------------------------------------------------------


def enrich(
    labels: list[str], *, client: OpenAI, model: str
) -> dict[str, EnrichedItem]:
    """Fill in physical metadata, one batch at a time.

    Returned facts are keyed by `collapse_key`, not by the exact label: the
    model is told to copy each name back verbatim and occasionally changes a
    space to a hyphen anyway. Keying on the collapsed form means that costs
    nothing.

    Weight and size are things a language model genuinely knows, because they
    are stable physical facts about kinds of object. Price is not, which is why
    it is absent from the schema entirely rather than merely discouraged.
    """
    enriched: dict[str, EnrichedItem] = {}

    for start in range(0, len(labels), ENRICH_BATCH_SIZE):
        batch = labels[start : start + ENRICH_BATCH_SIZE]
        listing = "\n".join(f"- {label}" for label in batch)
        print(
            f"  enriching {start + 1}-{start + len(batch)} of {len(labels)}",
            file=sys.stderr,
        )
        try:
            completion = client.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "user", "content": _ENRICH_PROMPT.format(labels=listing)}
                ],
                response_format=EnrichResult,
            )
        except Exception as exc:
            raise DetectionError(f"Enrichment call failed: {exc}") from exc

        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise DetectionError("Enrichment returned no parseable result.")
        for item in parsed.items:
            key = collapse_key(item.canonical_label)
            if key:
                enriched[key] = item

    return enriched


# --------------------------------------------------------------------------
# Stage 4: assemble
# --------------------------------------------------------------------------


def _metadata_from(facts: EnrichedItem | None) -> ItemMetadata:
    if facts is None:
        return ItemMetadata()
    return ItemMetadata(
        weight_kg=facts.weight_kg,
        weight_kg_min=facts.weight_kg_min,
        weight_kg_max=facts.weight_kg_max,
        dimensions=Dimensions(
            length_cm=facts.length_cm,
            width_cm=facts.width_cm,
            height_cm=facts.height_cm,
        ),
        material=facts.material,
        nestable=facts.nestable,
        stackable=facts.stackable,
        source="llm_estimate",
    )


def _claim_aliases(
    item: CatalogItem,
    aliases: set[str],
    owners: dict[str, CatalogItem],
    warnings: list[str],
) -> list[str]:
    """Give `item` every alias no other row owns. Report the ones it cannot have."""
    added: list[str] = []
    for alias in sorted(aliases):
        key = collapse_key(alias)
        if not key:
            continue
        holder = owners.get(key)
        if holder is item:
            continue
        if holder is not None:
            warnings.append(
                f"alias '{alias}' was given to both '{holder.id}' and '{item.id}'; "
                f"kept on '{holder.id}'"
            )
            continue
        owners[key] = item
        item.aliases.append(alias)
        added.append(alias)
    item.aliases.sort()
    return added


def assemble(
    clusters: list[ClusteredItem],
    enriched: dict[str, EnrichedItem],
    frequencies: dict[str, int],
) -> tuple[Catalog, list[str]]:
    """Combine clusters, enrichment and harvest counts into a validated catalog.

    Returns the catalog plus every conflict it had to settle, so the reviewer
    can check each one. Two kinds come up:

    A duplicate cluster — the model emitted a row whose name another row
    already owns. It is folded into that row: its aliases are synonyms of the
    same thing, and dropping them would lose exactly what clustering is for.

    A contested alias — two rows both claim "desk". The first row keeps it,
    since `Catalog` refuses an ambiguous alias (which row won would depend on
    file order). The reviewer can move it.
    """
    items: list[CatalogItem] = []
    owners: dict[str, CatalogItem] = {}  # every match key -> the row that owns it
    warnings: list[str] = []

    for cluster_item in clusters:
        canonical = normalize(cluster_item.canonical_label)
        canonical_key = collapse_key(canonical)
        if not canonical_key:
            warnings.append(
                f"skipped a cluster with an unusable name: {cluster_item.canonical_label!r}"
            )
            continue

        aliases = {normalize(alias) for alias in cluster_item.aliases} - {canonical}

        # Observations are counted only for names a row actually ends up
        # owning. Counting a contested or already-claimed alias would add the
        # same photos to two rows' totals.
        owner = owners.get(canonical_key)
        if owner is not None:
            added = _claim_aliases(owner, aliases, owners, warnings)
            owner.observations += sum(frequencies.get(name, 0) for name in added)
            extra = f", +{len(added)} alias(es)" if added else ""
            warnings.append(
                f"duplicate cluster '{canonical}' merged into '{owner.id}'{extra}"
            )
            continue

        item = CatalogItem(
            id=make_id(canonical),
            canonical_label=canonical,
            visual_class=normalize(cluster_item.visual_class) or canonical,
            excluded=cluster_item.excluded,
            exclusion_reason=cluster_item.reason if cluster_item.excluded else None,
            metadata=_metadata_from(enriched.get(canonical_key)),
        )
        owners[canonical_key] = item
        added = _claim_aliases(item, aliases, owners, warnings)
        item.observations = sum(
            frequencies.get(name, 0) for name in (canonical, *added)
        )
        items.append(item)

    # Catalog() re-checks every alias. The bookkeeping above is prevention;
    # this is the guarantee.
    return Catalog(items), warnings


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "images", type=Path, nargs="?", help="Folder of photographs to harvest"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PLAYGROUND_DIR / "catalog.json",
        help="Catalog to write",
    )
    parser.add_argument(
        "--harvest-file",
        type=Path,
        default=PLAYGROUND_DIR / "harvest.json",
        help="Where raw label frequencies are cached",
    )
    parser.add_argument(
        "--clusters-file",
        type=Path,
        default=PLAYGROUND_DIR / "clusters.json",
        help="Where the clustering result is cached",
    )
    parser.add_argument(
        "--from-harvest",
        action="store_true",
        help="Skip detection; reuse the cached harvest. Redoes clustering and "
        "enrichment.",
    )
    parser.add_argument(
        "--from-clusters",
        action="store_true",
        help="Skip detection and clustering; reuse both caches. Redoes "
        "enrichment only. Edit clusters.json by hand first if you like.",
    )
    parser.add_argument(
        "--runs", type=int, default=2, help="Detection passes per photo (default: 2)"
    )
    parser.add_argument(
        "--min-observations",
        type=int,
        default=1,
        help="Drop labels seen in fewer photos than this before clustering "
        "(default: 1, keep everything). Raise to 2 or 3 only once the photo set "
        "is large (20+); on a small set a real item may appear in one photo.",
    )
    parser.add_argument("--no-enrich", action="store_true", help="Skip stage 3")
    parser.add_argument("--model", default=default_model(), help="Model id")
    return parser.parse_args(argv)


def warn(message: str) -> None:
    print(f"  ! {message}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    load_env()
    args = parse_args(argv)
    notes: list[str] = []

    try:
        client = make_client()

        # ---- stage 1: harvest
        if args.from_harvest or args.from_clusters:
            frequencies = load_harvest(args.harvest_file)
            print(
                f"Reusing {args.harvest_file.name} ({len(frequencies)} labels)",
                file=sys.stderr,
            )
        else:
            if args.images is None:
                raise DetectionError(
                    "Give an image folder, or pass --from-harvest / --from-clusters."
                )
            images = find_images(args.images)
            print(
                f"Harvesting {len(images)} images x {args.runs} runs...",
                file=sys.stderr,
            )
            frequencies = harvest(
                images, client=client, model=args.model, runs=args.runs
            )
            # Saved immediately: if a later stage fails, the paid part survives.
            write_json(args.harvest_file, frequencies)
            print(f"Wrote {args.harvest_file.name}", file=sys.stderr)

        kept = {
            label: count
            for label, count in frequencies.items()
            if count >= args.min_observations
        }
        if not kept:
            raise DetectionError(
                f"Every label was seen fewer than {args.min_observations} times. "
                "Lower --min-observations or harvest more photos."
            )
        dropped = len(frequencies) - len(kept)
        print(
            f"{len(kept)} labels kept, {dropped} dropped below "
            f"{args.min_observations} observation(s)",
            file=sys.stderr,
        )

        # ---- stage 2: cluster
        if args.from_clusters:
            clusters = load_clusters(args.clusters_file)
            print(
                f"Reusing {args.clusters_file.name} ({len(clusters)} clusters)",
                file=sys.stderr,
            )
        else:
            print("Clustering...", file=sys.stderr)
            clusters = cluster(kept, client=client, model=args.model)

        clusters, missing = reconcile(clusters, list(kept))
        if missing:
            notes.append(
                f"clustering skipped {len(missing)} label(s), restored as "
                f"unmerged rows: {', '.join(missing[:8])}"
                + (" ..." if len(missing) > 8 else "")
            )
        save_clusters(args.clusters_file, clusters)
        print(f"{len(clusters)} clusters -> {args.clusters_file.name}", file=sys.stderr)

        # ---- stage 3: enrich
        if args.no_enrich:
            enriched: dict[str, EnrichedItem] = {}
        else:
            wanted = [
                normalize(item.canonical_label)
                for item in clusters
                if not item.excluded
            ]
            print(f"Enriching {len(wanted)} items...", file=sys.stderr)
            enriched = enrich(wanted, client=client, model=args.model)
            unanswered = [
                label for label in wanted if collapse_key(label) not in enriched
            ]
            if unanswered:
                notes.append(
                    f"enrichment returned nothing for {len(unanswered)} item(s): "
                    + ", ".join(unanswered[:8])
                    + (" ..." if len(unanswered) > 8 else "")
                )

        # ---- stage 4: assemble
        catalog, conflicts = assemble(clusters, enriched, frequencies)
        notes.extend(conflicts)
        catalog.save(args.out)

    except (DetectionError, CatalogError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    included = [item for item in catalog if not item.excluded]
    incomplete = catalog.incomplete()

    print(file=sys.stderr)
    print(f"Wrote {args.out}", file=sys.stderr)
    print(
        f"  {len(catalog)} items: {len(included)} collectable, "
        f"{len(catalog) - len(included)} excluded",
        file=sys.stderr,
    )
    if incomplete:
        notes.append(
            f"{len(incomplete)} collectable item(s) missing weight or volume: "
            + ", ".join(item.canonical_label for item in incomplete[:8])
            + (" ..." if len(incomplete) > 8 else "")
        )
    if notes:
        print(file=sys.stderr)
        print("Check these during review:", file=sys.stderr)
        for note in notes:
            warn(note)
    print(file=sys.stderr)
    print("NOW REVIEW IT BY HAND. The model gets granularity and exclusions", file=sys.stderr)
    print("wrong often enough that this step is not optional.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
