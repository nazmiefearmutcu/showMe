import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient

from showme.server import build_app
from showme.bots.record import BotRecord, SignalEntry
from showme.bots.runner import BotRunner
from showme.bots.store import BotStore
from showme.strategies.store import StrategyStore
from showme.strategies.spec import StrategySpec, Rule
from showme.brokers import CredentialStore

_STRATEGY_BODY = {
    "name": "RSI mean revert (test fixture)",
    "indicators": [{"alias": "rsi14", "id": "rsi", "params": {"period": 14}}],
    "entry_rules": [{"kind": "crosses_below", "left": "rsi14", "right": "literal:30"}],
    "exit_rules": [{"kind": "crosses_above", "left": "rsi14", "right": "literal:70"}],
    "exit_logic": "any",
}

@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    
    # Reset factory module state
    from showme.brokers import factory as factory_mod
    factory_mod._DYNAMIC.clear()
    factory_mod._LIVE.clear()
    for name in list(factory_mod._REGISTRY.keys()):
        if ":" in name:
            factory_mod._REGISTRY.pop(name, None)
            
    # Reset bot lifespan singleton
    import showme.bots.lifespan as lifespan
    lifespan._RUNNER = None
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})

def _seed_strategy(client) -> str:
    r = client.post("/api/strategies", json=_STRATEGY_BODY)
    assert r.status_code == 200, r.text
    return r.json()["id"]

def _seed_credential() -> str:
    store = CredentialStore.fresh()
    rec = store.add(
        exchange_id="binance",
        account_label="main",
        secrets={"apiKey": "k", "secret": "s"},
        permissions=("read", "trade"),
    )
    return rec.id

@pytest.fixture
def seeded(client):
    sid = _seed_strategy(client)
    cid = _seed_credential()
    return {
        "strategy_id": sid,
        "credential_id": cid,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "tick_interval_seconds": 900,
    }

def test_put_security_cumulative_funding_pnl_and_created_at(client, seeded):
    # Create bot
    r = client.post("/api/bots", json=seeded)
    assert r.status_code == 200, r.text
    bot_id = r.json()["id"]
    
    # Verify default cumulative_funding_pnl is 0.0 and get original created_at
    g = client.get(f"/api/bots/{bot_id}")
    assert g.status_code == 200
    orig_created_at = g.json()["created_at"]
    assert g.json()["cumulative_funding_pnl"] == 0.0
    
    # Manually modify cumulative_funding_pnl in store (simulate running bot accumulating funding pnl)
    store = BotStore.fresh()
    rec = store.get(bot_id)
    rec = rec.model_copy(update={"cumulative_funding_pnl": 42.5})
    store.save(rec)
    
    # Call PUT on the bot trying to change it, or other fields
    p = client.put(
        f"/api/bots/{bot_id}",
        json={
            **seeded,
            "symbol": "ETH/USDT",
            "cumulative_funding_pnl": 999.0, # clients cannot overwrite it
            "created_at": "1970-01-01T00:00:00Z" # clients cannot overwrite it
        }
    )
    assert p.status_code == 200, p.text
    body = p.json()
    assert body["symbol"] == "ETH/USDT"
    # Verify cumulative_funding_pnl and created_at are preserved from the existing store record!
    assert body["cumulative_funding_pnl"] == 42.5
    assert body["created_at"] == orig_created_at

@pytest.mark.asyncio
async def test_exchange_credential_cascade_delete_halts_bots(client, seeded):
    from showme.bots.lifespan import get_runner
    runner = get_runner()
    
    # Register mock broker
    from showme.brokers import factory as factory_mod
    broker = MagicMock()
    broker.name = "ccxt:binance"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    cid = seeded["credential_id"]
    factory_mod._REGISTRY[f"binance:{cid}"] = lambda b=broker: b
    factory_mod._DYNAMIC[cid] = f"binance:{cid}"
    
    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(transport=ASGITransport(app=client.app), base_url="http://test", headers={"X-ShowMe-Token": "test-token"}) as ac:
        # Create bot and enable it
        r = await ac.post("/api/bots", json=seeded)
        bot_id = r.json()["id"]
        
        # Enable directly via runner so the task runs on the test event loop
        store = BotStore.fresh()
        await runner.enable(bot_id, store)
        
        # Set runner's task state to active
        assert runner.is_running(bot_id) is True
        # Ensure a lock is cached in locks
        assert bot_id in runner._locks
        
        # Delete exchange credential using ?force=true
        d = await ac.delete(f"/api/exchange/credentials/{cid}?force=true")
        assert d.status_code == 200, d.text
        
        # Wait briefly for the task cancellation/cascade task to execute
        import asyncio
        await asyncio.sleep(0.1)
        
        # Check that bot is disabled and has correct skipped SignalEntry in signal_log
        g = await ac.get(f"/api/bots/{bot_id}")
        assert g.json()["enabled"] is False
        
        signals = g.json()["signal_log"]
        assert len(signals) > 0
        last_signal = signals[-1]
        assert last_signal["bar_index"] == -1
        assert last_signal["action"] == "skipped"
        assert last_signal["error"] == "stopped/error: exchange credential deleted"
        
        # Verify lock is evicted from runner._locks
        assert bot_id not in runner._locks

