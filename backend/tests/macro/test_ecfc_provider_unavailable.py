"""ECFC — Bug #N5 regression.

Previously the no-live-provider path returned identical 2.0% GDP / 2.8%
inflation / 4.1% unemployment rows for USA/CHN/BRA/JPN. The cockpit
displayed these as if they were a real forecast table. We now return
``status=provider_unavailable`` with empty rows + an explicit warning.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.functions.macro.ecfc import ECFCFunction  # noqa: E402


def test_ecfc_returns_empty_rows_when_live_not_requested() -> None:
    result = asyncio.run(ECFCFunction().execute(country="USA"))
    assert result.data["rows"] == []
    assert result.data["status"] == "provider_unavailable"
    assert result.data["data_state"] == "provider_unavailable"
    assert "no_live_source" in result.sources
    assert any("fabricate" in w.lower() for w in result.warnings)


def test_ecfc_does_not_return_identical_growth_for_each_country() -> None:
    """The original bug: USA/CHN/BRA/JPN all got value=2.0 for GDP."""
    rows = []
    for country in ("USA", "CHN", "BRA", "JPN"):
        result = asyncio.run(ECFCFunction().execute(country=country))
        rows.append((country, result.data["rows"]))
    # Either every country has empty rows (we refuse to fabricate) OR
    # the rows differ. With the fix we expect every country to have []
    # so no identical-fake-2.0% leak can happen.
    assert all(rows_for_country == [] for _, rows_for_country in rows), rows


def test_ecfc_methodology_explains_provider_unavailable() -> None:
    result = asyncio.run(ECFCFunction().execute(country="USA"))
    methodology = result.data["methodology"].lower()
    assert "imf" in methodology or "oecd" in methodology
    assert "provider_unavailable" in methodology or "no provider" in methodology
