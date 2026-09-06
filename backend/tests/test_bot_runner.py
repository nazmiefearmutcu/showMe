"""BotRunner tick + lifecycle tests with mocked broker + evaluator."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from showme.bots.record import BotRecord
from showme.bots.runner import BotRunner
from showme.bots.store import BotStore


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
def store(tmp_path: Path) -> BotStore:
    return BotStore(tmp_path / "bots")


def _ohlcv_df(closes=(99, 99, 99, 99, 99, 105)) -> pd.DataFrame:
    """Default fixture: close crosses_above 100 only on the LAST bar.

    The runner only fires events whose bar_index == len(df) - 1, so the
    fixture is shaped to trigger on the final bar — otherwise tick()
    correctly drops mid-history events as already-processed history.
    """
    n = len(closes)
    idx = pd.date_range("2026-05-22", periods=n, freq="h")
    return pd.DataFrame({
        "open": closes, "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes], "close": list(closes),
        "volume": [1000] * n,
    }, index=idx)


def _save_strategy_with_always_entry(tmp_path: Path, monkeypatch) -> str:
    """Persist a tiny strategy that emits an entry when close crosses 100.

    Paired with the default _ohlcv_df() fixture so the cross happens on
    the last bar — which is the only bar the runner will act on.
    """
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    from showme.strategies.store import StrategyStore
    from showme.strategies.spec import StrategySpec, Rule
    spec = StrategySpec(
        name="last_bar_cross",
        entry_rules=[Rule(kind="crosses_above", left="close", right="literal:100")],
        exit_rules=[],
    )
    saved = StrategyStore.fresh().save(spec)
    return saved.id


def _save_strategy_risk_pct(tmp_path: Path, monkeypatch) -> str:
    """Strategy with risk_pct sizing so the runner consults broker equity.

    risk_pct is the sizing kind that threads ``_resolve_equity_with_source``,
    so the equity-source honesty tag is only meaningful for this kind.
    """
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    from showme.strategies.store import StrategyStore
    from showme.strategies.spec import StrategySpec, Rule, Position
    spec = StrategySpec(
        name="last_bar_cross_risk",
        entry_rules=[Rule(kind="crosses_above", left="close", right="literal:100")],
        exit_rules=[],
        position=Position(sizing_kind="risk_pct", sizing_value=2.0),
    )
    saved = StrategyStore.fresh().save(spec)
    return saved.id


def _register_fake_broker(credential_id: str, ohlcv_rows: list[list[float]]):
    from showme.brokers import factory as factory_mod
    broker = MagicMock()
    broker.name = f"ccxt:binance:{credential_id}"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=ohlcv_rows)
    broker.submit_order = AsyncMock(return_value=MagicMock(id="order-123"))
    factory_mod._REGISTRY[f"binance:{credential_id}"] = lambda b=broker: b
    factory_mod._DYNAMIC[credential_id] = f"binance:{credential_id}"
    return broker


@pytest.mark.asyncio
async def test_tick_shadow_mode_appends_signal(monkeypatch, tmp_path):
    sid = _save_strategy_with_always_entry(tmp_path, monkeypatch)
    rows = [
        [1748000000000, 100.0, 101.0, 99.0, 100.5, 1000.0],
        [1748003600000, 100.5, 102.0, 99.5, 101.0, 1100.0],
    ]
    _register_fake_broker("c1", rows)

    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c1", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow",
    ))

    # Patch fetch_ohlcv to return a deterministic DataFrame:
    def _df_fixture(broker, symbol, timeframe="1h", limit=200):
        return _ohlcv_df()
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=_df_fixture))

    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    assert signal is not None
    assert signal.action == "shadow"
    assert signal.order_id is None

    reloaded = store.get(bot.id)
    assert len(reloaded.signal_log) == 1
    assert reloaded.last_processed_event is not None


@pytest.mark.asyncio
async def test_tick_does_not_double_fire(monkeypatch, tmp_path):
    sid = _save_strategy_with_always_entry(tmp_path, monkeypatch)
    _register_fake_broker("c2", [])
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c2", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow",
    ))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))

    runner = BotRunner()
    s1 = await runner.tick(bot.id, store)
    s2 = await runner.tick(bot.id, store)
    assert s1 is not None
    assert s2 is None  # same bar, same kind → deduped


@pytest.mark.asyncio
async def test_tick_skips_when_broker_missing(monkeypatch, tmp_path):
    sid = _save_strategy_with_always_entry(tmp_path, monkeypatch)
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="not-registered", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow",
    ))
    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    assert signal is not None
    assert signal.action == "skipped"
    assert "broker unavailable" in (signal.error or "")


@pytest.mark.asyncio
async def test_enable_disable_lifecycle(monkeypatch, tmp_path):
    sid = _save_strategy_with_always_entry(tmp_path, monkeypatch)
    _register_fake_broker("c3", [])
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c3", exchange_id="binance",
        symbol="BTC/USDT", enabled=False, mode="shadow",
        tick_interval_seconds=10,
    ))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))

    runner = BotRunner()
    rec = await runner.enable(bot.id, store)
    assert rec.enabled is True
    assert runner.is_running(bot.id)

    rec = await runner.disable(bot.id, store)
    assert rec.enabled is False
    assert not runner.is_running(bot.id)
    await runner.aclose()


@pytest.mark.asyncio
async def test_aclose_cancels_all_tasks(monkeypatch, tmp_path):
    sid = _save_strategy_with_always_entry(tmp_path, monkeypatch)
    _register_fake_broker("c4", [])
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c4", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow",
        tick_interval_seconds=5,
    ))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))

    runner = BotRunner()
    await runner.start_all(store)
    assert runner.is_running(bot.id)
    await runner.aclose()
    assert not runner.is_running(bot.id)


@pytest.mark.asyncio
async def test_tick_live_mode_calls_submit_order(monkeypatch, tmp_path):
    sid = _save_strategy_with_always_entry(tmp_path, monkeypatch)
    rows = [[1748000000000, 100.0, 101.0, 99.0, 100.5, 1000.0]]
    broker = _register_fake_broker("c5", rows)
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c5", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))

    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    assert signal is not None
    assert signal.action == "placed"
    assert signal.order_id == "order-123"
    broker.submit_order.assert_called_once()


# ── H13 honesty: equity_source threading ────────────────────────────────


@pytest.mark.asyncio
async def test_live_tick_tags_equity_source_broker(monkeypatch, tmp_path):
    """A live tick whose broker reports real equity tags the SignalEntry
    with ``equity_source == "broker"`` (risk_pct sizing path)."""
    sid = _save_strategy_risk_pct(tmp_path, monkeypatch)
    rows = [[1748000000000, 100.0, 101.0, 99.0, 100.5, 1000.0]]
    broker = _register_fake_broker("ce1", rows)
    broker.account = AsyncMock(return_value={"equity": 50_000.0})
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="ce1", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))
    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    assert signal is not None
    assert signal.equity_source == "broker"


@pytest.mark.asyncio
async def test_live_tick_tags_equity_source_fallback(monkeypatch, tmp_path):
    """A live tick whose broker.account() is unavailable tags the
    SignalEntry with ``equity_source == "fallback_10k"``."""
    sid = _save_strategy_risk_pct(tmp_path, monkeypatch)
    rows = [[1748000000000, 100.0, 101.0, 99.0, 100.5, 1000.0]]
    broker = _register_fake_broker("ce2", rows)
    # account() raises → fallback path.
    broker.account = AsyncMock(side_effect=RuntimeError("no account"))
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="ce2", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))
    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    assert signal is not None
    assert signal.equity_source == "fallback_10k"


@pytest.mark.asyncio
async def test_shadow_tick_leaves_equity_source_none(monkeypatch, tmp_path):
    """Shadow-mode entries never size a real order → equity_source None."""
    sid = _save_strategy_risk_pct(tmp_path, monkeypatch)
    _register_fake_broker("ce3", [])
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="ce3", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow",
    ))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))
    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    assert signal is not None
    assert signal.action == "shadow"
    assert signal.equity_source is None


@pytest.mark.asyncio
async def test_live_risk_pct_tick_resolves_equity_exactly_once(monkeypatch, tmp_path):
    """P1 regression: a live risk_pct tick must call ``broker.account()``
    EXACTLY ONCE, and the recorded ``equity_source`` must match that single
    resolution.

    Before the fix, equity was resolved twice per tick: once to tag the
    SignalEntry (``_resolve_equity_with_source``) and again inside the
    dispatch / persisted-qty path (``_resolve_equity``). A consistent mock
    masked the divergence; this counter-backed fake catches a double-call
    regression directly.
    """
    sid = _save_strategy_risk_pct(tmp_path, monkeypatch)
    rows = [[1748000000000, 100.0, 101.0, 99.0, 100.5, 1000.0]]
    broker = _register_fake_broker("ce4", rows)

    # account() increments a counter every time it's awaited so we can
    # assert the runner hits the broker a single time per tick.
    call_count = {"n": 0}

    async def _counting_account():
        call_count["n"] += 1
        return {"equity": 50_000.0}

    broker.account = _counting_account
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="ce4", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))
    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    assert signal is not None
    # Exactly one broker.account() round-trip for the whole tick.
    assert call_count["n"] == 1, (
        f"expected broker.account() called once, got {call_count['n']}"
    )
    # The tag reflects that single (broker) resolution.
    assert signal.equity_source == "broker"


@pytest.mark.asyncio
async def test_live_risk_pct_tick_tag_matches_resolved_source(monkeypatch, tmp_path):
    """P1 regression: when account() falls back, the tag is ``fallback_10k``
    AND account() is still attempted exactly once (no second divergent call
    that could resolve differently)."""
    sid = _save_strategy_risk_pct(tmp_path, monkeypatch)
    rows = [[1748000000000, 100.0, 101.0, 99.0, 100.5, 1000.0]]
    broker = _register_fake_broker("ce5", rows)

    call_count = {"n": 0}

    async def _counting_account():
        call_count["n"] += 1
        raise RuntimeError("no account")  # forces fallback_10k

    broker.account = _counting_account
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="ce5", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))
    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    assert signal is not None
    assert call_count["n"] == 1, (
        f"expected broker.account() called once, got {call_count['n']}"
    )
    assert signal.equity_source == "fallback_10k"


# ── Money-risk campaign 2026-09-05: F1 / F3 / F4 / F5 regression tests ──


def _exit_df() -> pd.DataFrame:
    """close > 100 on bars 0..3 (entry fires bar 0), < 100 on the LAST
    bar (exit fires on the last bar) — same shape as
    tests/test_runner_fixes._exit_df."""
    closes = [101, 102, 103, 104, 99]
    n = len(closes)
    idx = pd.date_range("2026-05-22", periods=n, freq="h")
    return pd.DataFrame({
        "open": closes, "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes], "close": list(closes),
        "volume": [1000] * n,
    }, index=idx)


def _save_strategy_with_exit(tmp_path: Path, monkeypatch) -> str:
    """Strategy: entry when close > 100, exit when close < 100."""
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    from showme.strategies.spec import Rule, StrategySpec
    from showme.strategies.store import StrategyStore
    spec = StrategySpec(
        name="entry_gt_exit_lt",
        entry_rules=[Rule(kind="greater_than", left="close", right="literal:100")],
        exit_rules=[Rule(kind="less_than", left="close", right="literal:100")],
    )
    saved = StrategyStore.fresh().save(spec)
    return saved.id


def _save_strategy_limit_entry(tmp_path: Path, monkeypatch) -> str:
    """Strategy with a GTC limit entry (offset 0.1% below/above close)."""
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    from showme.strategies.spec import Position, Rule, StrategySpec
    from showme.strategies.store import StrategyStore
    spec = StrategySpec(
        name="limit_entry",
        entry_rules=[Rule(kind="crosses_above", left="close", right="literal:100")],
        exit_rules=[],
        position=Position(
            entry_order_type="limit", limit_price_offset_pct=0.1,
        ),
    )
    saved = StrategyStore.fresh().save(spec)
    return saved.id


def _seed_open_bot(store: BotStore, sid: str, credential_id: str) -> BotRecord:
    """Persist a live bot whose last event is a placed entry (qty=1 @101)."""
    from showme.bots.record import SignalEntry
    entry_event = SignalEntry(
        bar_index=0, bar_time="2026-05-22 00:00:00+00:00",
        kind="entry", price=101.0, action="placed", qty=1.0,
    )
    return store.save(BotRecord(
        strategy_id=sid, credential_id=credential_id, exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
        last_processed_event=entry_event, signal_log=[entry_event],
    ))


@pytest.mark.asyncio
async def test_f1_live_risk_sizing_refused_on_fallback_equity(monkeypatch, tmp_path):
    """F1: live + risk_pct sizing + broker.account() unavailable → the
    entry is REFUSED (skipped, nothing submitted) instead of being sized
    on the $10k fallback equity."""
    sid = _save_strategy_risk_pct(tmp_path, monkeypatch)
    broker = _register_fake_broker("f1", [])
    broker.account = AsyncMock(side_effect=RuntimeError("no account"))
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="f1", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))
    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    assert signal is not None
    assert signal.action == "skipped"
    assert "live sizing refused" in (signal.error or "")
    assert signal.equity_source == "fallback_10k"
    broker.submit_order.assert_not_called()


@pytest.mark.asyncio
async def test_f1_live_risk_sizing_proceeds_on_broker_equity(monkeypatch, tmp_path):
    """F1 complement: with real broker equity the live risk_pct entry is
    still submitted (no over-refusal)."""
    sid = _save_strategy_risk_pct(tmp_path, monkeypatch)
    broker = _register_fake_broker("f1b", [])
    broker.account = AsyncMock(return_value={"equity": 50_000.0})
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="f1b", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))
    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    assert signal is not None
    assert signal.action == "placed"
    broker.submit_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_f3_gtc_limit_zero_fill_is_cancelled(monkeypatch, tmp_path):
    """F3: a zero-fill GTC limit entry is CANCELLED and recorded as
    skipped with an explicit reason — no untracked resting order."""
    sid = _save_strategy_limit_entry(tmp_path, monkeypatch)
    from showme.brokers import OrderType, TimeInForce
    order = MagicMock(
        id="gtc-1", filled_quantity=0.0, quantity=1.0, avg_fill_price=None,
        order_type=OrderType.LIMIT, time_in_force=TimeInForce.GTC,
    )
    broker = _register_fake_broker("f3a", [])
    broker.submit_order = AsyncMock(return_value=order)
    broker.cancel_order = AsyncMock(return_value=True)
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="f3a", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))
    runner = BotRunner()
    entry = await runner.tick(bot.id, store)
    assert entry is not None
    assert entry.action == "skipped"
    assert "cancelled" in (entry.error or "")
    broker.cancel_order.assert_awaited_once_with("gtc-1")


@pytest.mark.asyncio
async def test_f3_gtc_limit_cancel_failure_classified_error(monkeypatch, tmp_path):
    """F3: when the cancel fails, the entry is classified ``error`` —
    visible, NOT silently skipped — because the order may rest on the
    exchange."""
    sid = _save_strategy_limit_entry(tmp_path, monkeypatch)
    from showme.brokers import OrderType, TimeInForce
    order = MagicMock(
        id="gtc-2", filled_quantity=0.0, quantity=1.0, avg_fill_price=None,
        order_type=OrderType.LIMIT, time_in_force=TimeInForce.GTC,
    )
    broker = _register_fake_broker("f3b", [])
    broker.submit_order = AsyncMock(return_value=order)
    broker.cancel_order = AsyncMock(return_value=False)
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="f3b", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()))
    runner = BotRunner()
    entry = await runner.tick(bot.id, store)
    assert entry is not None
    assert entry.action == "error"
    assert "rest on exchange" in (entry.error or "")


@pytest.mark.asyncio
async def test_f4_failed_exit_retries_on_next_tick(monkeypatch, tmp_path):
    """F4: a failed (skipped) EXIT must not be dedup-blocked for the rest
    of the bar — the close is re-attempted on the next tick while the
    exit condition persists."""
    sid = _save_strategy_with_exit(tmp_path, monkeypatch)
    broker = _register_fake_broker("f4", [])
    broker.close_position = AsyncMock(side_effect=RuntimeError("boom"))
    store = BotStore(tmp_path / "bots")
    bot = _seed_open_bot(store, sid, "f4")
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _exit_df()))
    runner = BotRunner()
    s1 = await runner.tick(bot.id, store)
    assert s1 is not None
    assert s1.kind == "exit"
    assert s1.action == "skipped"
    s2 = await runner.tick(bot.id, store)
    assert s2 is not None
    assert s2.kind == "exit"
    # The retry actually reached the broker again.
    assert broker.close_position.await_count == 2


@pytest.mark.asyncio
async def test_f5_funding_accrues_on_signal_tick_and_paid_at_close(monkeypatch, tmp_path):
    """F5: funding accrues even on the tick that FIRES the exit — the
    signal-tick slice is included in ``funding_paid`` — and the
    accumulator resets to 0 after the close."""
    sid = _save_strategy_with_exit(tmp_path, monkeypatch)
    broker = _register_fake_broker("f5", [])
    broker._ex.fetch_funding_rate = AsyncMock(
        return_value={"fundingRate": 0.0001},
    )
    broker.close_position = AsyncMock(return_value=MagicMock(
        id="close-1", filled_quantity=1.0, quantity=1.0, avg_fill_price=99.0,
    ))
    store = BotStore(tmp_path / "bots")
    bot = _seed_open_bot(store, sid, "f5")
    # Pre-seed prior accrual so we can distinguish "reset happened" from
    # "accumulator was never touched".
    fresh = store.get(bot.id)
    store.save(fresh.model_copy(update={"cumulative_funding_pnl": 0.5}))
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _exit_df()))
    runner = BotRunner()
    s = await runner.tick(bot.id, store)
    assert s is not None
    assert s.action == "placed"
    rec = store.get(bot.id)
    assert len(rec.closed_trades_log) == 1
    dt = float(rec.tick_interval_seconds)
    signal_tick_delta = 101.0 * 1.0 * 0.0001 * (dt / (8 * 3600.0))
    assert rec.closed_trades_log[0].funding_paid == pytest.approx(
        0.5 + signal_tick_delta,
    )
    assert rec.cumulative_funding_pnl == 0.0


@pytest.mark.asyncio
async def test_f5_funding_resets_even_when_pairing_fails(monkeypatch, tmp_path):
    """F5: a non-skipped exit resets the funding accumulator even when the
    ClosedTrade pairing fails (opening entry missing from signal_log) —
    the stale funding must not leak into the next round-trip."""
    sid = _save_strategy_with_exit(tmp_path, monkeypatch)
    broker = _register_fake_broker("f5b", [])
    broker.close_position = AsyncMock(return_value=MagicMock(
        id="close-2", filled_quantity=1.0, quantity=1.0, avg_fill_price=99.0,
    ))
    store = BotStore(tmp_path / "bots")
    bot = _seed_open_bot(store, sid, "f5b")
    # The pairing requires the entry IN signal_log; drop it so pairing
    # fails while the exit still goes through.
    fresh = store.get(bot.id)
    fresh = fresh.model_copy(update={
        "signal_log": [],
        "cumulative_funding_pnl": 0.5,
    })
    store.save(fresh)
    monkeypatch.setattr("showme.bots.runner.fetch_ohlcv",
                        AsyncMock(side_effect=lambda *a, **k: _exit_df()))
    runner = BotRunner()
    s = await runner.tick(bot.id, store)
    assert s is not None
    assert s.action == "placed"
    rec = store.get(bot.id)
    assert rec.closed_trades_log == []  # pairing failed
    # BASE behaviour kept the stale 0.5; the fix resets it.
    assert rec.cumulative_funding_pnl == 0.0
