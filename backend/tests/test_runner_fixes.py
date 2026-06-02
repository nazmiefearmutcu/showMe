"""Faz 1 regression tests — pin the contract for runner + ohlcv bug-fixes.

Covers:
* S1 — exit dispatches close_position (not a fresh BUY/SELL with sizing_value).
* S2 — sizing_value semantics: fixed_base / fixed_quote / risk_pct branch
  to correct quantity.
* S3 — _is_ccxt detects ccxt-backed brokers structurally, not by name prefix.
* S4 — start_all auto-disables live-mode bots whose credential lost the
  trade permission.
* S8 — per-bot asyncio.Lock makes tick + concurrent CRUD save-safe.
* H-13 — Event.side propagates spec.position.side; runner uses it for
  long → BUY vs short → SELL on entry.

The fixtures intentionally mirror tests/test_bot_runner.py so the patches
target the same code paths used by production tick(). The MagicMock
brokers are registered through ``factory_mod._REGISTRY`` and reused by
the production ``get_broker(name)`` lookup.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from showme.bots.record import BotRecord
from showme.bots.runner import BotRunner, _resolve_quantity
from showme.bots.store import BotStore


# ── Fixtures shared with the existing runner test file ───────────────────


@pytest.fixture(autouse=True)
def _isolate_factory():
    """Snapshot the global broker registry so each test starts clean."""
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


def _ohlcv_df(closes=(99, 99, 99, 99, 99, 105)) -> pd.DataFrame:
    """Identical fixture to test_bot_runner._ohlcv_df — close crosses
    100 on the LAST bar so the runner actually fires an event."""
    n = len(closes)
    idx = pd.date_range("2026-05-22", periods=n, freq="h")
    return pd.DataFrame({
        "open": closes, "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes], "close": list(closes),
        "volume": [1000] * n,
    }, index=idx)


def _save_strategy(
    tmp_path: Path,
    monkeypatch,
    *,
    sizing_kind: str = "fixed_base",
    sizing_value: float = 1.0,
    side: str = "long",
) -> str:
    """Persist a tiny strategy. Default fires entry when close crosses 100
    (paired with the default _ohlcv_df). Sizing + side are tunable."""
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    from showme.strategies.store import StrategyStore
    from showme.strategies.spec import (
        Position,
        Rule,
        StrategySpec,
    )
    spec = StrategySpec(
        name="t",
        entry_rules=[Rule(kind="crosses_above", left="close", right="literal:100")],
        # Exit fires when close < 100 (cross down). Default fixture stays > 100
        # so exit only fires when we use the _exit_df fixture below.
        exit_rules=[Rule(kind="less_than", left="close", right="literal:100")],
        position=Position(side=side, sizing_kind=sizing_kind, sizing_value=sizing_value),
    )
    saved = StrategyStore.fresh().save(spec)
    return saved.id


def _save_strategy_for_exit(
    tmp_path: Path,
    monkeypatch,
    *,
    sizing_kind: str = "fixed_base",
    sizing_value: float = 1.0,
    side: str = "long",
) -> str:
    """Strategy whose evaluate sequence is entry-then-exit on the same df.

    Entry: close > 100. Exit: close < 100. Used with _exit_df below."""
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    from showme.strategies.store import StrategyStore
    from showme.strategies.spec import Position, Rule, StrategySpec
    spec = StrategySpec(
        name="t_exit",
        entry_rules=[Rule(kind="greater_than", left="close", right="literal:100")],
        exit_rules=[Rule(kind="less_than", left="close", right="literal:100")],
        position=Position(side=side, sizing_kind=sizing_kind, sizing_value=sizing_value),
    )
    saved = StrategyStore.fresh().save(spec)
    return saved.id


def _exit_df() -> pd.DataFrame:
    """Sequence designed to drive evaluate into the exit branch on the LAST
    bar so runner.tick() sees a fresh exit event.

    Bars 0..3 above 100 → entry fires on bar 0. Bar 4 (the last) crosses
    below 100 → exit fires on the last bar."""
    closes = [101, 102, 103, 104, 99]
    n = len(closes)
    idx = pd.date_range("2026-05-22", periods=n, freq="h")
    return pd.DataFrame({
        "open": closes, "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes], "close": list(closes),
        "volume": [1000] * n,
    }, index=idx)


def _register_fake_broker(
    credential_id: str,
    *,
    name_prefix: str = "ccxt:binance:",
    exchange_id: str = "binance",
    include_close_position: bool = True,
):
    """Register a MagicMock broker under the production registry key.

    Production: ``factory.get_broker("{exchange_id}:{credential_id}")`` →
    a CcxtBroker. We register a MagicMock under the same key with
    ``submit_order`` / ``close_position`` as AsyncMocks so tests can assert
    invocations.
    """
    from showme.brokers import factory as factory_mod
    broker = MagicMock()
    # The structural check in _is_ccxt accepts either a real CcxtBroker
    # instance, an _ex.fetch_ohlcv duck, or the legacy name prefix. The
    # mock here uses the prefix path so existing tests stay green.
    broker.name = f"{name_prefix}{credential_id}"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    broker.submit_order = AsyncMock(return_value=MagicMock(id="order-entry"))
    if include_close_position:
        broker.close_position = AsyncMock(return_value=MagicMock(id="order-close"))
    else:
        # Simulate brokers (e.g. legacy paper) that don't expose
        # close_position so we can pin the documented fallback path.
        # We use ``del`` so ``getattr(broker, "close_position", None)``
        # returns None — MagicMock would otherwise auto-create the
        # attribute on access.
        del broker.close_position
    factory_mod._REGISTRY[f"{exchange_id}:{credential_id}"] = lambda b=broker: b
    factory_mod._DYNAMIC[credential_id] = f"{exchange_id}:{credential_id}"
    return broker


# ── S1: exit dispatches close_position, not BUY/SELL with sizing_value ───


@pytest.mark.asyncio
async def test_s1_exit_calls_close_position_not_submit_order(monkeypatch, tmp_path):
    """S1 fix: long-side strategy exit must close the existing position
    via ``broker.close_position(symbol)`` rather than firing a fresh
    SELL order with ``sizing_value`` as the quantity (which was the
    pre-fix bug — opening new short exposure on what was meant to be a
    close).

    Updated 2026-05-23: ``evaluate_last_bar`` requires the bot to already
    be in a position before it'll emit an exit; we seed
    ``last_processed_event`` accordingly.
    """
    sid = _save_strategy_for_exit(tmp_path, monkeypatch,
                                   sizing_kind="fixed_base", sizing_value=1.0)
    broker = _register_fake_broker("c-s1")
    store = BotStore(tmp_path / "bots")
    from showme.bots.record import SignalEntry
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c-s1", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
        last_processed_event=SignalEntry(
            bar_index=0, bar_time="2026-05-22 00:00:00+00:00",
            kind="entry", price=101.0, action="placed",
        ),
    ))
    monkeypatch.setattr(
        "showme.bots.runner.fetch_ohlcv",
        AsyncMock(side_effect=lambda *a, **k: _exit_df()),
    )

    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    assert signal is not None
    assert signal.kind == "exit"
    assert signal.action == "placed"
    # Critical: close_position was used, NOT submit_order.
    broker.close_position.assert_awaited_once_with("BTC/USDT")
    broker.submit_order.assert_not_called()


@pytest.mark.asyncio
async def test_s1_exit_fallback_when_broker_lacks_close_position(monkeypatch, tmp_path):
    """S1 documented fallback: when the broker doesn't implement
    close_position (legacy paper variants), the runner uses an opposite-
    side market order. The qty still goes through _resolve_quantity so
    S2 semantics apply.

    Updated 2026-05-23: seed ``last_processed_event`` so the state-aware
    ``evaluate_last_bar`` triggers the exit branch.
    """
    sid = _save_strategy_for_exit(tmp_path, monkeypatch,
                                   sizing_kind="fixed_base", sizing_value=0.5,
                                   side="long")
    broker = _register_fake_broker("c-s1f", include_close_position=False)
    store = BotStore(tmp_path / "bots")
    from showme.bots.record import SignalEntry
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c-s1f", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
        last_processed_event=SignalEntry(
            bar_index=0, bar_time="2026-05-22 00:00:00+00:00",
            kind="entry", price=101.0, action="placed",
        ),
    ))
    monkeypatch.setattr(
        "showme.bots.runner.fetch_ohlcv",
        AsyncMock(side_effect=lambda *a, **k: _exit_df()),
    )

    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    assert signal is not None
    assert signal.kind == "exit"
    assert signal.action == "placed"
    # Fallback path: long exit → opposite is SELL.
    args, kwargs = broker.submit_order.call_args
    from showme.brokers import OrderSide
    assert kwargs["side"] == OrderSide.SELL
    assert kwargs["quantity"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_s1_exit_fallback_partial_fill_uses_persisted_qty(monkeypatch, tmp_path):
    """Exit fallback must use the entry's actual filled qty to close the position
    in case of partial fills."""
    sid = _save_strategy_for_exit(tmp_path, monkeypatch,
                                   sizing_kind="fixed_base", sizing_value=0.5,
                                   side="long")
    broker = _register_fake_broker("c-s1f-pf", include_close_position=False)
    store = BotStore(tmp_path / "bots")
    from showme.bots.record import SignalEntry

    # Simulating a partial fill on entry (only 0.2 units filled out of 0.5 requested)
    entry_event = SignalEntry(
        bar_index=0, bar_time="2026-05-22 00:00:00+00:00",
        kind="entry", price=101.0, action="placed", qty=0.2,
    )

    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c-s1f-pf", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
        last_processed_event=entry_event,
        signal_log=[entry_event],
    ))
    monkeypatch.setattr(
        "showme.bots.runner.fetch_ohlcv",
        AsyncMock(side_effect=lambda *a, **k: _exit_df()),
    )

    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    assert signal is not None
    assert signal.kind == "exit"
    assert signal.action == "placed"

    # Fallback path must use the persisted entry qty of 0.2 instead of re-resolving to 0.5.
    args, kwargs = broker.submit_order.call_args
    assert kwargs["quantity"] == pytest.approx(0.2)


# ── S2: sizing_value branches on sizing_kind ─────────────────────────────


def test_s2_sizing_kind_fixed_base():
    """fixed_base: sizing_value is already a base-currency quantity."""
    from showme.strategies.spec import Position, StrategySpec
    spec = StrategySpec(
        name="x",
        position=Position(sizing_kind="fixed_base", sizing_value=0.25),
    )
    df = _ohlcv_df(closes=[60000.0])
    assert _resolve_quantity(spec, df) == pytest.approx(0.25)


def test_s2_sizing_kind_fixed_quote_divides_by_last_close():
    """fixed_quote: quantity = sizing_value / last_close. The bug-pre-fix
    behaviour passed 100 (USDT) as the quantity, which on a 60k BTC price
    would have meant a 100-BTC order."""
    from showme.strategies.spec import Position, StrategySpec
    spec = StrategySpec(
        name="x",
        position=Position(sizing_kind="fixed_quote", sizing_value=100.0),
    )
    df = _ohlcv_df(closes=[60000.0])
    # 100 USDT / 60_000 USDT-per-BTC = 0.001666...
    assert _resolve_quantity(spec, df) == pytest.approx(100.0 / 60000.0)


def test_s2_sizing_kind_risk_pct_uses_reference_equity():
    """risk_pct: quantity = (reference_equity * value/100) / last_close.
    The reference equity is a documented Faz 1 limitation — a future
    iteration should pull from broker.account()."""
    from showme.bots.runner import _REFERENCE_EQUITY_USD
    from showme.strategies.spec import Position, StrategySpec
    spec = StrategySpec(
        name="x",
        position=Position(sizing_kind="risk_pct", sizing_value=2.0),
    )
    df = _ohlcv_df(closes=[200.0])
    budget = _REFERENCE_EQUITY_USD * 0.02
    assert _resolve_quantity(spec, df) == pytest.approx(budget / 200.0)


def test_s2_sizing_resolver_rejects_non_positive_price():
    """Defensive: a zero last close raises rather than dividing by zero."""
    from showme.bots.ohlcv import BotRunnerError
    from showme.strategies.spec import Position, StrategySpec
    spec = StrategySpec(
        name="x",
        position=Position(sizing_kind="fixed_quote", sizing_value=10.0),
    )
    df = _ohlcv_df(closes=[0.0])
    with pytest.raises(BotRunnerError):
        _resolve_quantity(spec, df)


@pytest.mark.asyncio
async def test_s2_entry_live_uses_resolved_quantity(monkeypatch, tmp_path):
    """End-to-end: live entry with fixed_quote=100 on a 105-close fixture
    should submit ``quantity=100/105`` — not 100."""
    sid = _save_strategy(tmp_path, monkeypatch,
                         sizing_kind="fixed_quote", sizing_value=100.0)
    broker = _register_fake_broker("c-s2")
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c-s2", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))
    monkeypatch.setattr(
        "showme.bots.runner.fetch_ohlcv",
        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()),
    )

    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    assert signal is not None
    assert signal.action == "placed"
    args, kwargs = broker.submit_order.call_args
    assert kwargs["quantity"] == pytest.approx(100.0 / 105.0)


# ── S3: _is_ccxt detects production broker keys structurally ─────────────


def test_s3_is_ccxt_accepts_real_ccxt_broker_instance(monkeypatch):
    """The _is_ccxt helper must accept the production CcxtBroker class
    (registered under ``{exchange_id}:{credential_id}`` like
    ``binance:abc123``), not just brokers whose ``name`` happens to start
    with ``ccxt:``."""
    from showme.bots.ohlcv import _is_ccxt
    from showme.brokers.ccxt_broker import CcxtBroker

    fake_ex = MagicMock()
    fake_ex.fetch_ohlcv = AsyncMock(return_value=[])

    class _FakeCcxtModule:
        async_support = MagicMock()

    _FakeCcxtModule.async_support.binance = lambda kwargs: fake_ex
    broker = CcxtBroker(
        exchange_id="binance",
        credentials={},
        permissions=("read",),
        ccxt_module=_FakeCcxtModule,
    )
    # Production-key registration is what _is_ccxt must satisfy. The
    # constructed broker still sets ``self.name = "ccxt:binance"`` but
    # _is_ccxt must not depend on that prefix.
    assert _is_ccxt(broker) is True


def test_s3_is_ccxt_accepts_duck_typed_broker_with_ex():
    """The _ex.fetch_ohlcv fallback supports MagicMock-backed fakes
    registered without using the CcxtBroker class (the legacy test
    pattern)."""
    from showme.bots.ohlcv import _is_ccxt
    broker = MagicMock()
    # Explicitly stripped of the legacy name prefix so this test exercises
    # the structural path only.
    broker.name = "binance:cred-xyz"  # production-format key, no "ccxt:" prefix
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    assert _is_ccxt(broker) is True


def test_s3_is_ccxt_rejects_non_ccxt_broker():
    """Brokers without ``_ex.fetch_ohlcv`` and without the ``ccxt:``
    prefix must be rejected so the runner emits a clear BotRunnerError
    instead of silently failing to fetch."""
    from showme.bots.ohlcv import _is_ccxt
    broker = MagicMock(spec=["name"])  # no _ex attribute
    broker.name = "paper"
    assert _is_ccxt(broker) is False


@pytest.mark.asyncio
async def test_s3_runner_ohlcv_path_for_production_format_key(monkeypatch, tmp_path):
    """S3 regression: a broker registered under the production key
    ``binance:cred-xyz`` (no ``ccxt:`` prefix on the registry key) must
    still drive the OHLCV fetch path. This is the configuration that the
    real factory produces and the audit reported failing silently."""
    sid = _save_strategy(tmp_path, monkeypatch)
    # No ``ccxt:`` prefix on the broker.name; we rely on structural detection.
    broker = _register_fake_broker(
        "cred-1", name_prefix="binance:", exchange_id="binance",
    )
    broker.name = "binance:cred-1"  # explicit override (no ccxt: prefix)

    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="cred-1", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow",
    ))
    # Drive the production fetch_ohlcv path: monkeypatch only the helper
    # function so the structural detection still runs.
    monkeypatch.setattr(
        "showme.bots.runner.fetch_ohlcv",
        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()),
    )
    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    # We got a shadow-mode signal — proves the runner reached evaluate,
    # which means the broker was usable.
    assert signal is not None
    assert signal.action == "shadow"


# ── S4: start_all auto-disables revoked-trade live bots ──────────────────


@pytest.mark.asyncio
async def test_s4_start_all_disables_live_bot_with_revoked_trade_perm(
    monkeypatch, tmp_path,
):
    """S4 fix: when the sidecar restarts and finds an ``enabled=True``,
    ``mode="live"`` bot whose credential no longer has ``trade`` perm,
    the runner must auto-disable that bot (persist ``enabled=False``) and
    log a WARNING — NOT respawn the loop."""
    sid = _save_strategy(tmp_path, monkeypatch)
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="bad-cred", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))

    # _has_trade_perm probes CredentialStore.fresh().get(credential_id);
    # patch the helper to return False (revoked / unknown / vault failure).
    monkeypatch.setattr("showme.bots.runner._has_trade_perm",
                        lambda cid: False)

    runner = BotRunner()
    await runner.start_all(store)

    # Bot loop must NOT be running.
    assert not runner.is_running(bot.id)
    # Persisted state must now reflect enabled=False.
    reloaded = store.get(bot.id)
    assert reloaded.enabled is False
    await runner.aclose()


@pytest.mark.asyncio
async def test_s4_start_all_keeps_live_bot_with_valid_trade_perm(
    monkeypatch, tmp_path,
):
    """Negative complement to test_s4_*: with valid trade perm the live
    bot loop IS spawned."""
    sid = _save_strategy(tmp_path, monkeypatch)
    _register_fake_broker("good-cred")
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="good-cred", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
        tick_interval_seconds=3600,
    ))

    monkeypatch.setattr("showme.bots.runner._has_trade_perm",
                        lambda cid: True)
    monkeypatch.setattr(
        "showme.bots.runner.fetch_ohlcv",
        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()),
    )

    runner = BotRunner()
    await runner.start_all(store)
    assert runner.is_running(bot.id)
    # Still enabled on disk.
    assert store.get(bot.id).enabled is True
    await runner.aclose()


@pytest.mark.asyncio
async def test_s4_shadow_bot_is_not_subject_to_trade_perm_check(
    monkeypatch, tmp_path,
):
    """Shadow-mode bots never call submit_order; the trade-perm gate
    is irrelevant for them and must not auto-disable on restart."""
    sid = _save_strategy(tmp_path, monkeypatch)
    _register_fake_broker("any-cred")
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="any-cred", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow",
        tick_interval_seconds=3600,
    ))

    # Even with no trade perm, a shadow bot stays alive.
    monkeypatch.setattr("showme.bots.runner._has_trade_perm",
                        lambda cid: False)
    monkeypatch.setattr(
        "showme.bots.runner.fetch_ohlcv",
        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()),
    )

    runner = BotRunner()
    await runner.start_all(store)
    assert runner.is_running(bot.id)
    assert store.get(bot.id).enabled is True
    await runner.aclose()


# ── S8: per-bot asyncio.Lock guards tick + CRUD ──────────────────────────


@pytest.mark.asyncio
async def test_s8_get_lock_returns_stable_lock_per_bot_id():
    """_get_lock(bot_id) must be idempotent: same id → same lock."""
    runner = BotRunner()
    lock_a1 = runner._get_lock("a")
    lock_a2 = runner._get_lock("a")
    lock_b = runner._get_lock("b")
    assert lock_a1 is lock_a2
    assert lock_a1 is not lock_b


@pytest.mark.asyncio
async def test_s8_concurrent_tick_and_crud_no_signal_log_loss(monkeypatch, tmp_path):
    """S8 fix: a tick that's mid-flight when a CRUD save lands must NOT
    lose the appended signal. Pre-fix: route writes existing-without-
    signal back to disk and clobbers the tick's append.

    We simulate the race: run tick() and a concurrent "CRUD save"
    (model_copy with no new signal) inside ``asyncio.gather``. Both
    must serialize via the per-bot lock; after both complete the disk
    record must contain the tick's signal entry.
    """
    sid = _save_strategy(tmp_path, monkeypatch)
    _register_fake_broker("c-s8")
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c-s8", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow",
    ))
    monkeypatch.setattr(
        "showme.bots.runner.fetch_ohlcv",
        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()),
    )

    runner = BotRunner()
    # Acquire the runner's lock; tick will block on it.
    bot_lock = runner._get_lock(bot.id)

    async def _hold_then_save_no_signal():
        """Simulate a route handler that reads the bot, holds while a
        tick tries to run, then writes back without the signal."""
        async with bot_lock:
            rec_snap = store.get(bot.id)
            # Yield so the tick coroutine actually starts contending.
            await asyncio.sleep(0)
            # Crucial: this save uses the stale snapshot (no signal yet).
            # If the lock weren't held, the tick could land first and we'd
            # clobber its signal.
            store.save(rec_snap.model_copy(update={"symbol": "BTC/USDT"}))

    # Start both, then release the held lock by letting _hold_then_save
    # finish. Both must serialize and the final record must have 1 signal.
    crud_task = asyncio.create_task(_hold_then_save_no_signal())
    # Tiny yield so the CRUD task takes the lock first.
    await asyncio.sleep(0)
    tick_task = asyncio.create_task(runner.tick(bot.id, store))
    await asyncio.gather(crud_task, tick_task)

    reloaded = store.get(bot.id)
    # The lock ensured the tick ran AFTER the CRUD save. The tick's
    # append_signal therefore lands cleanly on the post-CRUD record.
    assert len(reloaded.signal_log) == 1, (
        f"signal_log was clobbered by concurrent CRUD; "
        f"got {len(reloaded.signal_log)} entries"
    )


@pytest.mark.asyncio
async def test_s8_enable_disable_acquire_per_bot_lock(monkeypatch, tmp_path):
    """``enable`` and ``disable`` must acquire the per-bot lock so a tick
    cannot run concurrently with an enabled-flag flip."""
    sid = _save_strategy(tmp_path, monkeypatch)
    _register_fake_broker("c-s8b")
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c-s8b", exchange_id="binance",
        symbol="BTC/USDT", enabled=False, mode="shadow",
        tick_interval_seconds=3600,
    ))
    runner = BotRunner()
    # Pre-acquire the lock externally to prove enable/disable contend.
    lock = runner._get_lock(bot.id)
    await lock.acquire()
    enable_task = asyncio.create_task(runner.enable(bot.id, store))
    # Give enable a chance to attempt and block on the lock.
    await asyncio.sleep(0)
    assert not enable_task.done(), "enable() did not block on per-bot lock"
    lock.release()
    rec = await enable_task
    assert rec.enabled is True
    await runner.disable(bot.id, store)
    await runner.aclose()


# ── H-13: Event.side comes from spec.position.side; runner picks SELL for short ──


@pytest.mark.asyncio
async def test_h13_short_strategy_entry_dispatches_sell(monkeypatch, tmp_path):
    """A side="short" strategy's entry event must dispatch a SELL order.
    Pre-fix: the runner hardcoded BUY-on-entry, so short strategies opened
    long positions."""
    sid = _save_strategy(tmp_path, monkeypatch,
                         sizing_kind="fixed_base", sizing_value=1.0,
                         side="short")
    broker = _register_fake_broker("c-h13")
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c-h13", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))
    monkeypatch.setattr(
        "showme.bots.runner.fetch_ohlcv",
        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()),
    )

    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    from showme.brokers import OrderSide
    assert signal is not None
    assert signal.action == "placed"
    args, kwargs = broker.submit_order.call_args
    assert kwargs["side"] == OrderSide.SELL


@pytest.mark.asyncio
async def test_h13_long_strategy_entry_dispatches_buy(monkeypatch, tmp_path):
    """Complement to the short test: long-side entry dispatches BUY."""
    sid = _save_strategy(tmp_path, monkeypatch,
                         sizing_kind="fixed_base", sizing_value=1.0,
                         side="long")
    broker = _register_fake_broker("c-h13l")
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c-h13l", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))
    monkeypatch.setattr(
        "showme.bots.runner.fetch_ohlcv",
        AsyncMock(side_effect=lambda *a, **k: _ohlcv_df()),
    )

    runner = BotRunner()
    signal = await runner.tick(bot.id, store)
    from showme.brokers import OrderSide
    assert signal is not None
    assert signal.action == "placed"
    args, kwargs = broker.submit_order.call_args
    assert kwargs["side"] == OrderSide.BUY


def test_h13_evaluate_event_carries_side():
    """The evaluator must thread spec.position.side onto each Event."""
    from showme.strategies.evaluate import evaluate
    from showme.strategies.spec import Position, Rule, StrategySpec

    spec = StrategySpec(
        name="t",
        entry_rules=[Rule(kind="greater_than", left="close", right="literal:5")],
        exit_rules=[Rule(kind="less_than", left="close", right="literal:5")],
        position=Position(side="short"),
    )
    df = pd.DataFrame({
        "open": [1, 6, 7, 3], "high": [1.5, 6.5, 7.5, 3.5],
        "low": [0.5, 5.5, 6.5, 2.5], "close": [1, 6, 7, 3],
        "volume": [1000] * 4,
    }, index=pd.date_range("2026-05-22", periods=4, freq="h"))

    events = evaluate(spec, df)
    assert events, "expected at least one event"
    assert all(e.side == "short" for e in events)
    # Same kind sequence as a long strategy: entry then exit.
    kinds = [e.kind for e in events]
    assert kinds == ["entry", "exit"]


@pytest.mark.asyncio
async def test_runner_validates_strategy_against_catalog(monkeypatch, tmp_path):
    """If the strategy has an unknown indicator not present in the catalog,
    the runner tick loop should skip it and log a validation error."""
    from showme.strategies.spec import StrategySpec, IndicatorRef, Rule
    from showme.bots.store import BotStore
    from showme.bots.record import BotRecord
    from showme.bots.runner import BotRunner

    spec = StrategySpec(
        name="tampered_strat",
        timeframe="1h",
        indicators=[
            IndicatorRef(alias="ind_1", id="super_duper_indicator", params={})
        ],
        entry_rules=[Rule(kind="greater_than", left="ind_1", right="literal:5")],
        exit_rules=[Rule(kind="less_than", left="ind_1", right="literal:5")],
    )
    from showme.strategies.store import StrategyStore
    sstore = StrategyStore(tmp_path / "strategies")
    monkeypatch.setattr("showme.strategies.store.StrategyStore.fresh", lambda: sstore)
    sstore.save(spec)

    bot_store = BotStore(tmp_path / "bots")
    bot = bot_store.save(BotRecord(
        strategy_id=spec.id, credential_id="fake-cred", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow", timeframe="1h"
    ))

    _register_fake_broker("fake-cred")

    runner = BotRunner()
    signal = await runner.tick(bot.id, bot_store)
    assert signal is not None
    assert signal.action == "skipped"
    assert "strategy validation failed" in signal.error
    assert "super_duper_indicator" in signal.error
