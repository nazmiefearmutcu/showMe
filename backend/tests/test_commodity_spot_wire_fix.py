"""FIX F2 (SHOWME FUNCTION AUDIT 2026-09-11) — commodity spot wire fixes.

Pins the regressions reported by the audit for the commodity family:

  * A3-H — BGAS EIA rows were served raw (`value`/`period`) while the shared
    commodity pane filters on `last`, so every EIA row was dropped and the
    pane showed an empty grid next to a "live quote" pill. The function now
    normalizes the EIA series into the SpotRow shape (+ ascending history).
  * A8-H — BOIL is documented as the Brent−WTI pair but the workspace default
    instrument (CL=F) narrowed the backend to ONE leg, so `spread` stayed
    null and the advertised spread card never rendered. The pair is now
    always fetched; the requested leg only controls row order, and an
    explicit `benchmark=` selector can still narrow deliberately.
  * adjacent — the EIA QUOTE path returned `iloc[0]` of a frame that
    `series_data` sorts ASCENDING by period, i.e. the OLDEST observation was
    labelled `last`. It must read the newest period.

No live network: every provider is a minimal stub.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.commodity._funcs import BGASFunction, BOILFunction


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ── BOIL: default path always carries the Brent−WTI pair ──────────────────


class _PairYfinance:
    """QUOTE provider keyed by symbol; OHLCV raises so history is honestly absent."""

    def __init__(self, quotes: dict[str, tuple[float, float]]) -> None:
        self.quotes = quotes
        self.quote_calls: list[str] = []

    async def fetch(self, request: Any) -> Any:
        if request.kind == DataKind.OHLCV:
            raise RuntimeError("fixture has no history")
        symbol = request.instrument.symbol if request.instrument else ""
        self.quote_calls.append(symbol)
        last, prev = self.quotes[symbol]
        return SimpleNamespace(
            last=last,
            close_prev=prev,
            high_24h=None,
            low_24h=None,
            open_24h=None,
            volume_24h=None,
            source="yfinance",
            timestamp=datetime.now(UTC),
        )


def test_boil_default_legs_render_brent_wti_spread() -> None:
    provider = _PairYfinance({"CL=F": (78.0, 77.5), "BZ=F": (82.0, 81.0)})
    fn = BOILFunction(deps=FunctionDeps(yfinance=provider))
    inst = Instrument(symbol="CL=F", asset_class=AssetClass.COMMODITY)
    result = _run(fn.execute(instrument=inst))
    data = result.data
    assert data["status"] == "ok"
    assert [row["symbol"] for row in data["rows"]] == ["CL=F", "BZ=F"]
    assert set(provider.quote_calls) == {"CL=F", "BZ=F"}, provider.quote_calls
    assert data["spread"] == pytest.approx(4.0)


def test_boil_requested_brent_leg_still_orders_first() -> None:
    provider = _PairYfinance({"CL=F": (78.0, 77.5), "BZ=F": (82.0, 81.0)})
    fn = BOILFunction(deps=FunctionDeps(yfinance=provider))
    inst = Instrument(symbol="BZ=F", asset_class=AssetClass.COMMODITY)
    result = _run(fn.execute(instrument=inst))
    assert [row["symbol"] for row in result.data["rows"]] == ["BZ=F", "CL=F"]
    assert result.data["spread"] == pytest.approx(4.0)


def test_boil_explicit_benchmark_selector_still_narrows() -> None:
    provider = _PairYfinance({"CL=F": (78.0, 77.5), "BZ=F": (82.0, 81.0)})
    fn = BOILFunction(deps=FunctionDeps(yfinance=provider))
    result = _run(fn.execute(benchmark="WTI"))
    assert [row["symbol"] for row in result.data["rows"]] == ["CL=F"]
    assert result.data["spread"] is None


def test_boil_lowercase_instrument_is_normalized() -> None:
    provider = _PairYfinance({"CL=F": (78.0, 77.5), "BZ=F": (82.0, 81.0)})
    fn = BOILFunction(deps=FunctionDeps(yfinance=provider))
    inst = Instrument(symbol="bz=f", asset_class=AssetClass.COMMODITY)
    result = _run(fn.execute(instrument=inst))
    assert [row["symbol"] for row in result.data["rows"]] == ["BZ=F", "CL=F"]


# ── BGAS: EIA tier normalized to the shared SpotRow shape ─────────────────


class _EiaSeries:
    """EIA-shaped adapter returning a prebuilt frame (or raising)."""

    def __init__(self, frame: Any = None, exc: Exception | None = None) -> None:
        self.frame = frame
        self.exc = exc

    async def fetch(self, request: Any) -> Any:
        if self.exc is not None:
            raise self.exc
        return self.frame


def _eia_frame(values: list[float], periods: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "value": values,
            "series": ["RNGWHHD"] * len(values),
            "units": ["$/MMBtu"] * len(values),
        },
        index=pd.to_datetime(periods),
    )


def test_bgas_eia_rows_normalised_to_spot_shape() -> None:
    # Deliberately DESC order — the normalizer must resolve the newest period.
    frame = _eia_frame([3.20, 3.10, 3.05], ["2026-09-10", "2026-09-09", "2026-09-08"])
    fn = BGASFunction(deps=FunctionDeps(eia=_EiaSeries(frame)))
    result = _run(fn.execute())
    data = result.data
    assert data["status"] == "ok"
    assert data["source_mode"] == "live_eia"
    assert result.sources == ["eia"]
    assert len(data["rows"]) == 1
    row = data["rows"][0]
    assert row["symbol"] == "HENRYHUB"
    assert row["last"] == pytest.approx(3.20)
    assert row["prev"] == pytest.approx(3.10)
    assert row["change_pct"] == pytest.approx((3.20 / 3.10 - 1) * 100)
    assert row["unit"] == "$/MMBtu"
    assert row["as_of"] == "2026-09-10"
    assert row["source_mode"] == "live_eia"
    # Ascending history for the pane chart; every point is a real print.
    assert [point["close"] for point in data["history"]] == [3.05, 3.10, 3.20]
    assert [point["date"] for point in data["history"]] == [
        "2026-09-08", "2026-09-09", "2026-09-10",
    ]


def test_bgas_eia_empty_series_falls_through_honestly() -> None:
    fn = BGASFunction(deps=FunctionDeps(eia=_EiaSeries(pd.DataFrame())))
    result = _run(fn.execute())
    assert result.data["status"] == "provider_unavailable"
    errors = result.metadata.get("provider_errors") or []
    assert any("no usable Henry Hub rows" in str(e) for e in errors), errors


def test_bgas_eia_failure_still_captured() -> None:
    fn = BGASFunction(deps=FunctionDeps(eia=_EiaSeries(exc=RuntimeError("boom"))))
    result = _run(fn.execute())
    assert result.data["status"] == "provider_unavailable"
    errors = result.metadata.get("provider_errors") or []
    assert any("eia" in str(e).lower() and "boom" in str(e) for e in errors), errors


# ── adjacent: EIA QUOTE reads the newest period ───────────────────────────


def test_eia_quote_uses_newest_period(monkeypatch: pytest.MonkeyPatch) -> None:
    from showme.engine.data_sources.commodity.eia_adapter import EIAAdapter

    adapter = EIAAdapter({})
    frame = _eia_frame([3.10, 3.20], ["2026-09-09", "2026-09-10"])

    async def fake_series_data(*args: Any, **kwargs: Any) -> pd.DataFrame:
        return frame

    monkeypatch.setattr(adapter, "series_data", fake_series_data)
    quote = _run(adapter.fetch(DataRequest(kind=DataKind.QUOTE, symbols=["HENRYHUB"])))
    assert quote.last == pytest.approx(3.20)


def test_eia_quote_missing_value_is_none_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    from showme.engine.data_sources.commodity.eia_adapter import EIAAdapter

    adapter = EIAAdapter({})
    frame = pd.DataFrame({"series": ["RNGWHHD"]}, index=pd.to_datetime(["2026-09-10"]))

    async def fake_series_data(*args: Any, **kwargs: Any) -> pd.DataFrame:
        return frame

    monkeypatch.setattr(adapter, "series_data", fake_series_data)
    quote = _run(adapter.fetch(DataRequest(kind=DataKind.QUOTE, symbols=["HENRYHUB"])))
    assert quote.last is None
