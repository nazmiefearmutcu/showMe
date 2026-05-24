"""Q4 audit C2: broker-confirmed fill price threads into SignalEntry / ClosedTrade.

Before this fix, the runner used ``last_event.price`` (the bar's close at
evaluate-time) for both legs of pairing — even when the broker came back
with a different ``avg_fill_price``. PnL therefore systematically ignored
slippage.
"""
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


def _ohlcv_df(closes=(99, 99, 99, 99, 99, 105)) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2026-05-22", periods=n, freq="h")
    return pd.DataFrame({
        "open": closes, "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes], "close": list(closes),
        "volume": [1000] * n,
    }, index=idx)


def _setup_strategy(tmp_path: Path, monkeypatch) -> str:
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    from showme.strategies.store import StrategyStore
    from showme.strategies.spec import StrategySpec, Rule
    spec = StrategySpec(
        name="fill_price_thru",
        entry_rules=[Rule(kind="crosses_above", left="close", right="literal:100")],
        exit_rules=[],
    )
    return StrategyStore.fresh().save(spec).id


def _register_broker_with_fill(credential_id: str, *, fill_price: float, filled_qty: float):
    from showme.brokers import factory as factory_mod
    order = MagicMock()
    order.id = "order-fill"
    order.filled_quantity = filled_qty
    order.quantity = filled_qty
    order.avg_fill_price = fill_price
    broker = MagicMock()
    broker.name = f"ccxt:binance:{credential_id}"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    broker.submit_order = AsyncMock(return_value=order)
    broker.account = AsyncMock(return_value={"equity": 10_000.0})
    factory_mod._REGISTRY[f"binance:{credential_id}"] = lambda b=broker: b
    factory_mod._DYNAMIC[credential_id] = f"binance:{credential_id}"
    return broker


@pytest.mark.asyncio
async def test_signal_entry_records_fill_price_in_live_mode(monkeypatch, tmp_path):
    sid = _setup_strategy(tmp_path, monkeypatch)
    # Signal price will be 105 (last close), broker fills at 105.5 (slippage).
    _register_broker_with_fill("c1", fill_price=105.5, filled_qty=1.0)
    monkeypatch.setattr(
        "showme.bots.runner.fetch_ohlcv",
        AsyncMock(side_effect=lambda *a, **kw: _ohlcv_df()),
    )
    monkeypatch.setattr("showme.bots.runner._has_trade_perm", lambda _c: True)

    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c1", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))

    runner = BotRunner()
    entry = await runner.tick(bot.id, store)
    assert entry is not None
    assert entry.action == "placed"
    assert entry.fill_price == pytest.approx(105.5)
    # Signal price is the bar close (105); fill_price differs.
    assert entry.price == pytest.approx(105.0)
    # H17 — qty was persisted.
    assert entry.qty == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_fill_price_used_in_closed_trade_pairing(monkeypatch, tmp_path):
    """Once the bot is in_position, an exit should pair against the entry's
    fill_price — not the bar close at entry-time."""
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    from showme.strategies.store import StrategyStore
    from showme.strategies.spec import StrategySpec, Rule
    spec = StrategySpec(
        name="entry_exit",
        entry_rules=[Rule(kind="crosses_above", left="close", right="literal:100")],
        exit_rules=[Rule(kind="less_than", left="close", right="literal:99.5")],
    )
    sid = StrategyStore.fresh().save(spec).id

    from showme.brokers import factory as factory_mod
    # Entry order fills at 105.5; exit order fills at 99.0 (worse than signal).
    entry_order = MagicMock(id="o1", filled_quantity=1.0, quantity=1.0,
                            avg_fill_price=105.5)
    exit_order = MagicMock(id="o2", filled_quantity=1.0, quantity=1.0,
                           avg_fill_price=99.0)
    broker = MagicMock()
    broker.name = "ccxt:binance:c1"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    broker.account = AsyncMock(return_value={"equity": 10_000.0})
    broker.submit_order = AsyncMock(side_effect=[entry_order, exit_order])
    broker.close_position = AsyncMock(return_value=exit_order)
    factory_mod._REGISTRY["binance:c1"] = lambda: broker
    factory_mod._DYNAMIC["c1"] = "binance:c1"

    df_entry = _ohlcv_df(closes=(99, 99, 99, 99, 99, 105))
    df_exit = _ohlcv_df(closes=(99, 99, 99, 99, 99, 99))  # close=99 triggers exit
    df_iter = iter([df_entry, df_exit])
    monkeypatch.setattr(
        "showme.bots.runner.fetch_ohlcv",
        AsyncMock(side_effect=lambda *a, **kw: next(df_iter)),
    )
    monkeypatch.setattr("showme.bots.runner._has_trade_perm", lambda _c: True)

    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id=sid, credential_id="c1", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="live",
    ))

    runner = BotRunner()
    await runner.tick(bot.id, store)  # entry
    await runner.tick(bot.id, store)  # exit

    rec = store.get(bot.id)
    assert len(rec.closed_trades_log) == 1
    ct = rec.closed_trades_log[0]
    # Q4 audit C2: pairing uses BROKER fill prices (105.5, 99.0), not signal prices.
    assert ct.entry_price == pytest.approx(105.5)
    assert ct.exit_price == pytest.approx(99.0)
    # Long, qty=1, entry-exit = 105.5 - 99.0 = -6.5
    assert ct.pnl == pytest.approx(-6.5)
