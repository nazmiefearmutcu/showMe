"""BotRunner tick + lifecycle tests with mocked broker + evaluator."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from showme.bots.record import BotRecord, SignalEntry
from showme.bots.runner import BotRunner
from showme.bots.store import BotStore


@pytest.fixture(autouse=True)
def _isolate_factory():
    from showme.brokers import factory as factory_mod
    snap_reg = dict(factory_mod._REGISTRY)
    snap_dyn = dict(factory_mod._DYNAMIC)
    snap_live = dict(factory_mod._LIVE)
    yield
    factory_mod._REGISTRY.clear(); factory_mod._REGISTRY.update(snap_reg)
    factory_mod._DYNAMIC.clear(); factory_mod._DYNAMIC.update(snap_dyn)
    factory_mod._LIVE.clear(); factory_mod._LIVE.update(snap_live)


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
