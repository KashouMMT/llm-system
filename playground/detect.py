"""CLI: detect, stabilise, and filter the objects in one image.

    python detect.py ..\\images\\table.jpg
    python detect.py ..\\images\\table.jpg --runs 5
    python detect.py ..\\images\\table.jpg --no-exclude
    python detect.py ..\\images\\table.jpg --only laptop "power strip"
    python detect.py ..\\images\\table.jpg --json

This is the wiring, and nothing else: it owns argument parsing, configuration
and output formatting. Every decision it makes is delegated — what is in the
image to `consensus`, what we care about to `exclusions`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from consensus import StableItem, detect_stable
from dotenv import load_dotenv
from exclusions import load_exclusions, partition
from vision import DetectionError, build_client

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = "gpt-5.6-luna"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect and count objects in one image."
    )
    parser.add_argument("image", type=Path, help="Path to a .jpg/.png/.webp image")
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="How many independent passes to average over (default: 3). "
        "1 disables stabilisation and shows raw single-pass output.",
    )
    parser.add_argument(
        "--min-runs-seen",
        type=int,
        default=2,
        help="Keep an item only if at least this many runs reported it "
        "(default: 2). Use 1 to keep everything, e.g. when harvesting "
        "labels to build a catalog.",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="LABEL",
        help="Count only these objects instead of scanning for everything",
    )
    parser.add_argument(
        "--exclusions",
        type=Path,
        default=HERE / "exclusions.txt",
        help="Exclusion list file (default: exclusions.txt beside this script)",
    )
    parser.add_argument(
        "--no-exclude",
        action="store_true",
        help="Report everything, without applying the exclusion list",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of a table"
    )
    parser.add_argument(
        "--model",
        default=os.getenv("DETECT_MODEL", DEFAULT_MODEL),
        help=f"Model to call (default: {DEFAULT_MODEL}, or $DETECT_MODEL)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Sampling temperature. Omitted by default: gpt-5.6-luna and other "
        "reasoning models reject the parameter. Set it only for a model that "
        "accepts one.",
    )
    return parser.parse_args(argv)


def resolve_api_key() -> str:
    """Accept either name, so this shares the repository's existing .env."""
    key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise DetectionError(
            "No API key. Set LLM_API_KEY (or OPENAI_API_KEY) in the project .env."
        )
    return key


def format_count(item: StableItem) -> str:
    """Show the spread when the runs disagreed, so an estimate looks like one."""
    if item.count_min == item.count_max:
        return str(item.count)
    return f"{item.count} ({item.count_min}-{item.count_max})"


def render_table(items: list[StableItem], title: str) -> str:
    if not items:
        return f"{title}: none"

    counts = [format_count(item) for item in items]
    label_w = max(len("item"), max(len(item.label) for item in items))
    count_w = max(len("count"), max(len(text) for text in counts))

    lines = [
        f"{title} ({len(items)}):",
        f"  {'item'.ljust(label_w)}  {'count'.rjust(count_w)}  agree  conf",
        f"  {'-' * label_w}  {'-' * count_w}  -----  ----",
    ]
    for item, count_text in zip(items, counts):
        # "!" marks a count the runs disagreed about badly enough that the
        # model was estimating rather than counting. That is a review flag,
        # not a failure.
        flag = " !" if item.count_is_unstable else ""
        lines.append(
            f"  {item.label.ljust(label_w)}  {count_text.rjust(count_w)}  "
            f"{item.runs_seen}/{item.total_runs}    {item.mean_confidence:.2f}{flag}"
        )
    lines.append(
        f"  {len(items)} kinds, {sum(item.count for item in items)} units"
    )
    return "\n".join(lines)


def to_payload(item: StableItem) -> dict:
    data = item.model_dump()
    data["agreement"] = round(item.agreement, 3)
    data["count_is_unstable"] = item.count_is_unstable
    return data


def main(argv: list[str] | None = None) -> int:
    # The repository's own .env, one level up. No separate playground config.
    load_dotenv(HERE.parent / ".env")

    args = parse_args(argv)

    try:
        client = build_client(resolve_api_key(), os.getenv("LLM_BASE_URL"))
        items = detect_stable(
            args.image,
            client=client,
            model=args.model,
            runs=args.runs,
            targets=args.only,
            temperature=args.temperature,
        )
    except (DetectionError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Two independent reasons an item does not reach the final list, reported
    # separately because they mean completely different things. "Too few runs
    # agreed" is a measurement problem; "on the exclusion list" is policy.
    agreed = [item for item in items if item.runs_seen >= args.min_runs_seen]
    uncertain = [item for item in items if item.runs_seen < args.min_runs_seen]

    # An explicit --only list already says what the caller wants; filtering it
    # again through the exclusion list would be absurd.
    if args.no_exclude or args.only:
        kept, dropped = agreed, []
    else:
        kept, dropped = partition(agreed, load_exclusions(args.exclusions))

    if args.json:
        print(
            json.dumps(
                {
                    "image": str(args.image),
                    "model": args.model,
                    "runs": args.runs,
                    "min_runs_seen": args.min_runs_seen,
                    "kept": [to_payload(item) for item in kept],
                    "excluded": [to_payload(item) for item in dropped],
                    "uncertain": [to_payload(item) for item in uncertain],
                },
                indent=2,
            )
        )
        return 0

    # Every section is always printed when non-empty, never silent: an item
    # wrongly dropped is the failure mode that is hardest to notice and most
    # expensive to miss.
    print()
    print(render_table(kept, "Detected"))
    if dropped:
        print()
        print(render_table(dropped, "Excluded by list"))
    if uncertain:
        print()
        print(
            render_table(
                uncertain,
                f"Seen in fewer than {args.min_runs_seen} runs - needs a human",
            )
        )
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
