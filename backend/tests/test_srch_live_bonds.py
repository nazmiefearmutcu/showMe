"""SRCH live bond screener — keyless provider tier contracts (2026-09-16).

The pane stopped serving an 8-row static reference table: the live path now
refreshes the configured tenor set (US 3M..30Y, TIPS, DE/FR/IT/ES/GB/JP)
through the keyless tier chain — US Treasury curve → FRED CSV → Yahoo yield
indices. This file pins the honesty contract:

* every configured tenor has a mapped keyless provider OR an explicit
  ``quote_type="unavailable"`` label (never silently dropped);
* full provider success refreshes all 19 mapped tenors and keeps the table
  status "ok";
* partial coverage keeps every row (unresolved tenors labelled unavailable)
  and still reports "ok";
* total provider failure declares ``status="provider_unavailable"`` while
  the curated rows stay in the payload with no live labels (no fake yields);
* ``reference=true`` never touches the provider tiers.

Providers are monkeypatched at the module seam so the suite stays hermetic.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.screen import _funcs as screen_funcs
from showme.engine.functions.screen._funcs import SRCHFunction


def _frame(value: float, date_str: str = "2026-09-14") -> pd.DataFrame:
    return pd.DataFrame({"value": [value]}, index=pd.to_datetime([date_str]))


def _fred_fake(values: dict[str, float]):
    """Keyless FRED CSV fake: answers only the series ids in ``values``."""

    async def fake(
        series_id: str,
        *,
        client: Any = None,
        timeout: float = 8.0,
        lookback_days: int | None = None,
    ) -> pd.DataFrame | None:
        if series_id in values:
            return _frame(values[series_id])
        return None

    return fake


async def _no_fred(*_args: Any, **_kwargs: Any) -> None:
    return None


async def _no_quote(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise RuntimeError("yahoo quote disabled in test")


class _BoomCurve:
    async def yield_curve(self):
        raise RuntimeError("treasury csv down")


FOREIGN_2Y = ("DE2Y", "FR2Y", "IT2Y", "ES2Y", "GB2Y", "JP2Y")


def test_srch_live_refreshes_full_configured_tenor_set(monkeypatch) -> None:
    series = screen_funcs._FRED_YIELD_IDS
    values = {sid: 4.0 + index / 100 for index, sid in enumerate(series.values())}
    monkeypatch.setattr(screen_funcs, "fetch_fred_csv_series", _fred_fake(values))
    monkeypatch.setattr(screen_funcs, "fetch_quote_snapshot", _no_quote)

    result = asyncio.run(SRCHFunction().execute(query="yield >= 0", limit=50))
    rows = {row["symbol"]: row for row in result.data["rows"]}

    assert result.data["status"] == "ok"
    assert len(rows) == 25
    live = [row for row in rows.values() if row.get("quote_type") == "live"]
    assert len(live) == len(series) == 19
    assert rows["US10Y"]["yield"] == pytest.approx(
        4.0 + list(series.values()).index("DGS10") / 100
    )
    assert rows["US10Y"]["yield_state"] == "live"
    assert rows["US10Y"]["yield_source"] == "fred_csv"
    assert rows["US10Y"]["yield_cadence"] == "daily"
    assert rows["USTIPS10Y"]["quote_type"] == "live"
    assert rows["DE10Y"]["quote_type"] == "live"
    assert rows["DE10Y"]["yield_as_of"] == "2026-09-14"
    assert rows["DE10Y"]["yield_cadence"] == "monthly"
    # Foreign 2Y tenors have no keyless provider: explicit unavailable
    # markers while the curated value stays in the payload (never dropped).
    for symbol in FOREIGN_2Y:
        assert rows[symbol]["quote_type"] == "unavailable", symbol
        assert rows[symbol]["yield_state"] == "reference", symbol
        assert rows[symbol]["yield"] > 0, symbol
    assert "fred_csv" in result.sources
    assert "showme_bond_reference_universe" in result.sources
    assert result.metadata["live_rows"] == 19
    assert result.metadata["unavailable_rows"] == 6


def test_srch_partial_coverage_keeps_unavailable_markers(monkeypatch) -> None:
    monkeypatch.setattr(
        screen_funcs,
        "fetch_fred_csv_series",
        _fred_fake({"DGS10": 4.97, "DFII10": 2.6}),
    )

    async def quote(ticker: str) -> dict[str, Any]:
        return {
            "last": 3.96,
            "source": "yahoo_chart",
            "fetched_at": "2026-09-15T21:00:00+00:00",
        }

    monkeypatch.setattr(screen_funcs, "fetch_quote_snapshot", quote)

    result = asyncio.run(SRCHFunction().execute(query="yield >= 0", limit=50))
    rows = {row["symbol"]: row for row in result.data["rows"]}

    assert result.data["status"] == "ok"
    assert len(rows) == 25
    assert rows["US10Y"]["quote_type"] == "live"
    assert rows["US10Y"]["yield"] == pytest.approx(4.97)
    assert rows["USTIPS10Y"]["quote_type"] == "live"
    # The Yahoo tier fills the CBOE-mapped tenors FRED could not answer.
    assert rows["US3M"]["quote_type"] == "live"
    assert rows["US3M"]["yield"] == pytest.approx(3.96)
    assert rows["US3M"]["yield_source"] == "yahoo_quote"
    assert rows["US3M"]["yield_cadence"] == "intraday"
    # Unresolved configured tenors keep their curated rows, labelled.
    assert rows["US2Y"]["quote_type"] == "unavailable"
    assert rows["DE10Y"]["quote_type"] == "unavailable"
    for symbol in FOREIGN_2Y:
        assert rows[symbol]["quote_type"] == "unavailable", symbol
    assert any("no provider answer" in warning.lower() for warning in result.warnings)
    assert {"fred_csv", "yahoo_quote"} <= set(result.sources)


def test_srch_total_provider_failure_is_honest(monkeypatch) -> None:
    monkeypatch.setattr(screen_funcs, "fetch_fred_csv_series", _no_fred)
    monkeypatch.setattr(screen_funcs, "fetch_quote_snapshot", _no_quote)

    result = asyncio.run(
        SRCHFunction(FunctionDeps(ustreasury=_BoomCurve())).execute(query="yield >= 0")
    )
    rows = {row["symbol"]: row for row in result.data["rows"]}

    assert result.data["status"] == "provider_unavailable"
    assert len(rows) == 25
    assert all(row.get("quote_type") != "live" for row in rows.values())
    assert rows["US10Y"]["yield"] == 4.45  # curated value, not a fake live read
    assert rows["US10Y"]["quote_type"] == "unavailable"
    assert any("curve unavailable" in warning.lower() for warning in result.warnings)
    assert result.sources == ["showme_bond_reference_universe"]


def test_srch_reference_mode_never_calls_providers(monkeypatch) -> None:
    calls = {"fred": 0, "quote": 0}

    async def fred(*_args: Any, **_kwargs: Any):
        calls["fred"] += 1
        return None

    async def quote(*_args: Any, **_kwargs: Any):
        calls["quote"] += 1
        raise RuntimeError("no")

    monkeypatch.setattr(screen_funcs, "fetch_fred_csv_series", fred)
    monkeypatch.setattr(screen_funcs, "fetch_quote_snapshot", quote)

    result = asyncio.run(SRCHFunction().execute(query="yield >= 0", reference=True))
    assert calls == {"fred": 0, "quote": 0}
    assert result.data["status"] == "reference"
    assert result.sources == ["showme_bond_reference_universe"]


def test_srch_configured_tenors_have_reference_rows_or_markers() -> None:
    """Every live-target tenor must exist as a reference row (no orphans)."""
    rows = {row["symbol"] for row in screen_funcs._bond_reference_rows()}
    assert screen_funcs._LIVE_BOND_TENORS <= rows
    # The provider-mapped subset must never exceed the target set.
    assert screen_funcs._LIVE_BOND_PROVIDER_TENORS <= screen_funcs._LIVE_BOND_TENORS
