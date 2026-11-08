"""The DCF pane's default inputs must equal the manifest defaults (DCF#4).

The pane hard-codes its starting values, so nothing else stops them drifting
from dcf_seed.py. This reads the pane source and compares its literal defaults
with the manifest. No network is used.
"""

from __future__ import annotations

import re
from pathlib import Path

from showme.manifest import REGISTRY, load_seeds

REPO = Path(__file__).resolve().parents[2]
PANE = REPO / "ui" / "src" / "functions" / "DCF.tsx"


def _pane_default(pattern: str) -> float:
    match = re.search(pattern, PANE.read_text(encoding="utf-8"), re.S)
    assert match is not None, f"pane default not found: {pattern}"
    return float(match.group(1))


def test_pane_defaults_equal_manifest_defaults() -> None:
    load_seeds()
    defaults = REGISTRY.get("DCF").defaults

    growth_pct = _pane_default(
        r'usePersistentNumber\(\s*"showme\.dcf\.growth_high_pct"\s*,\s*([0-9.]+)\s*\)'
    )
    term_pct = _pane_default(
        r'usePersistentNumber\(\s*"showme\.dcf\.gterm"\s*,\s*([0-9.]+)\s*\)'
    )
    years = _pane_default(
        r'usePersistentOption<number>\(\s*"showme\.dcf\.projection_years"\s*,'
        r"\s*YEARS_IDS\s*,\s*([0-9]+)\s*,?\s*\)"
    )

    # The pane stores percent; the manifest stores a decimal fraction.
    assert round(growth_pct / 100, 6) == defaults["growth_high"]
    assert round(term_pct / 100, 6) == defaults["growth_terminal"]
    assert years == defaults["years"]
