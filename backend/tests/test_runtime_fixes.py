"""Cross-cutting regression tests for the 2026-05-23 audit fixes.

Each test pins a specific bug from BOT_AUDIT_REPORT.md. Keep them
narrow — one bug → one assertion path.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from showme.bots.record import BotRecord, SignalEntry
from showme.bots.runner import BotRunner
from showme.bots.store import BotStore


# ── Fixture wiring shared across the suite ──────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_factory():
    from showme.brokers import factory as factory_mod
    snap_reg = dict(factory_mod._REGISTRY)
    snap_dyn = dict(factory_mod._DYNAMIC)
    snap_live = dict(factory_mod._LIVE)
    snap_hooks = list(factory_mod._INVALIDATION_HOOKS)
    yield
    factory_mod._REGISTRY.clear()
    factory_mod._REGISTRY.update(snap_reg)
    factory_mod._DYNAMIC.clear()
    factory_mod._DYNAMIC.update(snap_dyn)
    factory_mod._LIVE.clear()
    factory_mod._LIVE.update(snap_live)
    factory_mod._INVALIDATION_HOOKS.clear()
    factory_mod._INVALIDATION_HOOKS.extend(snap_hooks)


def _ohlcv_df(closes=(99, 99, 99, 99, 99, 105)) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2026-05-22", periods=n, freq="h")
    return pd.DataFrame({
        "open": closes, "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes], "close": list(closes),
        "volume": [1000] * n,
    }, index=idx)


def _save_strategy(tmp_path: Path, monkeypatch, *, timeframe="1h", side="long"):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    from showme.strategies.spec import Position, Rule, StrategySpec
    from showme.strategies.store import StrategyStore
    spec = StrategySpec(
        name="cross_strat",
        timeframe=timeframe,
        entry_rules=[Rule(kind="crosses_above", left="close", right="literal:100")],
        exit_rules=[Rule(kind="crosses_below", left="close", right="literal:100")],
        position=Position(side=side, sizing_kind="fixed_quote", sizing_value=100.0),
    )
    return StrategyStore.fresh().save(spec).id


# ── C-RUNTIME-3 / C6: broker instance cache ─────────────────────────────


def test_get_broker_returns_cached_instance():
    """``get_broker(name)`` must return the same instance on repeated
    calls — otherwise per-tick instantiations leak aiohttp connectors."""
    from showme.brokers import factory as factory_mod
    calls = {"n": 0}

    def _factory():
        calls["n"] += 1
        b = MagicMock()
        b.name = "test:fake"
        return b

    factory_mod.register_broker("test:fake", _factory)
    a = factory_mod.get_broker("test:fake")
    b = factory_mod.get_broker("test:fake")
    c = factory_mod.get_broker("test:fake")
    assert a is b is c
    assert calls["n"] == 1


def test_unregister_credential_evicts_cache():
    """unregister_credential must drop the cached broker so a re-register
    of the same name builds afresh (different secrets, etc)."""
    from showme.brokers import factory as factory_mod
    calls = {"n": 0}

    def _factory():
        calls["n"] += 1
        return MagicMock(name="binance:c1")

    factory_mod.register_broker("binance:c1", _factory)
    factory_mod._DYNAMIC["c1"] = "binance:c1"
    factory_mod.get_broker("binance:c1")
    assert calls["n"] == 1

    factory_mod.unregister_credential("c1")
    # After unregister the broker must be removed from _LIVE.
    assert "binance:c1" not in factory_mod._LIVE


@pytest.mark.asyncio
async def test_unregister_credential_calls_aclose():
    """unregister_credential must call aclose() on the evicted broker."""
    import asyncio
    from unittest.mock import AsyncMock
    from showme.brokers import factory as factory_mod

    mock_broker = AsyncMock()
    factory_mod.register_broker("binance:c2", lambda: mock_broker)
    factory_mod._DYNAMIC["c2"] = "binance:c2"
    factory_mod.get_broker("binance:c2")

    factory_mod.unregister_credential("c2")
    await asyncio.sleep(0.01)
    mock_broker.aclose.assert_called_once()


# ── C-API-2: bollinger std_dev alias ────────────────────────────────────


def test_bollinger_accepts_std_dev_alias():
    """The shipped template uses ``std_dev`` but compute used to read only
    ``num_std``. Both spellings must yield identical bands."""
    from showme.strategies.compute import compute
    from showme.strategies.spec import IndicatorRef
    n = 60
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    df = pd.DataFrame({
        "open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n,
        "close": [100.0 + (i % 7) for i in range(n)], "volume": [1000] * n,
    }, index=idx)

    via_num_std = compute(df, [
        IndicatorRef(alias="bbu", id="bollinger_upper",
                     params={"period": 20, "num_std": 3.0}),
    ])
    via_std_dev = compute(df, [
        IndicatorRef(alias="bbu", id="bollinger_upper",
                     params={"period": 20, "std_dev": 3.0}),
    ])
    pd.testing.assert_series_equal(
        via_num_std["bbu"].dropna(), via_std_dev["bbu"].dropna(),
        check_names=False,
    )


# ── C-RUNTIME-4 / H-RT-1: partial fill audit ────────────────────────────


@pytest.mark.asyncio
async def test_partial_fill_marked_placed_with_diagnostic(monkeypatch, tmp_path):
    """A live order that comes back with ``filled_quantity`` smaller than
    requested must be recorded as ``placed`` with a partial-fill note in
    the error field — never silently as ``placed`` with no signal."""
    from showme.brokers import factory as factory_mod
    sid = _save_strategy(tmp_path, monkeypatch)

    partial_order = MagicMock()
    partial_order.id = "ord-1"
    partial_order.quantity = 1.0
    partial_order.filled_quantity = 0.4  # 40% fill

    broker = MagicMock()
    broker.name = "ccxt:binance:c1"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    broker.submit_order = AsyncMock(return_value=partial_order)
    broker.account = AsyncMock(return_value={"equity": 10_000})
    factory_mod._REGISTRY["binance:c1"] = lambda b=broker: b
    factory_mod._DYNAMIC["c1"] = "binance:c1"

    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))

    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c1", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))

    runner = BotRunner()
    sig = await runner.tick(bot.id, store)
    assert sig is not None
    assert sig.action == "placed"
    assert sig.error is not None
    assert "partial" in sig.error.lower()


@pytest.mark.asyncio
async def test_ioc_unfilled_downgrades_to_skipped(monkeypatch, tmp_path):
    """``filled_quantity == 0`` (IOC rejected by the exchange) must
    downgrade the signal to ``skipped`` so PERF doesn't count it."""
    from showme.brokers import factory as factory_mod
    sid = _save_strategy(tmp_path, monkeypatch)

    unfilled_order = MagicMock()
    unfilled_order.id = "ord-2"
    unfilled_order.quantity = 1.0
    unfilled_order.filled_quantity = 0.0  # IOC rejection

    broker = MagicMock()
    broker.name = "ccxt:binance:c2"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    broker.submit_order = AsyncMock(return_value=unfilled_order)
    broker.account = AsyncMock(return_value={"equity": 10_000})
    factory_mod._REGISTRY["binance:c2"] = lambda b=broker: b
    factory_mod._DYNAMIC["c2"] = "binance:c2"

    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))

    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c2", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))

    runner = BotRunner()
    sig = await runner.tick(bot.id, store)
    assert sig is not None
    assert sig.action == "skipped"
    assert "unfilled" in (sig.error or "").lower()