@pytest.mark.asyncio
async def test_strategy_cascade_delete_halts_bots(client, seeded):
    from showme.bots.lifespan import get_runner
    runner = get_runner()
    
    # Register mock broker
    from showme.brokers import factory as factory_mod
    broker = MagicMock()
    broker.name = "ccxt:binance"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    cid = seeded["credential_id"]
    factory_mod._REGISTRY[f"binance:{cid}"] = lambda b=broker: b
    factory_mod._DYNAMIC[cid] = f"binance:{cid}"
    
    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(transport=ASGITransport(app=client.app), base_url="http://test", headers={"X-ShowMe-Token": "test-token"}) as ac:
        # Create bot and enable it
        r = await ac.post("/api/bots", json=seeded)
        bot_id = r.json()["id"]
        
        # Enable directly via runner so the task runs on the test event loop
        store = BotStore.fresh()
        await runner.enable(bot_id, store)
        
        assert runner.is_running(bot_id) is True
        assert bot_id in runner._locks
        
        # Delete strategy using ?force=true
        sid = seeded["strategy_id"]
        d = await ac.delete(f"/api/strategies/{sid}?force=true")
        assert d.status_code == 200, d.text
        
        import asyncio
        await asyncio.sleep(0.1)
        
        # Check bot state
        g = await ac.get(f"/api/bots/{bot_id}")
        assert g.json()["enabled"] is False
        
        signals = g.json()["signal_log"]
        assert len(signals) > 0
        last_signal = signals[-1]
        assert last_signal["bar_index"] == -1
        assert last_signal["action"] == "skipped"
        assert last_signal["error"] == "stopped/error: strategy deleted"
        
        # Verify lock is evicted
        assert bot_id not in runner._locks

@pytest.mark.asyncio
async def test_start_all_disables_missing_strategy_bots(client, seeded):
    from showme.bots.lifespan import get_runner
    runner = get_runner()
    
    # Create bot
    r = client.post("/api/bots", json=seeded)
    bot_id = r.json()["id"]
    
    # Manually mark bot enabled in store without starting it (e.g. startup scenario)
    store = BotStore.fresh()
    rec = store.get(bot_id)
    rec = rec.model_copy(update={"enabled": True})
    store.save(rec)
    
    # Delete the strategy directly via store so we bypass cascade delete
    StrategyStore.fresh().delete(seeded["strategy_id"])
    
    # Call start_all
    await runner.start_all(store)
    
    # Check that bot was disabled and gets the error signal
    rec_after = store.get(bot_id)
    assert rec_after.enabled is False
    assert len(rec_after.signal_log) > 0
    assert rec_after.signal_log[-1].error == "stopped/error: strategy deleted"


def test_reenabling_bot_with_missing_strategy_blocked(client, seeded):
    # Register mock broker
    from showme.brokers import factory as factory_mod
    from unittest.mock import MagicMock, AsyncMock
    broker = MagicMock()
    broker.name = "ccxt:binance"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    cid = seeded["credential_id"]
    factory_mod._REGISTRY[f"binance:{cid}"] = lambda b=broker: b
    factory_mod._DYNAMIC[cid] = f"binance:{cid}"

    # Create bot
    r = client.post("/api/bots", json=seeded)
    assert r.status_code == 200, r.text
    bot_id = r.json()["id"]

    # Delete the strategy so it's missing
    sid = seeded["strategy_id"]
    d = client.delete(f"/api/strategies/{sid}?force=true")
    assert d.status_code == 200, d.text

    # Attempt to enable the bot again
    e = client.post(f"/api/bots/{bot_id}/enable")
    
    # We expect this to be blocked (return 400 Bad Request)
    assert e.status_code == 400, f"Expected 400 when enabling bot with missing strategy, got {e.status_code}"
    assert "strategy" in e.text.lower()


