"""COUN — no constant or baseline series may be reported as live (G5 COUN#1).

The Turkish Real GDP id TURGDPRQDSMEI does not exist on FRED (HTTP 404). ECST
used to answer that with a constant 1.0 curve, which COUN reported as a live
FRED value under source_mode live_macro. Now:

* a series with no live observation becomes an explicit unavailable row
  (value None, source_mode provider_unavailable) with a reason and a warning;
* "fred" is listed as a source only when a FRED row is actually live;
* the TR GDP series uses NGDPRSAXDCTRQ (Real GDP, Republic of Turkiye, FRED,
  verified 2026-11-08: quarterly, millions of domestic currency, SA).

All providers are patched; no network is used.
"""

from __future__ import annotations

import asyncio

import pandas as pd

import showme.engine.functions.macro.ecst as ecst_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.macro.coun import COUNFunction


def _run(coro):
    return asyncio.run(coro)


class _BtmmDown:
    """BTMM policy adapter is unreachable in these tests."""

    def __init__(self, deps) -> None:
        self.deps = deps

    async def execute(self, **kwargs):
        raise RuntimeError("btmm offline (test)")


class _Fred:
    """FRED stand-in: serves only the ids listed in ``live``."""

    def __init__(self, live: dict[str, list[tuple[str, float]]] | None = None) -> None:
        self.live = live or {}
        self.calls: list[str] = []

    async def series(self, sid, *args, **kwargs):
        self.calls.append(sid)
        if sid not in self.live:
            raise RuntimeError(f"keyless FRED CSV unavailable for {sid!r}")
        points = self.live[sid]
        return pd.DataFrame(
            {"date": [d for d, _ in points], "value": [v for _, v in points]}
        )

    async def info(self, sid):
        raise RuntimeError("info unavailable (test)")


def _patch(monkeypatch, fred: _Fred) -> None:
    import showme.engine.functions.macro.coun as coun_mod

    monkeypatch.setattr(coun_mod, "BTMMFunction", _BtmmDown)
    monkeypatch.setattr(
        ecst_mod, "fred_with_keyless_fallback", lambda deps_fred, client=None: fred
    )


def _metric(result, name):
    matches = [row for row in result.data["rows"] if row.get("metric") == name]
    assert len(matches) == 1, f"expected one {name!r} row, got {matches}"
    return matches[0]


def test_tr_real_gdp_outage_is_unavailable_not_a_constant(monkeypatch):
    fred = _Fred()  # every id fails, incl. the old TURGDPRQDSMEI
    _patch(monkeypatch, fred)

    result = _run(COUNFunction(FunctionDeps()).execute(country="TR", live=True))
    gdp = _metric(result, "Real GDP")

    assert gdp["value"] is None, f"constant placeholder served as a value: {gdp}"
    assert gdp["source_mode"] == "provider_unavailable"
    assert "fred" not in result.sources
    assert result.data["source_mode"] != "live_macro"
    assert not any(card.get("label") == "Real GDP" for card in result.data["cards"])
    assert result.warnings, "the unavailable series must be disclosed"


def test_tr_gdp_uses_fred_series_that_exists_and_labels_fred_live(monkeypatch):
    fred = _Fred(
        live={"NGDPRSAXDCTRQ": [("2025-10-01", 654220.37), ("2026-04-01", 663580.06)]}
    )
    _patch(monkeypatch, fred)

    result = _run(COUNFunction(FunctionDeps()).execute(country="TR", live=True))
    gdp = _metric(result, "Real GDP")

    assert "TURGDPRQDSMEI" not in fred.calls, "the id that 404s on FRED must not be requested"
    assert gdp["value"] == 663580.06
    assert gdp["as_of"] == "2026-04-01"
    assert gdp["source_mode"] == "fred"
    assert "fred" in result.sources
    assert result.data["source_mode"] == "live_macro"
    assert any(card.get("label") == "Real GDP" for card in result.data["cards"])


def test_us_all_indicator_outage_never_reports_fred_or_live(monkeypatch):
    fred = _Fred()
    _patch(monkeypatch, fred)

    result = _run(COUNFunction(FunctionDeps()).execute(country="US", live=True))

    for name in ("Real GDP", "Inflation", "Unemployment rate", "10Y government yield"):
        row = _metric(result, name)
        assert row["value"] is None, f"{name} served a value without a live source"
        assert row["source_mode"] == "provider_unavailable"
    assert "fred" not in result.sources
    assert "macro_series_baseline" not in result.sources
    assert result.data["source_mode"] != "live_macro"
    assert not any(
        card.get("label") in {"Real GDP", "Inflation", "Unemployment rate", "10Y government yield"}
        for card in result.data["cards"]
    )
    assert all(point.get("source_mode") != "macro_series_baseline" for point in result.data["history"])
