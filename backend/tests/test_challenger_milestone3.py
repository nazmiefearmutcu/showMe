import pytest
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient

from showme.server import build_app
from showme.bots.record import BotRecord, SignalEntry
from showme.bots.runner import BotRunner
from showme.bots.store import BotStore
from showme.strategies.store import StrategyStore
from showme.brokers import CredentialStore

_STRATEGY_BODY = {
    "name": "Challenger RSI (test fixture)",
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

@pytest.mark.asyncio
async def test_verify_credential_delete_halts_bots(client, seeded):
    # Verify: Deleting an exchange credential successfully halts all active bots linked to it
    # and appends stopped/error status to signal logs.
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
    
    from httpx import AsyncClient
    import httpx
    if hasattr(httpx, "ASGITransport"):
        transport = httpx.ASGITransport(app=client.app)
        ac_kwargs = {"transport": transport}
    else:
        ac_kwargs = {"app": client.app}
    async with AsyncClient(base_url="http://test", headers={"X-ShowMe-Token": "test-token"}, **ac_kwargs) as ac:
        r = await ac.post("/api/bots", json=seeded)
        bot_id = r.json()["id"]
        
        # Enable bot
        store = BotStore.fresh()
        await runner.enable(bot_id, store)
        
        assert runner.is_running(bot_id) is True
        assert bot_id in runner._locks
        
        # Delete credential with force=true
        d = await ac.delete(f"/api/exchange/credentials/{cid}?force=true")
        assert d.status_code == 200
        
        await asyncio.sleep(0.1)
        
        # Bot must be disabled, task halted, and signal log appended with stopped/error: exchange credential deleted
        g = await ac.get(f"/api/bots/{bot_id}")
        assert g.json()["enabled"] is False
        assert runner.is_running(bot_id) is False
        
        signals = g.json()["signal_log"]
        assert len(signals) > 0
        assert signals[-1]["error"] == "stopped/error: exchange credential deleted"
        assert bot_id not in runner._locks

@pytest.mark.asyncio
async def test_verify_strategy_delete_halts_bots(client, seeded):
    # Verify: Deleting a strategy successfully halts all active bots linked to it
    # and appends stopped/error status to signal logs.
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
    
    from httpx import AsyncClient
    import httpx
    if hasattr(httpx, "ASGITransport"):
        transport = httpx.ASGITransport(app=client.app)
        ac_kwargs = {"transport": transport}
    else:
        ac_kwargs = {"app": client.app}
    async with AsyncClient(base_url="http://test", headers={"X-ShowMe-Token": "test-token"}, **ac_kwargs) as ac:
        r = await ac.post("/api/bots", json=seeded)
        bot_id = r.json()["id"]
        
        # Enable bot
        store = BotStore.fresh()
        await runner.enable(bot_id, store)
        
        assert runner.is_running(bot_id) is True
        assert bot_id in runner._locks
        
        # Delete strategy with force=true
        sid = seeded["strategy_id"]
        d = await ac.delete(f"/api/strategies/{sid}?force=true")
        assert d.status_code == 200
        
        await asyncio.sleep(0.1)
        
        # Bot must be disabled, task halted, and signal log appended with stopped/error: strategy deleted
        g = await ac.get(f"/api/bots/{bot_id}")
        assert g.json()["enabled"] is False
        assert runner.is_running(bot_id) is False
        
        signals = g.json()["signal_log"]
        assert len(signals) > 0
        assert signals[-1]["error"] == "stopped/error: strategy deleted"
        assert bot_id not in runner._locks

def test_verify_put_bots_reverts_cumulative_funding_pnl_and_preserves_created_at(client, seeded):
    # Verify: The PUT bots route rejects updates to cumulative_funding_pnl (reverting to existing DB value)
    # and preserves created_at timestamp.
    r = client.post("/api/bots", json=seeded)
    assert r.status_code == 200
    bot_id = r.json()["id"]
    
    # Get original bot record
    g = client.get(f"/api/bots/{bot_id}")
    orig_created_at = g.json()["created_at"]
    assert g.json()["cumulative_funding_pnl"] == 0.0
    
    # Simulate DB having a different cumulative_funding_pnl (e.g. 15.5)
    store = BotStore.fresh()
    rec = store.get(bot_id)
    rec = rec.model_copy(update={"cumulative_funding_pnl": 15.5})
    store.save(rec)
    
    # Send PUT request with new values
    p = client.put(
        f"/api/bots/{bot_id}",
        json={
            **seeded,
            "cumulative_funding_pnl": 999.9,  # attacker trying to inject
            "created_at": "2000-01-01T00:00:00Z"  # attacker trying to overwrite
        }
    )
    assert p.status_code == 200
    body = p.json()
    
    # Verify cumulative_funding_pnl is reverted to DB value (15.5) and created_at is preserved
    assert body["cumulative_funding_pnl"] == 15.5
    assert body["created_at"] == orig_created_at

@pytest.mark.asyncio
async def test_verify_startup_verification_disables_orphan_bots_and_pops_locks(client, seeded):
    # Verify: Startup verification auto-disables orphan bots and pops locks.
    from showme.bots.lifespan import get_runner
    runner = get_runner()
    
    # Create bot
    r = client.post("/api/bots", json=seeded)
    bot_id = r.json()["id"]
    
    # Manually mark bot enabled in store to simulate startup state
    store = BotStore.fresh()
    rec = store.get(bot_id)
    rec = rec.model_copy(update={"enabled": True})
    store.save(rec)
    
    # Simulate orphan bot by deleting the strategy directly from store (bypassing cascade delete)
    StrategyStore.fresh().delete(seeded["strategy_id"])
    
    # Ensure lock exists in runner (simulate some lock activity or create it)
    runner._get_lock(bot_id)
    assert bot_id in runner._locks
    
    # Run startup verification (start_all)
    await runner.start_all(store)
    
    # Check that bot was disabled and gets the error signal
    rec_after = store.get(bot_id)
    assert rec_after.enabled is False
    assert len(rec_after.signal_log) > 0
    assert rec_after.signal_log[-1].error == "stopped/error: strategy deleted"
    
    # Verify that the lock was popped (no longer in runner._locks)
    assert bot_id not in runner._locks