# ── C-RUNTIME-4: exit uses close_position when available ───────────────


@pytest.mark.asyncio
async def test_exit_prefers_close_position(monkeypatch, tmp_path):
    """When the broker exposes ``close_position``, the exit branch must
    call it rather than re-using ``submit_order`` (which would reverse
    exposure if the position size differs from the strategy sizing)."""
    from showme.brokers import factory as factory_mod
    sid = _save_strategy(tmp_path, monkeypatch)

    closed = MagicMock(id="close-ord", quantity=1.0, filled_quantity=1.0)
    submitted = MagicMock(id="open-ord", quantity=1.0, filled_quantity=1.0)

    broker = MagicMock()
    broker.name = "ccxt:binance:c3"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    broker.submit_order = AsyncMock(return_value=submitted)
    broker.close_position = AsyncMock(return_value=closed)
    broker.account = AsyncMock(return_value={"equity": 10_000})
    factory_mod._REGISTRY["binance:c3"] = lambda b=broker: b
    factory_mod._DYNAMIC["c3"] = "binance:c3"

    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))

    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c3", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
        last_processed_event=SignalEntry(
            bar_index=4, bar_time="2026-05-22 04:00:00+00:00",
            kind="entry", price=99.0, action="placed", order_id="open-ord",
        ),
    ))

    # Drive the exit branch by making the last bar cross below 100.
    exit_df = _ohlcv_df(closes=(105, 105, 105, 105, 105, 95))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: exit_df))

    runner = BotRunner()
    sig = await runner.tick(bot.id, store)
    assert sig is not None
    assert sig.kind == "exit"
    assert sig.action == "placed"
    broker.close_position.assert_called_once_with("BTC/USDT")
    # submit_order MUST NOT have been called on the exit path.
    broker.submit_order.assert_not_called()


# ── H-RT-6: bot vs strategy timeframe drift ────────────────────────────


