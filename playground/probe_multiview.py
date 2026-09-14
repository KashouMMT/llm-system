"""Probe: does the model deduplicate one object seen from several angles?

    python probe_multiview.py ..\\images\\room\\room_1.jpg ..\\images\\room\\room_2.jpg
    python probe_multiview.py ..\\images\\room\\*.jpg --runs 3

Throwaway scaffolding for one decision (TODO §11a): whether a single vision
call, given several photographs of one room, reports "1 sofa" rather than
"3 sofas" when the sofa merely appears in three of them. Also the prototype
of the phase-5/7 multi-frame call — detect_items_multi in vision.py is the
part of this that survives past the experiment; this script is not meant to
be kept polished.

Costs real API calls. The caller pays for those, not this script.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from config import default_model, load_env, make_client
from vision import DetectionError, detect_items_multi


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send several photos of one room in a single call and see "
        "whether the model deduplicates objects seen from multiple angles."
    )
    parser.add_argument(
        "images",
        type=Path,
        nargs="+",
        help="Paths to two or more .jpg/.png/.webp images of the same room",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="How many independent calls to make, so runs can be compared "
        "by eye (default: 1)",
    )
    parser.add_argument(
        "--model",
        default=default_model(),
        help="Model to call (default: $DETECT_MODEL, or the project default)",
    )
    return parser.parse_args(argv)


def print_run(run: int, total_runs: int, items) -> None:
    print(f"\n=== run {run}/{total_runs} ===")

    if not items:
        print("  (nothing detected)")
        return

    label_w = max(len("item"), max(len(item.label) for item in items))
    for item in items:
        print(
            f"  {item.label.ljust(label_w)}  "
            f"count={item.count}  conf={item.confidence:.2f}"
        )
    print(f"  {len(items)} kinds, {sum(item.count for item in items)} units")


def main(argv: list[str] | None = None) -> int:
    load_env()
    args = parse_args(argv)

    if len(args.images) < 2:
        print(
            "error: give at least two images — this script tests whether "
            "the model recognises the same object across views",
            file=sys.stderr,
        )
        return 1

    try:
        client = make_client()
    except DetectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Images: {', '.join(str(p) for p in args.images)}")
    print(f"Model:  {args.model}")

    exit_code = 0
    for run in range(1, args.runs + 1):
        try:
            result = detect_items_multi(args.images, client=client, model=args.model)
        except DetectionError as exc:
            print(f"\n=== run {run}/{args.runs} ===\nerror: {exc}", file=sys.stderr)
            exit_code = 1
            continue

        print_run(run, args.runs, result.items)

    print()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
