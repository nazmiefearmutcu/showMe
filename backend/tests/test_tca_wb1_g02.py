"""Regression tests for the wb1-g02 TCA findings (TCA#2..#8, TCA-R1).

All network access is patched: benchmark fetchers are replaced by fakes, so
the suite never reaches Binance or Yahoo.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.bots.record import BotRecord, SignalEntry
from showme.bots.store import BotStore


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _use_temp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setattr(
        "showme.engine.services.order_history.runtime_path",
        lambda name: tmp_path / "runtime" / name,
    )
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# TCA#8 — the seed must describe the summary mean as count-weighted, which is
# what tca.py computes (sum / len), not notional-weighted.
# ---------------------------------------------------------------------------
def test_tca_seed_describes_avg_slippage_as_count_weighted():
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    desc = REGISTRY.get("TCA").field_dict["summary.avg_slippage_bps"].description.lower()
    assert "notional" not in desc, desc
    assert "count" in desc, desc


# ---------------------------------------------------------------------------
# TCA#7 — an FX pair such as EURUSD ends in "USD" but is not crypto, so its
# benchmark must not be requested from Binance.
# ---------------------------------------------------------------------------
class _CountingBinance:
    def __init__(self):
        self.calls: list[str] = []

    async def klines(self, symbol, interval="5m", limit=288, **kwargs):
        self.calls.append(symbol)
        return [{"high": 1.1, "low": 1.1, "close": 1.1, "volume": 10.0}]


def test_fx_pair_ending_in_usd_is_not_routed_to_binance(tmp_path, monkeypatch):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.trade.tca import TCAFunction

    _use_temp_home(tmp_path, monkeypatch)
    yf_calls: list[str] = []

    async def _fake_yf(self, symbol, *args, **kwargs):
        yf_calls.append(symbol)
        return []

    monkeypatch.setattr(TCAFunction, "_yfinance_intraday", _fake_yf)
    binance = _CountingBinance()
    _seed_fx = BotStore.fresh()
    _seed_fx.save(BotRecord(
        strategy_id="s1", credential_id="c1", exchange_id="binance",
        symbol="EURUSD", timeframe="1h", mode="live", enabled=True,
        signal_log=[SignalEntry(
            bar_index=0, bar_time="2026-06-01T00:00:00Z", kind="entry",
            price=1.10, action="placed", order_id="fx1",
            fill_price=1.11, qty=1000.0,
        )],
    ))

    res = _run(TCAFunction(deps=FunctionDeps(binance=binance)).execute(
        symbol="EURUSD", benchmark="VWAP"))

    assert binance.calls == [], binance.calls
    assert yf_calls == ["EURUSD"], yf_calls
    assert res.data["rows"][0]["benchmark_source"] == "arrival"


# ---------------------------------------------------------------------------
# TCA#6 — a fill with no benchmark (no live VWAP and no arrival price) has no
# slippage. It must not be plotted as a 0.0 bps execution in the series.
# ---------------------------------------------------------------------------
class _EmptyBinance:
    async def klines(self, symbol, interval="5m", limit=288, **kwargs):
        return []


def test_unbenchmarked_fill_is_not_plotted_as_zero_slippage(tmp_path, monkeypatch):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.trade.tca import TCAFunction
    from showme.engine.services import order_history

    _use_temp_home(tmp_path, monkeypatch)

    async def _no_bars(self, symbol, *args, **kwargs):
        return []

    monkeypatch.setattr(TCAFunction, "_yfinance_intraday", _no_bars)
    order_history.record_order(
        broker="binance", order_id="ord-200", symbol="BTCUSDT", side="BUY",
        quantity=2.0, asset_class="CRYPTO", price=190.0,
        type="LIMIT", status="filled",
        metadata={"fills": [{"px": 191.0, "qty": 2.0}], "filled_qty": 2.0},
    )

    res = _run(TCAFunction(deps=FunctionDeps(binance=_EmptyBinance())).execute(
        symbol="BTCUSDT", benchmark="VWAP"))
    data = res.data

    assert data["rows"][0]["slippage_bps"] is None
    assert data["series"] == [], data["series"]
    # No slippage was measured, so the summary means must be null, not 0.0.
    assert data["summary"]["avg_slippage_bps"] is None
    assert data["summary"]["worst_slippage_bps"] is None
    assert data["cards"]["avg_slippage_bps"] is None


# ---------------------------------------------------------------------------
# TCA#3 — benchmark=TWAP must compute a time-weighted average, not the VWAP
# series labelled TWAP. Two bars: typical 100 on volume 1000, typical 200 on
# volume 1. VWAP is ~100.1, TWAP (equal-weight bars) is 150.0.
# ---------------------------------------------------------------------------
class _TwoBarBinance:
    async def klines(self, symbol, interval="5m", limit=288, **kwargs):
        return [
            {"high": 100.0, "low": 100.0, "close": 100.0, "volume": 1000.0},
            {"high": 200.0, "low": 200.0, "close": 200.0, "volume": 1.0},
        ]


def _seed_btc_fill(fill_px=160.0, signal_px=150.0):
    BotStore.fresh().save(BotRecord(
        strategy_id="s1", credential_id="c1", exchange_id="binance",
        symbol="BTCUSDT", timeframe="1h", mode="live", enabled=True,
        signal_log=[SignalEntry(
            bar_index=0, bar_time="2026-06-01T00:00:00Z", kind="entry",
            price=signal_px, action="placed", order_id="t1",
            fill_price=fill_px, qty=1.0,
        )],
    ))


def test_twap_benchmark_is_time_weighted_not_vwap(tmp_path, monkeypatch):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.trade.tca import TCAFunction

    _use_temp_home(tmp_path, monkeypatch)
    _seed_btc_fill()

    fn = TCAFunction(deps=FunctionDeps(binance=_TwoBarBinance()))
    twap = _run(fn.execute(symbol="BTCUSDT", benchmark="TWAP")).data["rows"][0]
    vwap = _run(fn.execute(symbol="BTCUSDT", benchmark="VWAP")).data["rows"][0]

    assert twap["benchmark_px"] == pytest.approx(150.0)
    assert vwap["benchmark_px"] == pytest.approx(100.0999, rel=1e-4)


def test_unknown_benchmark_is_input_error_not_relabelled(tmp_path, monkeypatch):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.trade.tca import TCAFunction

    _use_temp_home(tmp_path, monkeypatch)
    _seed_btc_fill()
    res = _run(TCAFunction(deps=FunctionDeps(binance=_TwoBarBinance())).execute(
        symbol="BTCUSDT", benchmark="MIDPOINT"))
    assert res.data["status"] == "input_error"
    assert res.data["rows"] == []


# ---------------------------------------------------------------------------
# TCA#2 — the benchmark must be the VWAP of the FILL's session, not a 5-day
# window ending today. A fill from 2026-09-11 must request that day's bars.
# ---------------------------------------------------------------------------
class _SessionBinance:
    """Serves one bar per UTC day, keyed on startTime, and records requests."""

    def __init__(self, bars_by_day: dict[str, float]):
        self.bars_by_day = bars_by_day
        self.requests: list[dict] = []

    async def klines(self, symbol, interval="5m", limit=288, start_ms=None, end_ms=None, **kwargs):
        from datetime import datetime, timezone

        self.requests.append({"start_ms": start_ms, "end_ms": end_ms})
        if start_ms is None:
            return []
        day = datetime.fromtimestamp(start_ms / 1000, timezone.utc).date().isoformat()
        px = self.bars_by_day.get(day)
        if px is None:
            return []
        return [{"high": px, "low": px, "close": px, "volume": 5.0}]


def _seed_dated_btc_fill(filled_at: str | None, fill_px=160.0, signal_px=150.0):
    kwargs = {}
    if filled_at is not None:
        kwargs["bar_close_time"] = filled_at
    BotStore.fresh().save(BotRecord(
        strategy_id="s1", credential_id="c1", exchange_id="binance",
        symbol="BTCUSDT", timeframe="1h", mode="live", enabled=True,
        signal_log=[SignalEntry(
            bar_index=0, bar_time="2026-09-11T15:55:00Z", kind="entry",
            price=signal_px, action="placed", order_id="s2",
            fill_price=fill_px, qty=1.0, **kwargs,
        )],
    ))


def test_benchmark_is_the_fill_session_not_a_five_day_window(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.trade.tca import TCAFunction

    _use_temp_home(tmp_path, monkeypatch)
    _seed_dated_btc_fill("2026-09-11T16:00:05Z")
    binance = _SessionBinance({"2026-09-11": 120.0, "2026-11-06": 300.0})

    res = _run(TCAFunction(deps=FunctionDeps(binance=binance)).execute(
        symbol="BTCUSDT", benchmark="VWAP"))

    day_start = int(datetime(2026, 9, 11, tzinfo=timezone.utc).timestamp() * 1000)
    assert binance.requests, "benchmark was never requested"
    assert binance.requests[0]["start_ms"] == day_start, binance.requests
    assert res.data["rows"][0]["benchmark_px"] == pytest.approx(120.0)


def test_fill_older_than_intraday_retention_does_not_use_other_session(tmp_path, monkeypatch):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.trade.tca import TCAFunction

    _use_temp_home(tmp_path, monkeypatch)
    calls: list[str] = []

    async def _fake_yf(self, symbol, *args, **kwargs):
        calls.append(symbol)
        return [{"high": 999.0, "low": 999.0, "close": 999.0, "volume": 1.0}]

    monkeypatch.setattr(TCAFunction, "_yfinance_intraday", _fake_yf)
    BotStore.fresh().save(BotRecord(
        strategy_id="s1", credential_id="c1", exchange_id="ibkr",
        symbol="AAPL", timeframe="1h", mode="live", enabled=True,
        signal_log=[SignalEntry(
            bar_index=0, bar_time="2026-09-11T15:55:00Z", kind="entry",
            price=190.0, action="placed", order_id="eq1",
            fill_price=191.0, qty=2.0, bar_close_time="2026-06-01T15:00:00Z",
        )],
    ))

    res = _run(TCAFunction(deps=FunctionDeps()).execute(symbol="AAPL", benchmark="VWAP"))
    row = res.data["rows"][0]

    assert calls == [], "a 2026-06 session must not be served from another session's bars"
    assert row["benchmark_source"] == "arrival"
    assert row["benchmark_px"] == pytest.approx(190.0)
    assert any("AAPL" in w for w in res.warnings), res.warnings


def test_fill_without_timestamp_has_no_session_benchmark(tmp_path, monkeypatch):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.trade.tca import TCAFunction

    _use_temp_home(tmp_path, monkeypatch)
    binance = _SessionBinance({})
    BotStore.fresh().save(BotRecord(
        strategy_id="s1", credential_id="c1", exchange_id="binance",
        symbol="BTCUSDT", timeframe="1h", mode="live", enabled=True,
        signal_log=[SignalEntry(
            bar_index=0, bar_time="", kind="entry", price=150.0, action="placed",
            order_id="nt1", fill_price=160.0, qty=1.0, timestamp="",
        )],
    ))

    res = _run(TCAFunction(deps=FunctionDeps(binance=binance)).execute(
        symbol="BTCUSDT", benchmark="VWAP"))
    assert binance.requests == [], "no timestamp, so no session may be requested"
    assert res.data["rows"][0]["benchmark_source"] == "arrival"


class _RawKlineBinance:
    """Returns Binance's raw kline matrix (string fields), as BinanceProvider does."""

    async def klines(self, symbol, interval="5m", limit=288, start_ms=None, end_ms=None):
        row = [1786000000000, "100.0", "110.0", "90.0", "100.0", "10.0",
               1786000299999, "0", 1, "0", "0", "0"]
        return [row]


