"""COUN#2 — an uncurated country (JP) on the live path serves no placeholder numbers.

JP is outside the curated set (US, EU, GB, TR). With a fresh BIS policy row the
response must carry only that live row; no generic reference profile may add
inflation, unemployment or GDP numbers, and the missing profile must be stated
explicitly (profile_state, a warning) rather than hidden. All providers are
patched; no network.
"""

from __future__ import annotations

import asyncio
from datetime import date


import showme.engine.functions.macro.coun as coun_mod
import showme.engine.functions.macro.ecst as ecst_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.macro.coun import COUNFunction


def _run(coro):
    return asyncio.run(coro)


class _BtmmRows:
    def __init__(self, rows) -> None:
        self.rows = rows

    async def execute(self, **kwargs):
        from showme.engine.core.base_function import FunctionResult

        return FunctionResult(
            code="BTMM",
            instrument=None,
            data={"rows": self.rows},
            sources=["btmm"],
            warnings=[],
            metadata={},
        )


class _FredDown:
    """No FRED series at all: the live path has only the BTMM policy row."""

    async def series(self, sid, *args, **kwargs):
        raise RuntimeError(f"keyless FRED CSV unavailable for {sid!r}")

    async def info(self, sid):
        raise RuntimeError("info unavailable (test)")


def _patch(monkeypatch, btmm_rows) -> None:
    monkeypatch.setattr(coun_mod, "BTMMFunction", lambda deps: _BtmmRows(btmm_rows))
    monkeypatch.setattr(
        ecst_mod, "fred_with_keyless_fallback", lambda deps_fred, client=None: _FredDown()
    )
    monkeypatch.setattr(coun_mod, "_today", lambda: date(2026, 11, 8))


_JP_FRESH_POLICY = {
    "country_code": "JP",
    "country": "Japan",
    "policy_rate": 1.25,
    "as_of": "2026-11-03",
    "source": "BIS CBPOL",
    "freshness": "fresh",
}

# Numbers the retired generic fallback profile used to serve for any country.
_PLACEHOLDER_VALUES = {3.0, 6.0, 1.5}


def test_jp_live_path_serves_only_the_live_policy_row(monkeypatch):
    _patch(monkeypatch, [_JP_FRESH_POLICY])

    result = _run(COUNFunction(FunctionDeps()).execute(country="JP", live=True))

    rows = result.data["rows"]
    assert [row["metric"] for row in rows] == ["Policy rate"], rows
    assert rows[0]["value"] == 1.25
    assert rows[0]["as_of"] == "2026-11-03"
    assert all(row.get("source_mode") != "country_reference_profile" for row in rows)
    assert not any(row.get("value") in _PLACEHOLDER_VALUES for row in rows if row.get("metric") != "Policy rate")
    assert "country_reference_profile" not in result.sources
    assert result.sources == ["btmm"]


def test_jp_live_path_is_live_with_missing_profile_disclosed(monkeypatch):
    _patch(monkeypatch, [_JP_FRESH_POLICY])

    result = _run(COUNFunction(FunctionDeps()).execute(country="JP", live=True))

    assert result.data["source_mode"] == "live_macro"
    assert result.data["country_known"] is False
    # The missing profile is disclosed under profile_state, not as a top-level
    # status that would contradict the live policy row.
    assert "status" not in result.data
    assert result.data["profile_state"]["status"] == "needs_input"
    assert "JP" in result.data["profile_state"]["reason"]
    assert any("no curated profile" in warning for warning in result.warnings)


def test_jp_without_any_live_row_is_an_explicit_needs_input(monkeypatch):
    _patch(monkeypatch, [])

    result = _run(COUNFunction(FunctionDeps()).execute(country="JP", live=True))

    assert result.data["rows"] == []
    assert result.data["source_mode"] == "provider_unavailable"
    assert result.data["status"] == "needs_input"
    assert "profile_state" not in result.data
    assert result.sources == []
