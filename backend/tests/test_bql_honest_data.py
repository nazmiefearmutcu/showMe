"""BQL never returns synthetic market rows or silently substitutes a universe.

Audit findings BQL#1 (offline template prices labelled as provider data),
BQL#5 (live_query / start / end / interval wiring), BQL#6 (requested fields
missing from yfinance OHLCV dropped silently) and BQL#7 (limit max and the
BTCUSDT universe fallback). The network is never touched: yfinance is a fake.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.equity.yfinance_adapter import YFinanceAdapter
from showme.engine.functions.api import bql as bql_mod
from showme.manifest.registry import REGISTRY
from showme.manifest.seeds import load_seeds

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _FakeYf:
    """Records requests and returns a yfinance-shaped OHLCV frame."""

    def __init__(self, frame: pd.DataFrame | None = None) -> None:
        self.requests: list[Any] = []
        self.frame = frame if frame is not None else _ohlcv_frame()

    async def fetch(self, request: Any) -> pd.DataFrame:
        self.requests.append(request)
        return self.frame.copy()


def _ohlcv_frame() -> pd.DataFrame:
    idx = pd.DatetimeIndex(
        [pd.Timestamp("2026-11-05", tz="UTC"), pd.Timestamp("2026-11-06", tz="UTC")]
    )
    return pd.DataFrame(
        {
            "Open": [340.0, 341.0],
            "High": [343.0, 344.0],
            "Low": [339.0, 340.5],
            "Close": [342.0, 342.37],
            "Volume": [50_000_000, 48_000_000],
        },
        index=idx,
    )


def _run(fn: bql_mod.BQLFunction, **params: Any):
    return asyncio.run(fn.execute(**params))


def test_offline_mode_returns_no_fabricated_rows():
    """BQL#1: live=False must not return a hash-generated price series."""
    fn = bql_mod.BQLFunction(FunctionDeps(yfinance=_FakeYf()))
    res = _run(fn, instrument=AAPL, query="get(close, pe) for(['AAPL']) by(date)", live=False)
    assert res.data["rows"] == []
    assert res.data["status"] == "provider_unavailable"
    assert res.metadata["mode"] == "unavailable"
    assert "showme_query_model" not in res.sources
    assert "computed_model" not in repr(res.data)


def test_explicit_live_query_false_wins_over_injected_live_true():
    """BQL#5: the router injects live=True; an explicit live_query=False must stay offline."""
    yf = _FakeYf()
    fn = bql_mod.BQLFunction(FunctionDeps(yfinance=yf))
    res = _run(fn, instrument=AAPL, query="get(close) for(['AAPL'])", live=True, live_query=False)
    assert yf.requests == []  # no provider call was made
    assert res.data["rows"] == []
    assert res.metadata["mode"] == "unavailable"


def test_string_false_from_query_string_is_offline():
    """GET query strings arrive as text: live_query='false' must not count as truthy."""
    yf = _FakeYf()
    fn = bql_mod.BQLFunction(FunctionDeps(yfinance=yf))
    res = _run(fn, instrument=AAPL, query="get(close) for(['AAPL'])", live="true", live_query="false")
    assert yf.requests == []
    assert res.data["rows"] == []


def test_seed_interval_start_end_reach_the_provider():
    """BQL#5: interval/start/end declared as seed inputs are honoured by the handler."""
    yf = _FakeYf()
    fn = bql_mod.BQLFunction(FunctionDeps(yfinance=yf))
    _run(
        fn,
        instrument=AAPL,
        query="get(close) for(['AAPL'])",
        live=True,
        interval="1wk",
        start="2026-01-01",
        end="2026-02-01",
    )
    assert len(yf.requests) == 1
    req = yf.requests[0]
    assert req.interval == "1wk"
    assert req.start == pd.Timestamp("2026-01-01")
    assert req.end == pd.Timestamp("2026-02-01")


def test_requested_field_missing_from_ohlcv_is_reported_not_dropped():
    """BQL#6: pe is not a yfinance OHLCV column; the response must say so."""
    fn = bql_mod.BQLFunction(FunctionDeps(yfinance=_FakeYf()))
    res = _run(fn, instrument=AAPL, query="get(close, pe) for(['AAPL']) by(date)", live=True)
    assert res.data["rows"], "close is available so rows must still be returned"
    assert all("pe" not in row for row in res.data["rows"])
    assert any("pe" in w and "not provided" in w for w in res.warnings)
    assert any("pe" in w for w in res.data["warnings"])


def test_price_alias_maps_to_close_with_a_warning():
    """BQL#6: px_last / price are aliases for close in the template vocabulary; say so when used live."""
    fn = bql_mod.BQLFunction(FunctionDeps(yfinance=_FakeYf()))
    res = _run(fn, instrument=AAPL, query="get(px_last) for(['AAPL']) by(date)", live=True)
    assert res.data["rows"][0]["px_last"] == 342.0
    assert any("px_last" in w and "close" in w for w in res.warnings)


