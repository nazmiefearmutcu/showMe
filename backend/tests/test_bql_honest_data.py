"""BQL never returns synthetic market rows or silently substitutes a universe.

Audit findings BQL#1 (offline template prices labelled as provider data),
BQL#5 (live_query / start / end / interval wiring), BQL#6 (requested fields
missing from yfinance OHLCV dropped silently) and BQL#7 (limit max and the
BTCUSDT universe fallback). The network is never touched: yfinance is a fake.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
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


def test_limit_seed_max_matches_the_engine_clamp():
    """BQL#7: the seed must not advertise a limit the engine clamps away."""
    load_seeds()
    manifest = REGISTRY.get("BQL")
    limit = next(i for i in manifest.inputs if i.name == "limit")
    assert limit.max == 1000.0
    rows = [{"symbol": "A", "date": str(i)} for i in range(1500)]
    assert len(bql_mod._limit_rows(rows, 10000)) == 1000
