"""Q4 audit C6: partial-fill drift in live mode.

If the bot thinks it has 1.0 BTC but the broker only filled 0.3 BTC,
subsequent close orders submitted at 1.0 BTC will leave 0.3 BTC short
exposure (because the broker fills another 0.3 BTC OPEN order).

The runner must persist the actual ``filled_quantity`` on the SignalEntry
so pairing uses the real qty, and the dispatch fallback uses
broker.close_position so a paper / custom adapter without close_position
gets a clear diagnostic.
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


def _df(closes=(99, 99, 99, 99, 99, 105)) -> pd.DataFrame:
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
        name="partial_fill_test",
        entry_rules=[Rule(kind="crosses_above", left="close", right="literal:100")],
        exit_rules=[],
    )
    return StrategyStore.fresh().save(spec).id


@pytest.mark.asyncio
async def test_partial_fill_persists_actual_filled_qty(monkeypatch, tmp_path):
    sid = _setup_strategy(tmp_path, monkeypatch)
    from showme.brokers import factory as factory_mod
    # Bot requests qty=1.0, broker only fills 0.3.
    order = MagicMock(
        id="partial-1", filled_quantity=0.3, quantity=1.0,
        avg_fill_price=105.0,
    )
    broker = MagicMock()
    broker.name = "ccxt:binance:c1"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    broker.submit_order = AsyncMock(return_value=order)
    broker.account = AsyncMock(return_value={"equity": 10_000.0})
    factory_mod._REGISTRY["binance:c1"] = lambda: broker
    factory_mod._DYNAMIC["c1"] = "binance:c1"

    monkeypatch.setattr(
        "showme.bots.runner.fetch_ohlcv",
        AsyncMock(side_effect=lambda *a, **kw: _df()),
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
    # The entry must capture the ACTUAL filled qty (0.3), not the request (1.0).
    assert entry.qty == pytest.approx(0.3)
    # Diagnostic must surface partial fill on the error field.
    assert entry.error is not None
    assert "partial" in entry.error.lower()


@pytest.mark.asyncio
async def test_zero_fill_downgrades_to_skipped(monkeypatch, tmp_path):
    sid = _setup_strategy(tmp_path, monkeypatch)
    from showme.brokers import factory as factory_mod
    order = MagicMock(
        id="zero-fill", filled_quantity=0.0, quantity=1.0,
        avg_fill_price=None,
    )
    broker = MagicMock()
    broker.name = "ccxt:binance:c1"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    broker.submit_order = AsyncMock(return_value=order)
    broker.account = AsyncMock(return_value={"equity": 10_000.0})
    factory_mod._REGISTRY["binance:c1"] = lambda: broker
    factory_mod._DYNAMIC["c1"] = "binance:c1"

    monkeypatch.setattr(
        "showme.bots.runner.fetch_ohlcv",
        AsyncMock(side_effect=lambda *a, **kw: _df()),
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
    # IOC unfilled → skipped (no exposure).
    assert entry.action == "skipped"
    assert "unfilled" in (entry.error or "").lower()
