"""Regression tests for the g10-trade group findings (FXGO#3, TCA#1, TSOX#1).

All network access is patched: the FX spot fetch goes through a fake
``requests.get`` and TCA runs on a seeded temp ledger with no live benchmark
(no fills -> no benchmark call).
"""

from __future__ import annotations

import asyncio

import pytest
import requests

from showme.bots.record import BotRecord, SignalEntry
from showme.bots.store import BotStore
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _offline_tca_benchmark(monkeypatch):
    """TCA never reaches yfinance from these tests: the intraday bars are empty."""
    from showme.engine.functions.trade.tca import TCAFunction

    async def _no_bars(self, symbol):
        return []

    monkeypatch.setattr(TCAFunction, "_yfinance_intraday", _no_bars)


def _mk_handler(klass, deps=None):
    try:
        return klass(deps=deps)
    except TypeError:
        return klass()


# ---------------------------------------------------------------------------
# FXGO#3 — yfinance-style pair tickers must keep their "=X" suffix.
# ---------------------------------------------------------------------------
def test_fxgo_to_yf_fx_keeps_equals_x_pair_ticker():
    from showme.engine.functions.trade._funcs import FXGOFunction

    assert FXGOFunction._to_yf_fx("GBPUSD=X") == "GBPUSD=X"
    assert FXGOFunction._to_yf_fx("gbpusd=x") == "GBPUSD=X"
    assert FXGOFunction._to_yf_fx("EURUSD") == "EURUSD=X"
    assert FXGOFunction._to_yf_fx("EUR/USD") == "EURUSD=X"
    assert FXGOFunction._to_yf_fx("=X") == ""


class _FakeChartResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _install_fake_yahoo(monkeypatch, served: dict[str, float], seen: list[str]):
    """Serve a chart payload only for tickers in ``served``; 404 otherwise."""

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.append(url)
        ticker = url.rsplit("/", 1)[-1]
        if ticker not in served:
            raise requests.HTTPError(f"404 Client Error for url: {url}")
        px = served[ticker]
        payload = {
            "chart": {
                "result": [{
                    "meta": {"regularMarketPrice": px, "previousClose": px - 0.001},
                    "indicators": {"quote": [{"close": [px - 0.001, px]}]},
                }],
            },
        }
        return _FakeChartResp(payload)

    monkeypatch.setattr(requests, "get", fake_get)


def test_fxgo_user_pair_with_equals_x_reaches_yahoo_and_returns_board(monkeypatch):
    from showme.engine.functions.trade._funcs import FXGOFunction

    seen: list[str] = []
    _install_fake_yahoo(monkeypatch, {"GBPUSD=X": 1.3356}, seen)

    h = _mk_handler(FXGOFunction, deps=None)
    res = _run(h.execute(pairs="GBPUSD=X"))
    data = res.data

    assert seen, "expected a Yahoo chart request"
    assert seen[0].endswith("/GBPUSD=X"), seen[0]
    assert "GBPUSDX" not in seen[0]
    assert data["status"] == "ok"
    assert data["data_mode"] == "live_exchange"
    assert len(data["rows"]) == 1
    row = data["rows"][0]
    assert row["pair"] == "GBPUSD=X"
    assert row["mid"] == pytest.approx(1.3356)
    assert row["ask"] >= row["bid"] > 0


# ---------------------------------------------------------------------------
# TCA#1 — unfilled orders must not be booked as fills.
# ---------------------------------------------------------------------------
class _StubBinance:
    async def klines(self, symbol, interval="5m", limit=288):
        return [{"high": 100.0, "low": 100.0, "close": 100.0, "volume": 10.0}
                for _ in range(5)]


def _make_tca(provider=None):
    from showme.engine.functions.trade.tca import TCAFunction

    return TCAFunction(deps=FunctionDeps(binance=provider or _StubBinance()))


def _use_temp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setattr(
        "showme.engine.services.order_history.runtime_path",
        lambda name: tmp_path / "runtime" / name,
    )
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)


def test_tca_unfilled_limit_order_is_not_booked_as_fill(tmp_path, monkeypatch):
    from showme.engine.services import order_history

    _use_temp_home(tmp_path, monkeypatch)
    # Submitted limit order, never filled: no fill metadata, no filled_qty.
    order_history.record_order(
        broker="ibkr", order_id="ord-77", symbol="AAPL", side="BUY",
        quantity=3.0, asset_class="EQUITY", price=190.0,
        type="LIMIT", status="submitted", metadata={},
    )

    res = _run(_make_tca().execute(symbol="AAPL", benchmark="VWAP"))
    data = res.data

    assert data["status"] == "empty", data
    assert data["rows"] == []
    assert data["summary"]["fill_count"] == 0