@pytest.mark.asyncio
async def test_timeframe_drift_skips_tick(monkeypatch, tmp_path):
    """Bot.timeframe=1m but strategy.timeframe=4h → tick must record a
    ``skipped`` signal with a clear error rather than silently running
    a wrong-cadence evaluation."""
    sid = _save_strategy(tmp_path, monkeypatch, timeframe="4h")

    from showme.brokers import factory as factory_mod
    broker = MagicMock()
    broker.name = "ccxt:binance:c4"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    broker.submit_order = AsyncMock()
    factory_mod._REGISTRY["binance:c4"] = lambda b=broker: b
    factory_mod._DYNAMIC["c4"] = "binance:c4"

    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c4", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow",
        timeframe="1m",
    ))

    runner = BotRunner()
    sig = await runner.tick(bot.id, store)
    assert sig is not None
    assert sig.action == "skipped"
    assert "timeframe" in (sig.error or "").lower()
    broker.submit_order.assert_not_called()


# ── C-RUNTIME-2 / state-amnesia regression ─────────────────────────────


@pytest.mark.asyncio
async def test_in_position_does_not_re_entry_on_same_bar(monkeypatch, tmp_path):
    """A bot whose ``last_processed_event`` is an entry must NOT receive
    another ``entry`` event for the same bar even if the entry condition
    still matches that bar — proves the runner now consults
    ``in_position`` state instead of replaying the spec from scratch."""
    sid = _save_strategy(tmp_path, monkeypatch)

    from showme.brokers import factory as factory_mod
    broker = MagicMock()
    broker.name = "ccxt:binance:c5"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    factory_mod._REGISTRY["binance:c5"] = lambda b=broker: b
    factory_mod._DYNAMIC["c5"] = "binance:c5"

    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))

    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c5", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow",
        last_processed_event=SignalEntry(
            bar_index=5, bar_time="2026-05-22 05:00:00+00:00",
            kind="entry", price=105.0, action="shadow",
        ),
    ))

    runner = BotRunner()
    sig = await runner.tick(bot.id, store)
    # ``in_position`` is True (last event is an entry); evaluate_last_bar
    # only checks exit rules — exit_rules need close < 100, last close
    # is 105, so no event.
    assert sig is None


# ── C-INT-1 / C3: cascade hook ─────────────────────────────────────────


def test_cascade_hook_disables_referencing_bots(monkeypatch, tmp_path):
    """The lifespan cascade hook must persist enabled=False on every bot
    bound to a deleted credential. The runner-side cancel path is best-
    effort (requires a running loop); the persistence path is required."""
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    sid = _save_strategy(tmp_path, monkeypatch)

    store = BotStore.fresh()
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="cred-123", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow",
    ))
    assert store.get(bot.id).enabled is True

    # Wire the hook explicitly (lifespan.startup is async and we test sync).
    from showme.bots.lifespan import _on_credential_deleted
    _on_credential_deleted("cred-123")

    # The bot must now be disabled on disk.
    assert store.get(bot.id).enabled is False


def test_cascade_hook_ignores_unrelated_bots(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    sid = _save_strategy(tmp_path, monkeypatch)

    store = BotStore.fresh()
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="my-creds", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow",
    ))

    from showme.bots.lifespan import _on_credential_deleted
    _on_credential_deleted("some-other-credential")
    assert store.get(bot.id).enabled is True  # unaffected


# ── C4: closed_trades_log appended on paired exit ──────────────────────


@pytest.mark.asyncio
async def test_paired_exit_appends_closed_trade(monkeypatch, tmp_path):
    """When the runner pairs an exit with a previously-seen entry it
    must append a ClosedTrade to closed_trades_log (in addition to the
    signal_log append). PERF reads closed_trades_log so this is the
    correctness boundary between data loss and accurate PnL."""
    sid = _save_strategy(tmp_path, monkeypatch)

    from showme.brokers import factory as factory_mod
    broker = MagicMock()
    broker.name = "ccxt:binance:c6"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    factory_mod._REGISTRY["binance:c6"] = lambda b=broker: b
    factory_mod._DYNAMIC["c6"] = "binance:c6"

    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c6", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow",
        last_processed_event=SignalEntry(
            bar_index=4, bar_time="2026-05-22 04:00:00+00:00",
            kind="entry", price=99.0, action="shadow",
        ),
        signal_log=[
            SignalEntry(
                bar_index=4, bar_time="2026-05-22 04:00:00+00:00",
                kind="entry", price=99.0, action="shadow",
            ),
        ],
    ))

    # Drive an exit on the last bar: crosses_below 100.
    exit_df = _ohlcv_df(closes=(105, 105, 105, 105, 105, 95))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: exit_df))

    runner = BotRunner()
    sig = await runner.tick(bot.id, store)
    assert sig is not None
    assert sig.kind == "exit"

    reloaded = store.get(bot.id)
    assert len(reloaded.closed_trades_log) == 1
    ct = reloaded.closed_trades_log[0]
    assert ct.entry_price == 99.0
    assert ct.exit_price == 95.0
    assert ct.side == "long"
    # Long-side, entry=99, exit=95 → pnl negative.
    assert ct.pnl < 0


