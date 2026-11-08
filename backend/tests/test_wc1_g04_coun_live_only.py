"""COUN — no hard-coded macro value may be served; live rows only (WC1-G04).

Covers COUN-R1 (hard-coded country profiles), COUN#3 (undated reference
inflation/unemployment beside live FRED rows, CPI level shown as inflation),
COUN#4 (stale FRED observations presented as live), COUN#6 (metrics and
provider_mode inputs not read) and COUN#7 (handler default for ``live``
disagrees with the seed default). All providers are patched; no network.
"""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import pandas as pd

import showme.engine.functions.macro.coun as coun_mod
import showme.engine.functions.macro.ecst as ecst_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.macro.coun import COUNFunction
from showme.manifest.seeds.coun_seed import coun


def _run(coro):
    return asyncio.run(coro)


class _BtmmDown:
    def __init__(self, deps) -> None:
        self.deps = deps

    async def execute(self, **kwargs):
        raise RuntimeError("btmm offline (test)")


class _Fred:
    """FRED stand-in: serves only the ids listed in ``live``."""

    def __init__(self, live: dict[str, list[tuple[str, float]]] | None = None) -> None:
        self.live = live or {}

    async def series(self, sid, *args, **kwargs):
        if sid not in self.live:
            raise RuntimeError(f"keyless FRED CSV unavailable for {sid!r}")
        points = self.live[sid]
        return pd.DataFrame(
            {"date": [d for d, _ in points], "value": [v for _, v in points]}
        )

    async def info(self, sid):
        raise RuntimeError("info unavailable (test)")


def _patch(monkeypatch, fred: _Fred) -> None:
    monkeypatch.setattr(coun_mod, "BTMMFunction", _BtmmDown)
    monkeypatch.setattr(
        ecst_mod, "fred_with_keyless_fallback", lambda deps_fred, client=None: fred
    )
    # Pin "today" so the staleness limits are deterministic.
    monkeypatch.setattr(coun_mod, "_today", lambda: date(2026, 11, 8))


def _rows_named(result, name):
    return [row for row in result.data["rows"] if row.get("metric") == name]


def test_offline_live_false_serves_no_reference_numbers(monkeypatch):
    """COUN-R1: the hard-coded US profile (inflation 3.1, unemployment 3.9) is gone."""
    _patch(monkeypatch, _Fred())

    result = _run(COUNFunction(FunctionDeps()).execute(country="US", live=False))

    served = [row for row in result.data["rows"] if row.get("value") is not None]
    assert served == [], f"reference numbers served without a live source: {served}"
    assert "country_reference_profile" not in result.sources
    assert all(row.get("source_mode") != "country_reference_profile" for row in result.data["rows"])


def test_offline_live_us_gaps_are_explicit_unavailable_rows(monkeypatch):
    """COUN-R1: with every provider down, each metric is an explicit unavailable row."""
    _patch(monkeypatch, _Fred())

    result = _run(COUNFunction(FunctionDeps()).execute(country="US", live=True))

    rows = result.data["rows"]
    assert rows, "a curated country must still show its metric gaps"
    assert all(row["value"] is None for row in rows), rows
    assert all(row["source_mode"] == "provider_unavailable" for row in rows)
    assert all(row.get("reason") for row in rows), "every gap must carry a reason"
    fiscal = _rows_named(result, "Fiscal balance")
    assert len(fiscal) == 1 and fiscal[0]["value"] is None
    assert result.data["source_mode"] == "provider_unavailable"
    assert result.data["source_mode"] != "live_macro"


def test_us_inflation_is_year_over_year_from_cpi_not_an_index_level(monkeypatch):
    """COUN#3: the Inflation row is the CPI y/y rate (336.298 / 324.245 - 1), not the index."""
    _patch(
        monkeypatch,
        _Fred(
            live={
                "CPIAUCSL": [
                    ("2025-09-01", 324.245),
                    ("2026-09-01", 336.298),
                ]
            }
        ),
    )

    result = _run(COUNFunction(FunctionDeps()).execute(country="US", live=True))

    inflation = _rows_named(result, "Inflation")
    assert len(inflation) == 1, f"expected one Inflation row, got {inflation}"
    assert inflation[0]["unit"] == "% y/y"
    assert inflation[0]["source_mode"] == "fred"
    assert inflation[0]["as_of"] == "2026-09-01"
    assert abs(inflation[0]["value"] - 3.72) < 0.01, inflation[0]
    assert all(row["value"] != 336.298 for row in result.data["rows"]), "CPI index must not be a row value"


def test_stale_fred_observation_is_flagged_not_presented_as_live(monkeypatch):
    """COUN#4: EU unemployment last observed 2022-10-01 is flagged stale and does not make the workbook live."""
    _patch(
        monkeypatch,
        _Fred(live={"LRHUTTTTEZQ156S": [("2022-09-01", 6.6), ("2022-10-01", 6.666667)]}),
    )

    result = _run(COUNFunction(FunctionDeps()).execute(country="EU", live=True))

    unemployment = _rows_named(result, "Unemployment rate")
    assert len(unemployment) == 1, unemployment
    assert unemployment[0]["as_of"] == "2022-10-01"
    assert unemployment[0].get("stale") is True, f"stale observation not flagged: {unemployment[0]}"
    assert result.data["source_mode"] != "live_macro"


def test_metrics_input_filters_rows(monkeypatch):
    """COUN#6: metrics=['inflation'] returns only the inflation rows."""
    _patch(
        monkeypatch,
        _Fred(
            live={
                "CPIAUCSL": [("2025-09-01", 324.245), ("2026-09-01", 336.298)],
                "UNRATE": [("2026-10-01", 4.1)],
            }
        ),
    )

    result = _run(
        COUNFunction(FunctionDeps()).execute(country="US", live=True, metrics=["inflation"])
    )

    assert {row["metric"] for row in result.data["rows"]} == {"Inflation"}