def test_raw_binance_kline_rows_feed_the_benchmark(tmp_path, monkeypatch):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.trade.tca import TCAFunction

    _use_temp_home(tmp_path, monkeypatch)
    _seed_dated_btc_fill("2026-09-11T16:00:05Z")
    res = _run(TCAFunction(deps=FunctionDeps(binance=_RawKlineBinance())).execute(
        symbol="BTCUSDT", benchmark="VWAP"))
    row = res.data["rows"][0]
    # typical price = (110 + 90 + 100) / 3 = 100
    assert row["benchmark_px"] == pytest.approx(100.0)
    assert row["benchmark_source"] == "binance"


# ---------------------------------------------------------------------------
# TCA-R1 — orders that never produced a broker-confirmed fill are excluded, and
# the exclusion must be visible (count + warning), not silent.
# ---------------------------------------------------------------------------
def test_excluded_unfilled_orders_are_counted_and_warned(tmp_path, monkeypatch):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.trade.tca import TCAFunction
    from showme.engine.services import order_history

    _use_temp_home(tmp_path, monkeypatch)
    # manual order that never executed
    order_history.record_order(
        broker="binance", order_id="ord-300", symbol="BTCUSDT", side="BUY",
        quantity=1.0, asset_class="CRYPTO", price=190.0,
        type="LIMIT", status="submitted", metadata={},
    )
    BotStore.fresh().save(BotRecord(
        strategy_id="s1", credential_id="c1", exchange_id="binance",
        symbol="BTCUSDT", timeframe="1h", mode="live", enabled=True,
        signal_log=[
            SignalEntry(bar_index=0, bar_time="2026-09-11T00:00:00Z", kind="entry",
                        price=150.0, action="placed", order_id="x1",
                        fill_price=None, qty=1.0),          # placed, no fill price
            SignalEntry(bar_index=1, bar_time="2026-09-11T01:00:00Z", kind="exit",
                        price=150.0, action="placed", order_id="x2",
                        fill_price=151.0, qty=None),        # no executed size
            SignalEntry(bar_index=2, bar_time="2026-09-11T02:00:00Z", kind="entry",
                        price=150.0, action="shadow", order_id="x3",
                        fill_price=None, qty=1.0),          # simulation, not an order
            SignalEntry(bar_index=3, bar_time="2026-09-11T03:00:00Z", kind="entry",
                        price=150.0, action="placed", order_id="x4",
                        fill_price=152.0, qty=2.0),         # real fill
        ],
    ))

    res = _run(TCAFunction(deps=FunctionDeps(binance=_TwoBarBinance())).execute(
        symbol="BTCUSDT", benchmark="VWAP"))
    data = res.data

    assert data["summary"]["fill_count"] == 1
    assert data["excluded_orders"]["total"] == 3, data["excluded_orders"]
    assert data["excluded_orders"]["reasons"] == {
        "unfilled_no_execution": 1, "no_fill_price": 1, "no_positive_qty": 1,
    }, data["excluded_orders"]
    assert any("Excluded 3" in w for w in res.warnings), res.warnings