# ── C-RUNTIME-1: TF/tick extreme combos rejected ────────────────────────


def test_extreme_tick_too_slow_rejected():
    """``timeframe=1m`` + ``tick_interval=3600s`` would skip ~60 bars per
    tick — Pydantic must reject the construction up-front."""
    with pytest.raises(Exception):
        BotRecord(
            strategy_id="s", credential_id="c", exchange_id="binance",
            symbol="BTC/USDT", timeframe="1m", tick_interval_seconds=3600,
        )


def test_extreme_tick_too_aggressive_rejected():
    """``timeframe=1d`` + ``tick_interval=5s`` would generate 17,280
    ticks/day — Pydantic must reject."""
    with pytest.raises(Exception):
        BotRecord(
            strategy_id="s", credential_id="c", exchange_id="binance",
            symbol="BTC/USDT", timeframe="1d", tick_interval_seconds=5,
        )


def test_reasonable_tick_combos_accepted():
    """Existing safe combos like (1h, 60s), (15m, 5s), (1d, 60s) must
    keep working."""
    BotRecord(strategy_id="s", credential_id="c", exchange_id="e",
              symbol="X", timeframe="1h", tick_interval_seconds=60)
    BotRecord(strategy_id="s", credential_id="c", exchange_id="e",
              symbol="X", timeframe="15m", tick_interval_seconds=5)
    BotRecord(strategy_id="s", credential_id="c", exchange_id="e",
              symbol="X", timeframe="1d", tick_interval_seconds=60)


# ── Performance: sizing_kind switch ────────────────────────────────────


def test_performance_fixed_base_matches_sizing_module():
    """H-SUP-3 regression at the route level. ``compute_trades`` with
    ``sizing_kind='fixed_base'`` must use ``sizing_value`` as the qty —
    the legacy ``fixed_quote`` formula would be off by 60000× for 2 BTC."""
    from showme.bots.performance import compute_trades

    log = [
        SignalEntry(bar_index=0, bar_time="t1", kind="entry",
                    price=30_000.0, action="shadow"),
        SignalEntry(bar_index=1, bar_time="t2", kind="exit",
                    price=32_000.0, action="shadow"),
    ]
    trades = compute_trades(log, sizing_value=2.0, sizing_kind="fixed_base")
    assert len(trades) == 1
    # 2 BTC × ($32k - $30k) = $4000 absolute PnL.
    assert trades[0].pnl == pytest.approx(4_000.0)


def test_performance_short_side_pnl():
    """A short round-trip earns when price falls."""
    from showme.bots.performance import compute_trades

    log = [
        SignalEntry(bar_index=0, bar_time="t1", kind="entry",
                    price=100.0, action="shadow"),
        SignalEntry(bar_index=1, bar_time="t2", kind="exit",
                    price=90.0, action="shadow"),
    ]
    trades = compute_trades(log, sizing_value=100.0,
                            sizing_kind="fixed_quote", side="short")
    assert len(trades) == 1
    # 1 unit × $10 favorable move = +$10 PnL on the short.
    assert trades[0].pnl == pytest.approx(10.0)


# ── compute_trades_from_closed ─────────────────────────────────────────


def test_compute_trades_from_closed_reads_canonical_log():
    """``compute_trades_from_closed`` produces Trade aggregates directly
    from a bot's ``closed_trades_log``. This is the path PERF should use
    once C4 is rolled out everywhere."""
    from showme.bots.performance import compute_trades_from_closed
    from showme.bots.record import ClosedTrade

    closed = [
        ClosedTrade(
            entry_timestamp="t1", exit_timestamp="t2",
            entry_price=100.0, exit_price=110.0,
            qty=1.0, side="long", pnl=10.0,
            bar_index_entry=0, bar_index_exit=1,
        ),
        ClosedTrade(
            entry_timestamp="t3", exit_timestamp="t4",
            entry_price=120.0, exit_price=115.0,
            qty=2.0, side="long", pnl=-10.0,
            bar_index_entry=2, bar_index_exit=3,
        ),
    ]
    out = compute_trades_from_closed(closed)
    assert len(out) == 2
    assert out[0].pnl == 10.0
    assert out[1].pnl == -10.0
