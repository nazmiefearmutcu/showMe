#!/usr/bin/env python3
"""Fail-fast sentinel scanner for ShowMe audit artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


DEFAULT_DENY = (
    "No rows",
    "No ratios",
    "function did not return",
    "undefined",
    "NaN",
    "null table",
    "NONE",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="artifacts/showme-function-audit")
    parser.add_argument("--deny", nargs="*", default=list(DEFAULT_DENY))
    parser.add_argument("--allow-empty-state-with-reason", action="store_true")
    args = parser.parse_args()

    root = Path(args.path)
    if not root.exists():
        raise SystemExit(f"scan path does not exist: {root}")

    # If the root contains subdirectories, resolve to the latest one
    if root.is_dir():
        subdirs = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if subdirs:
            root = max(subdirs, key=lambda d: d.name)

    hits: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl", ".md", ".log", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for sentinel in args.deny:
            if sentinel and sentinel in text:
                if args.allow_empty_state_with_reason and _allowed_empty_context(text, sentinel):
                    continue
                hits.append(f"{path}: {sentinel}")

    if hits:
        print("sentinel audit failed:")
        for hit in hits[:200]:
            print(f"- {hit}")
        if len(hits) > 200:
            print(f"- ... {len(hits) - 200} more")
        return 1
    print(f"sentinel audit passed: {root}")
    return 0


def _allowed_empty_context(text: str, sentinel: str) -> bool:
    if sentinel not in {"No rows", "No ratios", "NONE"}:
        return False
    lowered = text.lower()
    return "status" in lowered and "empty" in lowered and "reason" in lowered and (
        "nextaction" in lowered or "next_actions" in lowered
    )


if __name__ == "__main__":
    sys.exit(main())