# ---------------------------------------------------------------------------
# TCA#4 — the seed's `window` and `transactions` inputs must be honoured.
# ---------------------------------------------------------------------------
def test_window_excludes_fills_older_than_the_lookback(tmp_path, monkeypatch):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.trade.tca import TCAFunction

    _use_temp_home(tmp_path, monkeypatch)
    BotStore.fresh().save(BotRecord(
        strategy_id="s1", credential_id="c1", exchange_id="binance",
        symbol="BTCUSDT", timeframe="1h", mode="live", enabled=True,
        signal_log=[
            SignalEntry(bar_index=0, bar_time="2026-06-01T00:00:00Z", kind="entry",
                        price=150.0, action="placed", order_id="old1",
                        fill_price=160.0, qty=1.0, bar_close_time="2026-06-01T00:00:00Z"),
            SignalEntry(bar_index=1, bar_time="2026-06-01T01:00:00Z", kind="entry",
                        price=150.0, action="placed", order_id="new1",
                        fill_price=160.0, qty=1.0),  # timestamp = now
        ],
    ))
    fn = TCAFunction(deps=FunctionDeps(binance=_TwoBarBinance()))

    windowed = _run(fn.execute(symbol="BTCUSDT", benchmark="VWAP", window="1M")).data
    assert [r["order_id"] for r in windowed["rows"]] == ["new1"]
    assert windowed["excluded_orders"]["reasons"] == {"outside_window": 1}

    everything = _run(fn.execute(symbol="BTCUSDT", benchmark="VWAP", window="ALL")).data
    assert everything["summary"]["fill_count"] == 2


