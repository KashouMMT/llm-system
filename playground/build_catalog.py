"""Build a catalog from photographs, with no reference images and no data entry.

    python build_catalog.py ..\\images --out catalog.json

Four stages, each writing its output so the expensive ones are never repeated:

    1. HARVEST    every photo -> raw labels + how often each was seen   (costs money)
    2. CLUSTER    raw labels  -> canonical items with aliases           (one call)
    3. ENRICH     canonical items -> weight, dimensions, material       (a few calls)
    4. WRITE      catalog.json

Stage 1 is the only slow one, so it is cached in `harvest.json`. Re-run with
`--from-harvest` to redo clustering or enrichment for free while you tune the
prompts — which you will, several times.

Nobody photographs a reference item and nobody fills in a spreadsheet. The
catalog is assembled from what the detector already said, then reviewed by a
human once. That review is the only manual step and it is not optional: the
model produces inconsistent granularity and occasionally invents a category,
and two hours with the JSON file fixes both.
"""

from __future__ import annotations

import argparse
import json
import os
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
from consensus import detect_stable
from dotenv import load_dotenv
from labels import collapse_key, normalize
from openai import OpenAI
from pydantic import BaseModel, Field
from vision import DetectionError, build_client

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = "gpt-5.6-luna"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

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
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not images:
        raise DetectionError(f"No images in {folder}")
    return images


def harvest(
    images: list[Path], *, client: OpenAI, model: str, runs: int
) -> dict[str, int]:
    """Detect over every image and count how often each label was produced.

    Counts *label occurrences*, not object counts: seeing six chairs in one
    photo is one observation of "chair". The question this answers is "is this
    label real", not "how many are there".

    Nothing is excluded and nothing is thresholded here. A one-off sighting is
    still an observation, and the clustering stage handles the noise better
    than a blunt filter would.
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
            messages=[{"role": "user", "content": _CLUSTER_PROMPT.format(labels=listing)}],
            response_format=ClusterResult,
        )
    except Exception as exc:
        raise DetectionError(f"Clustering call failed: {exc}") from exc

    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise DetectionError("Clustering returned no parseable result.")
    return parsed.items


# --------------------------------------------------------------------------
# Stage 3: enrich
# --------------------------------------------------------------------------


def enrich(
    labels: list[str], *, client: OpenAI, model: str
) -> dict[str, EnrichedItem]:
    """Fill in physical metadata, one batch at a time.

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
            enriched[normalize(item.canonical_label)] = item

    return enriched


# --------------------------------------------------------------------------
# Stage 4: assemble
# --------------------------------------------------------------------------