def test_live_defaults_on_when_flag_is_omitted(monkeypatch):
    """COUN#7: the handler default matches the seed default (live=true)."""
    _patch(monkeypatch, _Fred(live={"UNRATE": [("2026-10-01", 4.1)]}))

    result = _run(COUNFunction(FunctionDeps()).execute(country="US"))

    assert "fred" in result.sources
    assert _rows_named(result, "Unemployment rate")[0]["value"] == 4.1


def test_provider_mode_input_is_removed_because_nothing_reads_it():
    """COUN#6: the seed must not offer provider_mode, which the handler never reads."""
    assert "provider_mode" not in [spec.name for spec in coun.inputs]
    assert "provider_mode" not in (coun.defaults or {})


def test_gdp_level_unit_is_chained_usd_not_index(monkeypatch):
    """Guard for COUN#5: GDPC1 is billions of chained 2017 USD, never 'index'."""
    _patch(monkeypatch, _Fred(live={"GDPC1": [("2026-07-01", 24611.077)]}))

    result = _run(COUNFunction(FunctionDeps()).execute(country="US", live=True))

    gdp = _rows_named(result, "Real GDP")
    assert len(gdp) == 1
    assert gdp[0]["unit"] == "bn chained USD"


class _BtmmRows:
    """BTMM stand-in returning policy rows shaped like BTMMFunction output."""

    def __init__(self, rows) -> None:
        self.rows = rows

    async def execute(self, **kwargs):
        return SimpleNamespace(data={"rows": self.rows})


def _patch_btmm_rows(monkeypatch, rows) -> None:
    monkeypatch.setattr(coun_mod, "BTMMFunction", lambda deps: _BtmmRows(rows))


def test_policy_path_skips_stale_legacy_row_and_uses_fresh_row(monkeypatch):
    """COUN#4: a stale BIS row (1998) must not drive the live policy rate."""
    _patch(monkeypatch, _Fred())
    _patch_btmm_rows(
        monkeypatch,
        [
            {"country_code": "EU", "country": "Euro area", "policy_rate": 2.0,
             "as_of": "1998-01-01", "source": "BIS CBPOL", "freshness": "stale"},
            {"country_code": "EU", "country": "Euro area", "policy_rate": 2.15,
             "as_of": "2026-10-30", "source": "BIS CBPOL", "freshness": "fresh"},
        ],
    )

    result = _run(COUNFunction(FunctionDeps()).execute(country="EU", live=True))

    policy = _rows_named(result, "Policy rate")
    assert len(policy) == 1
    assert policy[0]["value"] == 2.15
    assert policy[0]["as_of"] == "2026-10-30"
    assert "btmm" in result.sources
    assert result.data["source_mode"] == "live_macro"


def test_policy_path_stale_only_row_is_not_live(monkeypatch):
    """COUN#4: a policy row that is only stale or undated never makes the workbook live."""
    _patch(monkeypatch, _Fred())
    _patch_btmm_rows(
        monkeypatch,
        [
            {"country_code": "EU", "country": "Euro area", "policy_rate": 2.0,
             "as_of": "1998-01-01", "source": "BIS CBPOL", "freshness": "stale"},
        ],
    )

    result = _run(COUNFunction(FunctionDeps()).execute(country="EU", live=True))

    policy = _rows_named(result, "Policy rate")
    assert len(policy) == 1
    assert policy[0]["value"] is None
    assert policy[0]["source_mode"] == "provider_unavailable"
    assert "btmm" not in result.sources
    assert result.data["source_mode"] != "live_macro"
    assert any("not fresh" in warning for warning in result.warnings)


class _WorldBankGdp:
    """World Bank stand-in: NY.GDP.MKTP.KD is constant 2015 USD, in units of USD."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def indicator(self, country, indicator):
        self.calls.append(indicator)
        return pd.DataFrame(
            {"date": ["2025-07-01", "2026-07-01"], "value": [22.0e12, 23.0e12]}
        )


def test_worldbank_gdp_fallback_is_labelled_constant_2015_usd_not_chained(monkeypatch):
    """COUN units: the World Bank fallback for GDPC1 is constant 2015 USD, not chained USD."""
    _patch(monkeypatch, _Fred())
    worldbank = _WorldBankGdp()

    result = _run(
        COUNFunction(FunctionDeps(worldbank=worldbank)).execute(country="US", live=True)
    )

    assert "NY.GDP.MKTP.KD" in worldbank.calls
    gdp = _rows_named(result, "Real GDP")
    assert len(gdp) == 1
    assert gdp[0]["source_mode"] == "worldbank"
    assert gdp[0]["value"] == 23000.0
    assert gdp[0]["unit"] == "bn constant 2015 USD"
    assert "chained" not in gdp[0]["unit"]


def test_history_honours_metrics_input(monkeypatch):
    """Minor cross-cutting: history[] follows the metrics subset like rows and cards do."""
    live = {
        "GDPC1": [("2025-07-01", 24000.0), ("2026-07-01", 24611.077)],
        "UNRATE": [("2026-10-01", 4.1)],
    }
    _patch(monkeypatch, _Fred(live=live))

    unfiltered = _run(COUNFunction(FunctionDeps()).execute(country="US", live=True))
    assert unfiltered.data["history"], "GDP level history expected without a metrics filter"

    filtered = _run(
        COUNFunction(FunctionDeps()).execute(country="US", live=True, metrics=["unemployment"])
    )
    assert filtered.data["history"] == []
