"""CLI: the product. One image in, a review-ready item list with metadata out.

    python estimate.py ..\\images\\table.jpg
    python estimate.py ..\\images\\table.jpg --runs 5
    python estimate.py ..\\images\\table.jpg --json

`detect.py` is the raw detection tool used for harvesting and debugging; this is
the pipeline a product would call. The difference is the catalog: `detect.py`
reports whatever the model said, `estimate.py` reports catalog items with their
physical metadata, plus an explicit account of everything it could not settle.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from catalog import Catalog, CatalogError
from config import PLAYGROUND_DIR, default_model, load_env, make_client
from consensus import detect_stable
from resolve import Resolution, ResolvedItem, UnmatchedItem, grouping_key, resolve
from vision import DetectionError


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path, help="Path to a .jpg/.png/.webp image")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=PLAYGROUND_DIR / "catalog.json",
        help="Catalog file",
    )
    parser.add_argument(
        "--runs", type=int, default=3, help="Detection passes (default: 3)"
    )
    parser.add_argument(
        "--min-runs-seen",
        type=int,
        default=2,
        help="Detections seen in fewer runs than this are reported separately "
        "as low-agreement, not counted in totals (default: 2)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--model", default=default_model(), help="Model id")
    return parser.parse_args(argv)


def format_number(value: float | None, unit: str, places: int = 1) -> str:
    return "?" if value is None else f"{value:.{places}f}{unit}"


def format_count(item: ResolvedItem) -> str:
    if item.count_min == item.count_max:
        return str(item.count)
    return f"{item.count} ({item.count_min}-{item.count_max})"


def render_items(items: list[ResolvedItem], title: str) -> str:
    if not items:
        return f"{title}: none"

    rows = [
        (
            item.label,
            format_count(item),
            format_number(item.total_weight_kg, " kg"),
            format_number(item.total_volume_m3, " m3", 2),
            f"{item.runs_seen}/{item.total_runs}",
        )
        for item in items
    ]
    headers = ("item", "count", "weight", "volume", "agree")
    widths = [
        max(len(headers[column]), max(len(row[column]) for row in rows))
        for column in range(len(headers))
    ]

    def line(values: tuple[str, ...]) -> str:
        cells = [
            values[0].ljust(widths[0]),
            *(values[column].rjust(widths[column]) for column in range(1, 5)),
        ]
        return "  " + "  ".join(cells)

    out = [
        f"{title} ({len(items)}):",
        line(headers),
        "  " + "  ".join("-" * width for width in widths),
    ]
    for item, row in zip(items, rows):
        # "!" means the runs disagreed badly enough that the model was
        # estimating the count rather than counting it.
        out.append(line(row) + (" !" if item.count_is_unstable else ""))
    return "\n".join(out)


def render_unmatched(items: list[UnmatchedItem], title: str) -> str:
    lines = [f"{title} ({len(items)}):"]
    for item in items:
        lines.append(
            f"  {item.label}  x{item.count}  ({item.runs_seen}/{item.total_runs} runs)"
        )
    return "\n".join(lines)


def render_totals(resolution: Resolution) -> str:
    lines = [
        "Totals:",
        f"  kinds   {len(resolution.matched)}",
        f"  units   {sum(item.count for item in resolution.matched)}",
        f"  weight  {format_number(resolution.total_weight_kg, ' kg')}",
        f"  volume  {format_number(resolution.total_volume_m3, ' m3', 2)}",
    ]
    if resolution.total_price is not None:
        lines.append(f"  price   {resolution.total_price:.2f}")

    # A total assembled from partial data is misleading unless it says what it
    # left out, so this warning is printed with the number, not instead of it.
    incomplete = resolution.items_missing_metadata
    if incomplete:
        names = ", ".join(item.label for item in incomplete[:6])
        suffix = " ..." if len(incomplete) > 6 else ""
        lines.append(
            f"  ! totals exclude {len(incomplete)} item(s) with missing "
            f"metadata: {names}{suffix}"
        )
    return "\n".join(lines)


def render_low_agreement(low: Resolution, min_runs_seen: int) -> str:
    """Items too few runs agreed on. Not counted — but never silently dropped.

    A thing seen in one run of three may be a real object the model only
    noticed once. Low-agreement items the catalog excludes need no human, so
    they are summarised rather than listed.
    """
    title = f"Low agreement - seen in fewer than {min_runs_seen} runs, not counted"
    lines = [f"{title}:"]
    for item in low.matched:
        lines.append(
            f"  {item.label}  x{item.count}  ({item.runs_seen}/{item.total_runs} runs)"
        )
    for item in low.unmatched:
        lines.append(
            f"  {item.label}  x{item.count}  ({item.runs_seen}/{item.total_runs} runs)"
            "  [not in catalog]"
        )
    if low.excluded:
        lines.append(f"  (+{len(low.excluded)} excluded by catalog)")
    return "\n".join(lines)


def to_payload(item: ResolvedItem) -> dict:
    return {
        "id": item.catalog_item.id,
        "label": item.label,
        "observed_labels": item.observed_labels,
        "count": item.count,
        "count_min": item.count_min,
        "count_max": item.count_max,
        "count_is_unstable": item.count_is_unstable,
        "runs_seen": item.runs_seen,
        "total_runs": item.total_runs,
        "total_weight_kg": item.total_weight_kg,
        "total_volume_m3": item.total_volume_m3,
        "metadata": item.metadata.model_dump(),
    }


def resolution_payload(resolution: Resolution) -> dict:
    return {
        "matched": [to_payload(item) for item in resolution.matched],
        "excluded": [to_payload(item) for item in resolution.excluded],
        "unmatched": [item.model_dump() for item in resolution.unmatched],
    }


def main(argv: list[str] | None = None) -> int:
    load_env()
    args = parse_args(argv)

    try:
        # The catalog loads first: if it is broken, find out before paying for
        # detection.
        catalog = Catalog.load(args.catalog)
        client = make_client()
        # Grouping through the catalog merges synonyms per run — the only point
        # where "one table, named differently" and "a table and a desk" can
        # still be told apart.
        detected = detect_stable(
            args.image,
            client=client,
            model=args.model,
            runs=args.runs,
            key=grouping_key(catalog),
        )
    except (DetectionError, CatalogError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    confident = [item for item in detected if item.runs_seen >= args.min_runs_seen]
    low = [item for item in detected if item.runs_seen < args.min_runs_seen]
    resolution = resolve(confident, catalog)
    low_resolution = resolve(low, catalog)

    if args.json:
        print(
            json.dumps(
                {
                    "image": str(args.image),
                    "model": args.model,
                    "runs": args.runs,
                    "min_runs_seen": args.min_runs_seen,
                    "catalog_items": len(catalog),
                    **resolution_payload(resolution),
                    "low_agreement": resolution_payload(low_resolution),
                    "totals": {
                        "weight_kg": resolution.total_weight_kg,
                        "volume_m3": resolution.total_volume_m3,
                        "price": resolution.total_price,
                    },
                },
                indent=2,
            )
        )
        return 0

    # Every section prints whenever it is non-empty. Nothing detected is ever
    # discarded without the reviewer seeing it.
    print()
    print(render_items(resolution.matched, "Collectable"))
    print()
    print(render_totals(resolution))

    if resolution.excluded:
        print()
        print(render_items(resolution.excluded, "Excluded by catalog"))

    if resolution.unmatched:
        print()
        print(render_unmatched(resolution.unmatched, "Not in catalog - needs a human"))

    if low_resolution.matched or low_resolution.unmatched or low_resolution.excluded:
        print()
        print(render_low_agreement(low_resolution, args.min_runs_seen))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