def test_missing_universe_needs_input_instead_of_btcusdt():
    """BQL#7: no for(), no symbol: never substitute BTCUSDT."""
    yf = _FakeYf()
    fn = bql_mod.BQLFunction(FunctionDeps(yfinance=yf))
    res = _run(fn, query="get(close)", live=True)
    assert yf.requests == []
    assert res.data["status"] == "input_required"
    assert res.data["rows"] == []
    assert "BTCUSDT" not in repr(res.data)


def test_symbol_beats_router_injected_peer_symbols_for_no_for_query():
    """BQL#5/#6 evidence: a pane symbol must not be replaced by the router's peer list."""
    yf = _FakeYf()
    fn = bql_mod.BQLFunction(FunctionDeps(yfinance=yf))
    res = _run(
        fn,
        instrument=AAPL,
        query="get(close) with(period='1mo') by(date)",
        live=True,
        symbol="AAPL",
        symbols=["AAPL", "MSFT", "GOOGL"],
        __explicit_symbol=True,
    )
    assert [r.instrument.symbol for r in yf.requests] == ["AAPL"]
    assert res.data["summary"]["symbols"] == 1


def test_limit_is_clamped_to_1000_and_not_advertised_by_the_seed():
    """BQL#7/#5: the engine clamps the row limit to 1000; the seed no longer declares
    a limit input the pane cannot send, so nothing advertises a larger cap."""
    load_seeds()
    manifest = REGISTRY.get("BQL")
    assert all(i.name != "limit" for i in manifest.inputs)
    rows = [{"symbol": "A", "date": str(i)} for i in range(1500)]
    assert len(bql_mod._limit_rows(rows, 10000)) == 1000


class _FakeChartClient:
    """Stands in for the Yahoo chart httpx client; records the query params sent."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def get(self, url: str, params: dict[str, Any] | None = None, **_: Any) -> httpx.Response:
        self.calls.append({"url": url, "params": dict(params or {})})
        body = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1767225600, 1767830400],  # 2026-01-01, 2026-01-08 UTC
                        "indicators": {
                            "quote": [
                                {
                                    "open": [340.0, 341.0],
                                    "high": [343.0, 344.0],
                                    "low": [339.0, 340.5],
                                    "close": [342.0, 342.37],
                                    "volume": [50_000_000, 48_000_000],
                                }
                            ]
                        },
                    }
                ]
            }
        }
        return httpx.Response(200, json=body, request=httpx.Request("GET", f"https://yahoo.test{url}"))


def _real_yahoo_adapter(monkeypatch: pytest.MonkeyPatch) -> tuple[YFinanceAdapter, _FakeChartClient]:
    """The real YFinanceAdapter with only its HTTP transport replaced."""
    adapter = YFinanceAdapter()
    chart = _FakeChartClient()

    async def _client_():
        return chart

    monkeypatch.setattr(adapter, "_chart_client_", _client_)
    return adapter, chart


def test_start_end_window_reaches_yahoo_request_without_default_period(monkeypatch: pytest.MonkeyPatch):
    """BQL#5 end-to-end: seed start/end/interval must become period1/period2 on the wire, not range=1mo."""
    adapter, chart = _real_yahoo_adapter(monkeypatch)
    fn = bql_mod.BQLFunction(FunctionDeps(yfinance=adapter))
    res = _run(
        fn,
        instrument=AAPL,
        query="get(close) for(['AAPL']) by(date)",
        live=True,
        interval="1wk",
        start="2026-01-01",
        end="2026-02-01",
    )
    assert len(chart.calls) == 1
    sent = chart.calls[0]["params"]
    assert sent["interval"] == "1wk"
    assert "range" not in sent
    assert sent["period1"] == int(pd.Timestamp("2026-01-01", tz="UTC").timestamp())
    assert sent["period2"] == int(pd.Timestamp("2026-02-01", tz="UTC").timestamp())
    assert res.metadata["mode"] == "live"
    assert res.data["rows"]


def test_with_start_end_in_dsl_also_skips_default_period(monkeypatch: pytest.MonkeyPatch):
    """BQL#5: the same window written in with(...) must not be widened to range=1mo."""
    adapter, chart = _real_yahoo_adapter(monkeypatch)
    fn = bql_mod.BQLFunction(FunctionDeps(yfinance=adapter))
    _run(
        fn,
        instrument=AAPL,
        query="get(close) for(['AAPL']) with(start='2026-01-01', end='2026-02-01', interval='1wk') by(date)",
        live=True,
    )
    sent = chart.calls[0]["params"]
    assert "range" not in sent
    assert "period1" in sent and "period2" in sent


def test_no_window_keeps_the_one_month_default_range(monkeypatch: pytest.MonkeyPatch):
    """BQL#5 control: without start/end the runtime 90-day default range still applies."""
    adapter, chart = _real_yahoo_adapter(monkeypatch)
    fn = bql_mod.BQLFunction(FunctionDeps(yfinance=adapter))
    _run(fn, instrument=AAPL, query="get(close) for(['AAPL']) by(date)", live=True)
    sent = chart.calls[0]["params"]
    assert sent["range"] == "90d"  # _apply_runtime_window default (days=90)
    assert "period1" not in sent
