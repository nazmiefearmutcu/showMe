#!/usr/bin/env python3
"""MEET contract generator — Gate-1 (quality-gate suite).

Builds ``contracts/meet.json`` from the manifest (``meet_seed.meet``) and
``meet._DATA_FILTERS``. The JSON is the single source of truth consumed by
the drift-gate tests; the UI reads the JSON, never the Python.

Deterministic output: ``json.dump(sort_keys=True, indent=2)`` + trailing
newline. Only the two MEET modules below are imported from ``showme`` (no
unrelated import chains); ``backend/`` is added to ``sys.path``.

Usage:
    python scripts/gen_meet_contract.py            # write contracts/meet.json
    python scripts/gen_meet_contract.py --stdout   # print to stdout (freshness gate)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[1]
_BACKEND_DIR = _REPO_ROOT / "backend"
_CONTRACT_PATH = _REPO_ROOT / "contracts" / "meet.json"

if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.functions.comm import meet as meet_mod  # noqa: E402
from showme.manifest.seeds import meet_seed  # noqa: E402


def build_contract() -> dict:
    manifest = meet_seed.meet() if callable(meet_seed.meet) else meet_seed.meet
    return {
        "inputs": [
            {
                "name": inp.name,
                "options": list(inp.options) if inp.options is not None else None,
                "default": manifest.defaults.get(inp.name),
            }
            for inp in manifest.inputs
        ],
        "must_have": list(manifest.output_contract.must_have),
        "card_slots": [slot.key for slot in manifest.card_schema.slots],
        "data_filter_values": sorted(meet_mod._DATA_FILTERS),
    }


def render(contract: dict) -> str:
    return json.dumps(contract, sort_keys=True, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate contracts/meet.json")
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print the contract to stdout instead of writing the file.",
    )
    args = parser.parse_args(argv)
    text = render(build_contract())
    if args.stdout:
        sys.stdout.write(text)
    else:
        _CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONTRACT_PATH.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
