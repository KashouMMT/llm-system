"""Ad-hoc runner for vision.py.

    python run.py ../images/room.jpg                  # open scan
    python run.py ../images/room.jpg laptop bottle    # count only these
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from vision import DetectionError, build_client, detect_items

# The repository's own .env, one level up — no separate playground config.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DEFAULT_MODEL = "gpt-5.6-luna"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python run.py <image> [label ...]", file=sys.stderr)
        return 2

    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("error: set LLM_API_KEY in the project .env", file=sys.stderr)
        return 1

    client = build_client(api_key, os.getenv("LLM_BASE_URL"))

    try:
        result = detect_items(
            Path(sys.argv[1]),
            client=client,
            model=os.getenv("DETECT_MODEL", DEFAULT_MODEL),
            targets=sys.argv[2:] or None,
        )
    except DetectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for item in result.items:
        print(f"{item.count:>3} x {item.label}  ({item.confidence:.2f})")
    print(f"--- {len(result.items)} kinds, {sum(i.count for i in result.items)} units")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())