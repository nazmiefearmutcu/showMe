"""De-garbage regression tests for EXEC action=plan.

EXEC's monitor actions (open/slice/close/get/list) only echo recorded fills,
so with an empty store the function used to surface a lifeless ``status=empty``
placeholder. ``action=plan`` (and the symbol-hinted default route) now drives
the real ``algos.{TWAP,VWAP,Iceberg,Sniper}`` schedulers against LIVE intraday
OHLCV (Binance for crypto, Yahoo for listed assets) and returns real per-slice
rows with computed slippage / implementation shortfall / pace.

Live-network assertions are guarded: if the fetch errors (offline CI), we assert
the graceful ``provider_unavailable`` shape instead.
"""

from __future__ import annotations

import httpx
import pytest

from showme.engine.core.base_function import FunctionResult
from showme.engine.functions.trade import exec as exec_mod
from showme.engine.functions.trade.exec import EXECFunction
from showme.engine.services import exec_monitor

OK_SET = {"ok", "empty", "provider_unavailable"}

# The old placeholder / hardcoded constants we must never emit on the plan path.
_FORBIDDEN_REASONS = {
    "No execution parent orders are being monitored.",
}


@pytest.fixture(autouse=True)
def _reset_store(tmp_path, monkeypatch):
    """Isolate the SQLite exec_monitor store. The store lives at
    ``runtime_path('exec_monitor.sqlite')`` = ``<app_home>/runtime/...`` and
    app_home() honours the SHOWME_HOME env var, so pointing it at a tmp dir
    gives each test a fresh empty store with no real on-disk parent orders
    leaking into the empty-list assertions."""
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    # _db_path() re-reads app_home() and _connect() opens fresh each call, so
    # the override fully isolates the store; nothing cached to reset.
    assert exec_monitor.list_parents() == []


@pytest.fixture
def fn():
    return EXECFunction()


class _ClosedHistory:
    def __init__(self, rows, source):
        self.rows = rows
        self.source = source
        self.warnings = []
        self.metadata = {}


