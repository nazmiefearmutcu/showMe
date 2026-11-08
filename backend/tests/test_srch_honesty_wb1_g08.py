"""SRCH honesty contract — monthly quote type, curated-yield match flags, duration basis.

Pins three review findings on the bond screener live path:

* SRCH#3 — the OECD monthly foreign 10Y observations (FRED ``IRLTLT01*``) are
  labelled ``quote_type="monthly"``, not ``"live"``, and are excluded from the
  live count.
* SRCH#2 — a matched row whose yield is a curated value for a tenor no live
  provider answered (``quote_type="unavailable"``) is flagged in metadata and
  a warning; the filter never silently treats it as a verified yield.
* SRCH#4 — a row with a live yield carries a par-bond modified duration
  computed from that yield (``duration_basis``), with the curated duration kept
  as ``duration_curated``; non-live rows keep the curated duration labelled as
  such.

Providers are monkeypatched at the module seam so the suite stays hermetic.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest

from showme.engine.functions.screen import _funcs as screen_funcs
from showme.engine.functions.screen._funcs import SRCHFunction


def _frame(value: float, date_str: str = "2026-09-14") -> pd.DataFrame:
    return pd.DataFrame({"value": [value]}, index=pd.to_datetime([date_str]))


def _fred_fake(values: dict[str, float]):
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


async def _no_quote(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise RuntimeError("yahoo quote disabled in test")


def _par_duration(yield_pct: float, tenor_years: float) -> float:
    y = yield_pct / 100.0
    return (1.0 - (1.0 + y / 2.0) ** (-2.0 * tenor_years)) / y


def test_monthly_foreign_10y_is_not_tagged_live(monkeypatch) -> None:
    series = screen_funcs._FRED_YIELD_IDS
    values = {sid: 4.0 + index / 100 for index, sid in enumerate(series.values())}
    monkeypatch.setattr(screen_funcs, "fetch_fred_csv_series", _fred_fake(values))
    monkeypatch.setattr(screen_funcs, "fetch_quote_snapshot", _no_quote)

    result = asyncio.run(SRCHFunction().execute(query="yield >= 0", limit=50))
    rows = {row["symbol"]: row for row in result.data["rows"]}

    # SRCH#3: the monthly OECD 10Y observation is its own label, never "live".
    for symbol in ("DE10Y", "FR10Y", "IT10Y", "ES10Y", "GB10Y", "JP10Y"):
        assert rows[symbol]["quote_type"] == "monthly", symbol
        assert rows[symbol]["yield_cadence"] == "monthly", symbol
        assert rows[symbol]["yield_as_of"] == "2026-09-14", symbol
    assert rows["US10Y"]["quote_type"] == "live"
    live = [row for row in rows.values() if row.get("quote_type") == "live"]
    assert len(live) == 13
    assert result.metadata["live_rows"] == 13
    assert result.metadata["monthly_rows"] == 6
    assert result.data["status"] == "ok"


def test_unavailable_curated_yield_matches_are_flagged(monkeypatch) -> None:
    # SRCH#2: only US10Y resolves; every other tenor keeps its curated yield
    # labelled unavailable, and a yield floor still matches those curated values.
    monkeypatch.setattr(
        screen_funcs, "fetch_fred_csv_series", _fred_fake({"DGS10": 4.97})
    )
    monkeypatch.setattr(screen_funcs, "fetch_quote_snapshot", _no_quote)

    result = asyncio.run(SRCHFunction().execute(query="yield >= 4", limit=50))
    matched_unavailable = [
        row
        for row in result.data["rows"]
        if row.get("quote_type") == "unavailable" and row["yield"] >= 4
    ]
    assert matched_unavailable, "fixture must match at least one curated unavailable row"
    assert result.metadata["curated_yield_matches"] == len(matched_unavailable)
    assert any(
        "curated" in warning.lower() and "unavailable" in warning.lower()
        for warning in result.warnings
    )


def test_live_rows_carry_par_bond_duration_and_curated_rows_keep_basis(monkeypatch) -> None:
    # SRCH#4: the duration of a live-yield row is derived from that yield, and
    # the curated duration is preserved and labelled as such.
    series = screen_funcs._FRED_YIELD_IDS
    values = {sid: 4.0 + index / 100 for index, sid in enumerate(series.values())}
    monkeypatch.setattr(screen_funcs, "fetch_fred_csv_series", _fred_fake(values))
    monkeypatch.setattr(screen_funcs, "fetch_quote_snapshot", _no_quote)

    result = asyncio.run(SRCHFunction().execute(query="yield >= 0", limit=50))
    rows = {row["symbol"]: row for row in result.data["rows"]}

    us10 = rows["US10Y"]
    assert us10["duration_basis"] == "par_bond_model_from_live_yield"
    assert us10["duration_curated"] == pytest.approx(8.2)
    # Rounded to 2 dp in the payload.
    assert us10["duration"] == pytest.approx(_par_duration(us10["yield"], 10.0), abs=0.006)

    # Foreign monthly rows and unavailable rows keep the curated duration.
    assert rows["FR10Y"]["duration"] == pytest.approx(8.3)
    assert rows["FR10Y"]["duration_basis"] == "curated_reference"
    assert rows["GB2Y"]["duration"] == pytest.approx(1.9)
    assert rows["GB2Y"]["duration_basis"] == "curated_reference"
