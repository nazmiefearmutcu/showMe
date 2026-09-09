"""KAOS engine-kind delegate — routing, isolation, honesty.

Proves, at the runner level:
* spec-rule bots keep the EXACT pre-campaign path (the KAOS adapter is
  never consulted; evaluate_last_bar is never consulted for kaos bots);
* KAOS decisions flow through the EXISTING dispatch (shadow provenance,
  shared _submit_live_and_audit for live orders, closed-trade pairing);
* per-venue error isolation (one venue failing never blocks the other);
* honest lane labels ("PAPER (no Alpaca keys)" — never fake bars).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from showme.bots.kaos.adapter import KaosDecision
from showme.bots.record import BotRecord, SignalEntry, VenueSpec
from showme.bots.runner import BotRunner
from showme.bots.store import BotStore

CRYPTO_VENUE = {
    "id": "crypto", "exchange_id": "binanceusdm", "market": "crypto-futures",
    "symbols": ["BTC/USDT:USDT", "ETH/USDT:USDT"], "risk_profile": "crypto",
}
NASDAQ_VENUE = {
    "id": "nasdaq", "exchange_id": "alpaca", "market": "us-equities",
    "symbols": ["AAPL", "MSFT"], "risk_profile": "equity",
}


@pytest.fixture(autouse=True)
def _isolate_factory():
    from showme.brokers import factory as factory_mod
    snap_reg = dict(factory_mod._REGISTRY)
    snap_dyn = dict(factory_mod._DYNAMIC)
    snap_live = dict(factory_mod._LIVE)
    yield
    factory_mod._REGISTRY.clear()
    factory_mod._REGISTRY.update(snap_reg)
    factory_mod._DYNAMIC.clear()
    factory_mod._DYNAMIC.update(snap_dyn)
    factory_mod._LIVE.clear()
    factory_mod._LIVE.update(snap_live)


@pytest.fixture
def store(tmp_path) -> BotStore:
    return BotStore(tmp_path / "bots")


def _save_sizing_spec(tmp_path, monkeypatch, sizing_kind="fixed_quote"):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    from showme.strategies.spec import Position, StrategySpec
    from showme.strategies.store import StrategyStore
    spec = StrategyStore.fresh().save(StrategySpec(
        name="kaos-sizing-host",
        position=Position(sizing_kind=sizing_kind, sizing_value=100),
    ))
    return spec.id


def _kaos_record(sid: str, venues: list[dict], **kw) -> BotRecord:
    base = {
        "strategy_id": sid, "credential_id": "kc1",
        "exchange_id": "binanceusdm", "symbol": "BTC/USDT",
        "timeframe": "15m", "tick_interval_seconds": 60,
        "mode": "shadow", "enabled": True, "engine": "kaos",
        "venues": [VenueSpec(**v) for v in venues],
    }
    base.update(kw)
    return BotRecord(**base)


def _df(symbol_close: float = 100.0, n: int = 60) -> pd.DataFrame:
    idx = pd.date_range("2026-09-09", periods=n, freq="15min")
    closes = [symbol_close] * n
    return pd.DataFrame({
        "open": closes, "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes], "close": closes,
        "volume": [10.0] * n,
    }, index=idx)


def _decision(symbol: str, venue_id: str, kind: str = "entry",
              side: str = "long", price: float = 100.0,
              bar_time: str = "2026-09-09 01:00:00+00:00") -> KaosDecision:
    return KaosDecision(
        symbol=symbol, venue_id=venue_id,
        market="crypto-futures" if venue_id == "crypto" else "us-equities",
        risk_profile="crypto" if venue_id == "crypto" else "equity",
        kind=kind, side=side, price=price, bar_index=59, bar_time=bar_time,
        reason="consensus 0.62 [trend] (ema+ macd+ rsi+ bb+)",
        strength=0.62, sigma=0.002 if kind == "entry" else None,
        stop_loss_pct=4.0 if kind == "entry" else None,
        take_profit_pct=0.8 if kind == "entry" else None,
        regime="trend",
    )


def _register_broker(exchange_id: str, credential_id: str = "kc1"):
    from showme.brokers import factory as factory_mod
    broker = MagicMock()
    broker.name = f"ccxt:{exchange_id}:{credential_id}"
    broker._ex = MagicMock()
    broker.submit_order = AsyncMock(return_value=MagicMock(
        id="order-kaos-1", filled_quantity=0.5, quantity=0.5,
        avg_fill_price=100.0,
    ))
    factory_mod._REGISTRY[f"{exchange_id}:{credential_id}"] = lambda: broker
    factory_mod._DYNAMIC[credential_id] = f"{exchange_id}:{credential_id}"
    return broker


def _patch_bars(monkeypatch, bars_by_symbol: dict[str, pd.DataFrame]):
    async def _fake_fetch(broker, symbol, timeframe="15m", limit=200):
        df = bars_by_symbol.get(symbol)
        if df is None:
            from showme.bots.ohlcv import BotRunnerError
            raise BotRunnerError(f"no bars for {symbol}")
        return df
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=_fake_fetch))


def _patch_decisions(monkeypatch, decisions: list[KaosDecision]):
    """Crafted adapter output: routing is under test, not signal truth."""
    def _fake_evaluate(bars_by_symbol, venue, cfg, *, in_position_by_symbol=None):
        want = set(getattr(venue, "symbols", []))
        return [d for d in decisions if d.symbol in want]
    monkeypatch.setattr("showme.bots.kaos.adapter.evaluate", _fake_evaluate)


# ---- path isolation ---------------------------------------------------------


@pytest.mark.asyncio
async def test_spec_bot_never_consults_kaos_adapter(monkeypatch, tmp_path, store):
    """Zero regression pin: the spec path is byte-for-byte the old path."""
    sid = _save_sizing_spec(tmp_path, monkeypatch)
    from showme.strategies.spec import Rule
    from showme.strategies.store import StrategyStore
    sstore = StrategyStore.fresh()
    spec = sstore.get(sid)
    spec = spec.model_copy(update={
        "timeframe": "15m",  # match the bot timeframe (H-RT-6 drift guard)
        "entry_rules": [Rule(kind="crosses_above", left="close",
                             right="literal:99")],
    })
    sstore.save(spec)

    broker = _register_broker("binanceusdm")
    rec = store.save(BotRecord(
        strategy_id=sid, credential_id="kc1", exchange_id="binanceusdm",
        symbol="BTC/USDT", enabled=True, mode="shadow",
        timeframe="15m", tick_interval_seconds=60,
    ))
    # Spec fixture: close crosses_above 99 exactly on the LAST bar
    # (same shape the baseline runner tests use).
    idx = pd.date_range("2026-09-09", periods=60, freq="15min")
    closes = [98.0] * 59 + [100.0]
    cross_df = pd.DataFrame({
        "open": closes, "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes], "close": closes,
        "volume": [10.0] * 60,
    }, index=idx)
    _patch_bars(monkeypatch, {"BTC/USDT": cross_df})

    def _boom(*a, **kw):
        raise AssertionError("kaos adapter must not be called for spec bots")
    monkeypatch.setattr("showme.bots.kaos.adapter.evaluate", _boom)

    entry = await BotRunner().tick(rec.id, store)
    assert entry is not None and entry.action == "shadow"
    assert entry.symbol is None  # spec provenance: record symbol, not per-entry
    broker.submit_order.assert_not_called()


@pytest.mark.asyncio
async def test_kaos_bot_never_consults_evaluate_last_bar(monkeypatch, tmp_path, store):
    sid = _save_sizing_spec(tmp_path, monkeypatch)
    rec = store.save(_kaos_record(sid, [CRYPTO_VENUE]))
    _register_broker("binanceusdm")
    _patch_bars(monkeypatch, {s: _df() for s in CRYPTO_VENUE["symbols"]})
    _patch_decisions(monkeypatch, [
        _decision("BTC/USDT:USDT", "crypto"),
    ])

    def _boom(*a, **kw):
        raise AssertionError("spec evaluator must not run for kaos bots")
    monkeypatch.setattr("showme.strategies.evaluate.evaluate_last_bar", _boom)

    entry = await BotRunner().tick(rec.id, store)
    assert entry is not None
    assert entry.symbol == "BTC/USDT:USDT"


# ---- shadow routing + multi-venue -------------------------------------------


@pytest.mark.asyncio
async def test_kaos_shadow_entries_carry_provenance(monkeypatch, tmp_path, store):
    sid = _save_sizing_spec(tmp_path, monkeypatch)
    rec = store.save(_kaos_record(sid, [CRYPTO_VENUE]))
    _register_broker("binanceusdm")
    _patch_bars(monkeypatch, {s: _df() for s in CRYPTO_VENUE["symbols"]})
    _patch_decisions(monkeypatch, [
        _decision("BTC/USDT:USDT", "crypto", side="long"),
        _decision("ETH/USDT:USDT", "crypto", side="short"),
    ])

    entry = await BotRunner().tick(rec.id, store)
    reloaded = store.get(rec.id)
    assert len(reloaded.signal_log) == 2
    by_symbol = {e.symbol: e for e in reloaded.signal_log}
    assert set(by_symbol) == {"BTC/USDT:USDT", "ETH/USDT:USDT"}
    assert all(e.action == "shadow" for e in reloaded.signal_log)
    assert all(e.venue_id == "crypto" for e in reloaded.signal_log)
    assert by_symbol["BTC/USDT:USDT"].side == "long"
    assert by_symbol["ETH/USDT:USDT"].side == "short"
    assert by_symbol["BTC/USDT:USDT"].qty is not None
    assert "consensus" in by_symbol["BTC/USDT:USDT"].reason
    assert entry is reloaded.signal_log[-1] or entry.symbol is not None


@pytest.mark.asyncio
async def test_kaos_exit_pairs_closed_trade_per_symbol(monkeypatch, tmp_path, store):
    sid = _save_sizing_spec(tmp_path, monkeypatch)
    held = SignalEntry(
        bar_index=50, bar_time="2026-09-09 00:00:00+00:00", kind="entry",
        price=100.0, action="shadow", qty=0.5, symbol="BTC/USDT:USDT",
        venue_id="crypto", side="long",
    )
    rec = _kaos_record(sid, [CRYPTO_VENUE])
    rec = rec.append_signal(held)
    rec.enabled = True
    store.save(rec)

    _register_broker("binanceusdm")
    _patch_bars(monkeypatch, {s: _df() for s in CRYPTO_VENUE["symbols"]})
    _patch_decisions(monkeypatch, [
        _decision("BTC/USDT:USDT", "crypto", kind="exit", side="long",
                  price=101.0, bar_time="2026-09-09 01:00:00+00:00"),
    ])

    await BotRunner().tick(rec.id, store)
    reloaded = store.get(rec.id)
    assert reloaded.signal_log[-1].kind == "exit"
    assert len(reloaded.closed_trades_log) == 1
    trade = reloaded.closed_trades_log[-1]
    assert trade.side == "long"
    assert trade.entry_price == 100.0
    assert trade.exit_price == 101.0
    assert trade.net_pnl == pytest.approx(trade.pnl - trade.commission_paid)
    assert trade.exit_reason.startswith("consensus")


@pytest.mark.asyncio
async def test_kaos_multi_venue_routing_and_isolation(monkeypatch, tmp_path, store):
    """Crypto venue live-decides; nasdaq venue has NO broker → honest PAPER
    label, no fake evaluation, and the crypto lane is never blocked."""
    sid = _save_sizing_spec(tmp_path, monkeypatch)
    rec = store.save(_kaos_record(sid, [CRYPTO_VENUE, NASDAQ_VENUE]))
    _register_broker("binanceusdm")  # alpaca broker deliberately ABSENT
    _patch_bars(monkeypatch, {s: _df() for s in CRYPTO_VENUE["symbols"]})
    _patch_decisions(monkeypatch, [
        _decision("BTC/USDT:USDT", "crypto"),
    ])

    runner = BotRunner()
    await runner.tick(rec.id, store)
    reloaded = store.get(rec.id)
    symbols = [e.symbol for e in reloaded.signal_log]
    assert "BTC/USDT:USDT" in symbols          # crypto lane routed
    assert "AAPL" not in symbols and "MSFT" not in symbols

    rows = {r["venue_id"]: r for r in runner.kaos_lane_rows(
        rec.id, [CRYPTO_VENUE, NASDAQ_VENUE])}
    assert rows["crypto"]["lane_status"] == "shadow"
    assert rows["crypto"]["decisions"] == 1
    assert rows["nasdaq"]["lane_status"] == "PAPER (no Alpaca keys)"
    assert rows["nasdaq"]["decisions"] == 0
    assert rows["nasdaq"]["last_eval"] is None


@pytest.mark.asyncio
async def test_kaos_crypto_lane_bars_unavailable_honest(monkeypatch, tmp_path, store):
    sid = _save_sizing_spec(tmp_path, monkeypatch)
    rec = store.save(_kaos_record(sid, [CRYPTO_VENUE]))
    _register_broker("binanceusdm")
    _patch_bars(monkeypatch, {})  # broker present, every fetch fails
    _patch_decisions(monkeypatch, [])

    runner = BotRunner()
    await runner.tick(rec.id, store)
    rows = runner.kaos_lane_rows(rec.id, [CRYPTO_VENUE])
    assert rows[0]["lane_status"] == "bars unavailable"
    assert store.get(rec.id).signal_log == []


@pytest.mark.asyncio
async def test_kaos_venue_evaluation_error_isolated(monkeypatch, tmp_path, store):
    """One venue's adapter blowing up leaves an honest error row and the
    other venue still routes."""
    sid = _save_sizing_spec(tmp_path, monkeypatch)
    other = dict(NASDAQ_VENUE)
    other["id"] = "crypto2"
    other["exchange_id"] = "binanceusdm"
    rec = store.save(_kaos_record(sid, [CRYPTO_VENUE, other]))
    _register_broker("binanceusdm")
    _patch_bars(monkeypatch, {
        s: _df() for s in
        CRYPTO_VENUE["symbols"] + other["symbols"]
    })

    calls = {"n": 0}
    def _flaky(bars_by_symbol, venue, cfg, *, in_position_by_symbol=None):
        calls["n"] += 1
        if getattr(venue, "id", "") == "crypto":
            raise RuntimeError("venue exploded")
        return [_decision("AAPL", "crypto2", bar_time="2026-09-09 01:00:00+00:00")]
    monkeypatch.setattr("showme.bots.kaos.adapter.evaluate", _flaky)

    runner = BotRunner()
    await runner.tick(rec.id, store)
    assert calls["n"] == 2  # both venues attempted; first crashed, second ran
    rows = {r["venue_id"]: r for r in runner.kaos_lane_rows(
        rec.id, [CRYPTO_VENUE, other])}
    assert rows["crypto"]["lane_status"] == "evaluation error"
    assert rows["crypto2"]["decisions"] == 1
    symbols = [e.symbol for e in store.get(rec.id).signal_log]
    assert "AAPL" in symbols


@pytest.mark.asyncio
async def test_kaos_same_bar_dedup(monkeypatch, tmp_path, store):
    sid = _save_sizing_spec(tmp_path, monkeypatch)
    rec = store.save(_kaos_record(sid, [CRYPTO_VENUE]))
    _register_broker("binanceusdm")
    _patch_bars(monkeypatch, {s: _df() for s in CRYPTO_VENUE["symbols"]})
    _patch_decisions(monkeypatch, [
        _decision("BTC/USDT:USDT", "crypto", bar_time="2026-09-09 01:00:00+00:00"),
    ])

    runner = BotRunner()
    first = await runner.tick(rec.id, store)
    assert first is not None
    second = await runner.tick(rec.id, store)
    assert second is None
    assert len(store.get(rec.id).signal_log) == 1


# ---- live dispatch through the SHARED path ----------------------------------


@pytest.mark.asyncio
async def test_kaos_live_dispatch_uses_shared_submit(monkeypatch, tmp_path, store):
    """Live KAOS submits through _dispatch_live_order (same guards/spec
    sizing), auditing the fill exactly like a spec bot."""
    sid = _save_sizing_spec(tmp_path, monkeypatch)
    rec = store.save(_kaos_record(sid, [CRYPTO_VENUE], mode="live"))
    # credential not in vault → _has_trade_perm defers to the broker gate
    broker = _register_broker("binanceusdm")
    _patch_bars(monkeypatch, {s: _df() for s in CRYPTO_VENUE["symbols"]})
    _patch_decisions(monkeypatch, [
        _decision("BTC/USDT:USDT", "crypto", side="long"),
    ])

    entry = await BotRunner().tick(rec.id, store)
    assert entry is not None and entry.action == "placed"
    assert entry.order_id == "order-kaos-1"
    assert broker.submit_order.await_count == 1
    kwargs = broker.submit_order.await_args.kwargs
    assert kwargs["symbol"] == "BTC/USDT:USDT"
    from showme.brokers import OrderSide, OrderType, TimeInForce
    assert kwargs["side"] == OrderSide.BUY
    assert kwargs["order_type"] == OrderType.MARKET
    assert kwargs["time_in_force"] == TimeInForce.IOC


@pytest.mark.asyncio
async def test_kaos_live_short_dispatches_sell(monkeypatch, tmp_path, store):
    sid = _save_sizing_spec(tmp_path, monkeypatch)
    rec = store.save(_kaos_record(sid, [CRYPTO_VENUE], mode="live"))
    broker = _register_broker("binanceusdm")
    _patch_bars(monkeypatch, {s: _df() for s in CRYPTO_VENUE["symbols"]})
    _patch_decisions(monkeypatch, [
        _decision("ETH/USDT:USDT", "crypto", side="short"),
    ])

    await BotRunner().tick(rec.id, store)
    kwargs = broker.submit_order.await_args.kwargs
    from showme.brokers import OrderSide
    assert kwargs["symbol"] == "ETH/USDT:USDT"
    assert kwargs["side"] == OrderSide.SELL


# ---- position book + lane accessors -----------------------------------------


def test_kaos_position_state_from_signal_log():
    rec = BotRecord(strategy_id="s", credential_id="c", exchange_id="e",
                    symbol="BTC/USDT", engine="kaos",
                    venues=[VenueSpec(**CRYPTO_VENUE)])
    rec = rec.append_signal(SignalEntry(
        bar_index=1, bar_time="t1", kind="entry", price=100.0,
        action="shadow", symbol="A", venue_id="crypto", side="short"))
    rec = rec.append_signal(SignalEntry(
        bar_index=2, bar_time="t2", kind="entry", price=5.0,
        action="shadow", symbol="B", venue_id="crypto", side="long"))
    rec = rec.append_signal(SignalEntry(
        bar_index=3, bar_time="t3", kind="exit", price=101.0,
        action="skipped", symbol="A", venue_id="crypto", side="short"))
    state = BotRunner._kaos_position_state(rec)
    # A's exit was skipped → position still open (F4 retry semantics);
    assert set(state) == {"A", "B"}
    assert state["A"]["side"] == "short"
    assert state["B"]["side"] == "long"


def test_kaos_lane_rows_idle_when_never_ticked():
    runner = BotRunner()
    rows = runner.kaos_lane_rows("nope", [CRYPTO_VENUE])
    assert rows == [{
        "venue_id": "crypto", "market": "crypto-futures", "bars_age": None,
        "last_eval": None, "decisions": 0, "lane_status": "idle",
    }]