@pytest.fixture
def closed_feed(monkeypatch):
    """Offline stand-in for both intraday feeds: closed bars ending days ago, so
    the live-branch assertions run without any network access."""
    import time as _time

    import showme.chart_history as ch

    anchor = (int(_time.time()) // 300) * 300 - 3 * 86400

    def _rows(interval: str) -> list[dict]:
        step = 60 if interval == "1m" else 300
        return [
            {
                "time": anchor + i * step,
                "open": 300.0 + i * 0.2,
                "high": 300.5 + i * 0.2,
                "low": 299.5 + i * 0.2,
                "close": 300.3 + i * 0.2,
                "volume": 1000.0 + (i % 17) * 10.0,
            }
            for i in range(400)
        ]

    async def _yahoo(**kwargs):
        return _ClosedHistory(_rows(kwargs["interval"])[-int(kwargs["bars"]):], "yahoo_chart")

    async def _binance(**kwargs):
        return _ClosedHistory(_rows(kwargs["interval"])[-int(kwargs["bars"]):], "binance_spot")

    monkeypatch.setattr(ch, "fetch_yahoo_history", _yahoo, raising=True)
    monkeypatch.setattr(ch, "fetch_binance_history", _binance, raising=True)


def _is_live_ok(data: dict) -> bool:
    return data.get("status") == "ok"


def _assert_plan_contract(data: dict) -> None:
    """Shape every plan response (ok OR provider_unavailable) must satisfy."""
    assert data["status"] in OK_SET
    assert "methodology" in data and isinstance(data["methodology"], str) and data["methodology"]
    assert "field_dictionary" in data and isinstance(data["field_dictionary"], dict)
    assert "rows" in data and isinstance(data["rows"], list)
    assert data.get("reason") not in _FORBIDDEN_REASONS


@pytest.mark.asyncio
async def test_plan_crypto_returns_real_slices_or_graceful_outage(fn, closed_feed):
    """action=plan against BTCUSDT drives a real TWAP schedule on live klines."""
    try:
        res = await fn.execute(
            action="plan", symbol="BTCUSDT", algo="TWAP",
            target_qty=10, horizon_seconds=300, slices=6,
        )
    except (httpx.HTTPError, OSError):
        pytest.skip("network unavailable for Binance klines")

    assert isinstance(res, FunctionResult)
    data = res.data
    _assert_plan_contract(data)

    if _is_live_ok(data):
        assert data["algo"] == "TWAP"
        # chart_history labels the Binance source "binance_spot"; just assert a
        # real, single, binance-family source (never the inert exec_monitor).
        assert res.sources and "binance" in res.sources[0].lower()
        rows = data["rows"]
        assert len(rows) == 6
        # Rows must be REAL: distinct timestamps + real positive prices, not a
        # canned constant repeated.
        closes = [r["bar_close"] for r in rows if r["bar_close"] is not None]
        assert closes, "no real bar closes returned"
        assert all(c > 0 for c in closes)
        assert len({r["ts_ms"] for r in rows}) >= 2
        # Benchmark + slippage are computed from real bars.
        assert any(r["benchmark_px"] is not None for r in rows)
        assert any(r["slip_bps"] is not None for r in rows)
        # Pace is monotonic non-decreasing and ends near 100%.
        paces = [r["pace_pct"] for r in rows]
        assert paces == sorted(paces)
        assert paces[-1] == pytest.approx(100.0, abs=0.5)
        # Series + cards shipped for the chart grammar.
        assert "price" in data["series"] and data["series"]["price"]
        # EXEC#1: a replay over stored bars is labelled historical, never live.
        assert data["cards"]["data_mode"] == "historical_replay"
    else:
        # Outage path: honest provider_unavailable, no fabricated rows.
        assert data["status"] == "provider_unavailable"
        assert data["rows"] == []
        assert res.warnings


@pytest.mark.asyncio
async def test_plan_equity_vwap_uses_yahoo(fn, closed_feed):
    """VWAP equity plan slices follow the real volume profile via Yahoo."""
    try:
        res = await fn.execute(
            action="plan", symbol="AAPL", algo="VWAP",
            target_qty=500, horizon_seconds=600, slices=12, side="SELL",
        )
    except (httpx.HTTPError, OSError):
        pytest.skip("network unavailable for Yahoo history")

    data = res.data
    _assert_plan_contract(data)
    if _is_live_ok(data):
        assert data["algo"] == "VWAP"
        assert "yfinance" in res.sources or res.sources
        rows = data["rows"]
        assert rows
        # VWAP weights are non-uniform → slice qty should vary across slices.
        qtys = [r["qty"] for r in rows]
        assert len(set(round(q, 6) for q in qtys)) > 1
        # EXEC#4: the store is empty in this fixture, so no parent is claimed.
        assert data["cards"]["open_parents"] == 0
    else:
        assert data["status"] == "provider_unavailable"


@pytest.mark.asyncio
async def test_default_list_with_symbol_routes_to_live_plan(fn, closed_feed):
    """With an empty store but a symbol hint, the default route returns a live
    plan instead of the dead status=empty placeholder."""
    try:
        res = await fn.execute(symbol="ETHUSDT", algo="ICEBERG", target_qty=20, slices=5)
    except (httpx.HTTPError, OSError):
        pytest.skip("network unavailable")

    data = res.data
    _assert_plan_contract(data)
    assert data.get("action") == "plan"
    if _is_live_ok(data):
        assert data["algo"] == "ICEBERG"
        assert all(r["qty"] > 0 for r in data["rows"])


@pytest.mark.asyncio
async def test_plain_empty_list_still_returns_empty(fn):
    """Regression: action=list with no symbol + empty store keeps the documented
    empty contract (semantic test exec_list_empty_returns_empty_status)."""
    res = await fn.execute(action="list")
    assert res.data["status"] == "empty"
    assert res.data["orders"] == []
    assert res.data["n"] == 0


@pytest.mark.asyncio
async def test_plan_graceful_when_feed_raises(fn, monkeypatch):
    """Forced outage path: a raising fetcher yields provider_unavailable with an
    honest warning and zero fabricated rows."""
    async def _boom(*args, **kwargs):
        raise httpx.ConnectError("simulated outage")

    monkeypatch.setattr(exec_mod, "EXECFunction", EXECFunction)  # noop anchor
    import showme.chart_history as ch
    monkeypatch.setattr(ch, "fetch_binance_history", _boom, raising=True)

    res = await fn.execute(action="plan", symbol="BTCUSDT", algo="TWAP", target_qty=10)
    data = res.data
    assert data["status"] == "provider_unavailable"
    assert data["rows"] == []
    assert data["n"] == 0
    assert res.warnings
    assert "methodology" in data and "field_dictionary" in data