def test_tca_manual_order_with_recorded_fills_still_counts(tmp_path, monkeypatch):
    from showme.engine.services import order_history

    _use_temp_home(tmp_path, monkeypatch)
    order_history.record_order(
        broker="ibkr", order_id="ord-88", symbol="AAPL", side="BUY",
        quantity=3.0, asset_class="EQUITY", price=190.0,
        type="LIMIT", status="filled",
        metadata={"fills": [{"px": 191.0, "qty": 2.0}], "filled_qty": 2.0,
                  "arrival_price": 190.0},
    )

    res = _run(_make_tca().execute(symbol="AAPL", benchmark="ARRIVAL"))
    data = res.data

    assert data["status"] == "ok", data
    assert data["summary"]["fill_count"] == 1
    row = data["rows"][0]
    assert row["order_id"] == "ord-88"
    assert row["avg_fill_px"] == pytest.approx(191.0)
    assert row["quantity"] == pytest.approx(2.0)


def test_tca_bot_placed_order_without_fill_price_is_not_a_fill(tmp_path, monkeypatch):
    _use_temp_home(tmp_path, monkeypatch)
    store = BotStore.fresh()
    rec = BotRecord(
        strategy_id="s1", credential_id="c1", exchange_id="binance",
        symbol="BTCUSDT", timeframe="1h", mode="live", enabled=True,
        signal_log=[
            # placed, but the broker never reported a fill price
            SignalEntry(bar_index=0, bar_time="2026-06-01T00:00:00Z", kind="entry",
                        price=105.0, action="placed", order_id="r1",
                        fill_price=None, qty=2.0),
        ],
    )
    store.save(rec)

    res = _run(_make_tca().execute(symbol="BTCUSDT", benchmark="VWAP"))
    data = res.data

    assert data["status"] == "empty", data
    assert data["summary"]["fill_count"] == 0
    assert data["rows"] == []


# ---------------------------------------------------------------------------
# TSOX#1 — treasury futures are bond instruments, so TSOX accepts its defaults.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("symbol", ["ZN=F", "ZB=F", "ZF=F", "TU=F", "ZT=F", "TN=F", "UB=F"])
def test_treasury_futures_classify_as_bond(symbol):
    from showme import server

    assert server.default_asset_class_name(symbol) == "BOND"


def test_tsox_default_symbol_is_supported_asset_class():
    from showme import server
    from showme.engine.functions.trade._funcs import TSOXFunction

    ac_name = server.default_asset_class_name("ZN=F")
    instrument = Instrument(symbol="ZN=F", asset_class=AssetClass(ac_name))
    assert server._function_supports_instrument(TSOXFunction, instrument)


def test_treasury_mapping_does_not_capture_other_futures():
    from showme import server

    assert server.default_asset_class_name("GC=F") == "COMMODITY"
    assert server.default_asset_class_name("ZZ=F") == "EQUITY"


# ---------------------------------------------------------------------------
# TCA#1 (review follow-up) — the limit price must never stand in for the
# arrival benchmark or for a fill price.
# ---------------------------------------------------------------------------
def test_tca_manual_fill_without_arrival_price_has_no_limit_price_arrival(tmp_path, monkeypatch):
    from showme.engine.services import order_history

    _use_temp_home(tmp_path, monkeypatch)
    order_history.record_order(
        broker="binance", order_id="ord-99", symbol="BTCUSDT", side="BUY",
        quantity=2.0, asset_class="CRYPTO", price=190.0,
        type="LIMIT", status="filled",
        metadata={"fills": [{"px": 191.0, "qty": 2.0}], "filled_qty": 2.0},
    )

    res = _run(_make_tca().execute(symbol="BTCUSDT", benchmark="ARRIVAL"))
    data = res.data

    assert data["status"] == "ok", data
    row = data["rows"][0]
    assert row["avg_fill_px"] == pytest.approx(191.0)
    assert row["arrival_px"] is None
    assert row["is_bps"] is None


def test_services_tca_unfilled_limit_order_has_no_book_price_fill():
    from showme.engine.services import tca as services_tca

    out = services_tca.analyze_order({
        "id": 1, "order_id": "ord-77", "broker": "ibkr", "symbol": "AAPL",
        "side": "BUY", "quantity": 3.0, "price": 190.0, "status": "submitted",
        "metadata": {},
    })

    assert out["avg_fill"] is None
    assert out["arrival_price"] is None
    assert "implementation_shortfall_bps" not in out