def test_inline_transactions_replace_the_local_store(tmp_path, monkeypatch):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.trade.tca import TCAFunction
    from showme.engine.services import order_history

    _use_temp_home(tmp_path, monkeypatch)

    async def _no_bars(self, symbol, *args, **kwargs):
        return []

    monkeypatch.setattr(TCAFunction, "_yfinance_intraday", _no_bars)
    order_history.record_order(
        broker="ibkr", order_id="ord-500", symbol="AAPL", side="BUY",
        quantity=3.0, asset_class="EQUITY", price=190.0, type="LIMIT",
        status="filled",
        metadata={"fills": [{"px": 191.0, "qty": 3.0}], "filled_qty": 3.0,
                  "arrival_price": 190.0},
    )
    blotter = (
        "symbol,side,quantity,avg_fill_px,arrival_px,filled_at\n"
        "AAPL,BUY,10,190.5,190.0,2026-11-06T15:00:00Z\n"
        "AAPL,SELL,5,0,190.0,2026-11-06T15:05:00Z\n"
    )
    res = _run(TCAFunction(deps=FunctionDeps()).execute(
        transactions=blotter, benchmark="ARRIVAL"))
    data = res.data

    assert [r["order_id"] for r in data["rows"]] == ["tx-1"], data["rows"]
    assert data["rows"][0]["quantity"] == pytest.approx(10.0)
    assert data["excluded_orders"]["reasons"] == {"no_fill_price": 1}
    assert "inline_transactions" in res.sources
    assert "order_history" not in res.sources


def test_json_transactions_and_invalid_transactions(tmp_path, monkeypatch):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.trade.tca import TCAFunction

    _use_temp_home(tmp_path, monkeypatch)
    fn = TCAFunction(deps=FunctionDeps(binance=_TwoBarBinance()))

    ok = _run(fn.execute(
        transactions='[{"symbol":"BTCUSDT","side":"buy","quantity":2,'
                     '"avg_fill_px":101,"order_id":"j1"}]',
        benchmark="VWAP")).data
    assert [r["order_id"] for r in ok["rows"]] == ["j1"]
    assert ok["rows"][0]["side"] == "BUY"

    bad = _run(fn.execute(transactions='[{"symbol": ', benchmark="VWAP")).data
    assert bad["status"] == "input_error"
    assert "transactions" in bad["reason"].lower()