def assemble(
    clusters: list[ClusteredItem],
    enriched: dict[str, EnrichedItem],
    frequencies: dict[str, int],
) -> Catalog:
    items: list[CatalogItem] = []
    seen_ids: set[str] = set()
    # Every match key already spoken for. The clustering model reliably assigns
    # the same alias to two clusters now and then, and `Catalog` refuses to load
    # an ambiguous alias — correctly, since which row won would depend on file
    # order. Resolving it here on a first-come basis costs one alias and saves
    # discarding an entire paid harvest. The reviewer can move it afterwards.
    claimed: set[str] = set()

    for cluster_item in clusters:
        canonical = normalize(cluster_item.canonical_label)
        item_id = make_id(canonical)
        # The model occasionally emits the same canonical twice; keeping both
        # would trip the same conflict check.
        if item_id in seen_ids or collapse_key(canonical) in claimed:
            continue
        seen_ids.add(item_id)

        # Observations for the whole cluster: the canonical plus every alias.
        names = [canonical, *(normalize(a) for a in cluster_item.aliases)]
        observations = sum(frequencies.get(name, 0) for name in names)

        facts = enriched.get(canonical)
        if facts is None:
            metadata = ItemMetadata()
        else:
            metadata = ItemMetadata(
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

        # Deduplicated, never containing the canonical itself (that would
        # conflict with its own row), and never an alias another row already
        # claimed.
        aliases = sorted(
            alias
            for alias in {normalize(a) for a in cluster_item.aliases} - {canonical}
            if collapse_key(alias) and collapse_key(alias) not in claimed
        )
        claimed.add(collapse_key(canonical))
        claimed.update(collapse_key(alias) for alias in aliases)

        items.append(
            CatalogItem(
                id=item_id,
                canonical_label=canonical,
                aliases=aliases,
                visual_class=normalize(cluster_item.visual_class) or canonical,
                excluded=cluster_item.excluded,
                exclusion_reason=cluster_item.reason if cluster_item.excluded else None,
                observations=observations,
                metadata=metadata,
            )
        )

    return Catalog(items)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "images", type=Path, nargs="?", help="Folder of photographs to harvest"
    )
    parser.add_argument(
        "--out", type=Path, default=HERE / "catalog.json", help="Catalog to write"
    )
    parser.add_argument(
        "--harvest-file",
        type=Path,
        default=HERE / "harvest.json",
        help="Where raw label frequencies are cached",
    )
    parser.add_argument(
        "--from-harvest",
        action="store_true",
        help="Skip detection and reuse the cached harvest. Free, and what you "
        "want while tuning the clustering or enrichment prompts.",
    )
    parser.add_argument(
        "--runs", type=int, default=2, help="Detection passes per photo (default: 2)"
    )
    parser.add_argument(
        "--min-observations",
        type=int,
        default=2,
        help="Drop labels seen fewer times than this before clustering "
        "(default: 2). Use 1 to keep everything.",
    )
    parser.add_argument("--no-enrich", action="store_true", help="Skip stage 3")
    parser.add_argument(
        "--model", default=os.getenv("DETECT_MODEL", DEFAULT_MODEL), help="Model id"
    )
    return parser.parse_args(argv)


def resolve_api_key() -> str:
    key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise DetectionError("No API key. Set LLM_API_KEY in the project .env.")
    return key


def main(argv: list[str] | None = None) -> int:
    load_dotenv(HERE.parent / ".env")
    args = parse_args(argv)

    try:
        client = build_client(resolve_api_key(), os.getenv("LLM_BASE_URL"))

        # ---- stage 1
        if args.from_harvest:
            if not args.harvest_file.is_file():
                raise DetectionError(f"No cached harvest at {args.harvest_file}")
            frequencies = json.loads(args.harvest_file.read_text(encoding="utf-8"))
            print(f"Reusing {args.harvest_file} ({len(frequencies)} labels)", file=sys.stderr)
        else:
            if args.images is None:
                raise DetectionError("Give an image folder, or pass --from-harvest.")
            images = find_images(args.images)
            print(f"Harvesting {len(images)} images x {args.runs} runs...", file=sys.stderr)
            frequencies = harvest(
                images, client=client, model=args.model, runs=args.runs
            )
            write_json(args.harvest_file, frequencies)
            print(f"Wrote {args.harvest_file}", file=sys.stderr)

        kept = {
            label: count
            for label, count in frequencies.items()
            if count >= args.min_observations
        }
        dropped = len(frequencies) - len(kept)
        if not kept:
            raise DetectionError(
                f"Every label was seen fewer than {args.min_observations} times. "
                "Lower --min-observations or harvest more photos."
            )
        print(
            f"{len(kept)} labels kept, {dropped} dropped below "
            f"{args.min_observations} observations",
            file=sys.stderr,
        )

        # ---- stage 2
        print("Clustering...", file=sys.stderr)
        clusters = cluster(kept, client=client, model=args.model)
        print(f"{len(clusters)} canonical items", file=sys.stderr)

        # ---- stage 3
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

        # ---- stage 4
        catalog = assemble(clusters, enriched, frequencies)
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
        print(
            f"  {len(incomplete)} missing weight or volume: "
            + ", ".join(item.canonical_label for item in incomplete[:8])
            + (" ..." if len(incomplete) > 8 else ""),
            file=sys.stderr,
        )
    print(file=sys.stderr)
    print("NOW REVIEW IT BY HAND. The model gets granularity and exclusions", file=sys.stderr)
    print("wrong often enough that this step is not optional.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
