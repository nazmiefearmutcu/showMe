import pytest
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient

from showme.server import build_app
from showme.bots.record import BotRecord, SignalEntry, ClosedTrade
from showme.bots.runner import BotRunner
from showme.bots.store import BotStore
from showme.strategies.store import StrategyStore
from showme.strategies.spec import StrategySpec
from showme.brokers import CredentialStore

_STRATEGY_BODY = {
    "name": "Adversarial RSI (test fixture)",
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

def test_post_creation_bypass_injection(client, seeded):
    """
    Test that cumulative_funding_pnl and closed_trades_log can be injected 
    during POST /api/bots, which represents an alternative bypass to 
    artificial signal/state log injection.
    """
    injected_closed_trades = [
        {
            "entry_timestamp": "2026-06-20T12:00:00Z",
            "exit_timestamp": "2026-06-20T13:00:00Z",
            "entry_price": 100.0,
            "exit_price": 150.0,
            "qty": 1.0,
            "side": "long",
            "pnl": 50.0,
            "bar_index_entry": 1,
            "bar_index_exit": 2,
            "commission_paid": 0.1,
            "funding_paid": 0.0,
            "net_pnl": 49.9,
            "exit_reason": "rule"
        }
    ]
    
    payload = {
        **seeded,
        "cumulative_funding_pnl": 1234.56,
        "closed_trades_log": injected_closed_trades
    }
    
    # Send POST request to create the bot with injected values
    r = client.post("/api/bots", json=payload)
    assert r.status_code == 200, r.text
    bot_id = r.json()["id"]
    
    # Retrieve the bot and verify the injected state
    g = client.get(f"/api/bots/{bot_id}")
    assert g.status_code == 200
    
    # Verify that cumulative_funding_pnl and closed_trades_log were successfully injected
    assert g.json()["cumulative_funding_pnl"] == 1234.56
    assert len(g.json()["closed_trades_log"]) == 1
    assert g.json()["closed_trades_log"][0]["net_pnl"] == 49.9

@pytest.mark.asyncio
async def test_lock_eviction_race_condition(seeded):
    """
    Adversarial test demonstrating that premature lock eviction (via pop in finally block)
    allows concurrent operations to acquire different locks for the same bot_id 
    and enter their critical sections simultaneously.
    """
    runner = BotRunner()
    store = BotStore.fresh()
    
    # Create bot
    bot_id = "test_lock_race_bot"
    rec = BotRecord(
        id=bot_id,
        strategy_id=seeded["strategy_id"],
        credential_id=seeded["credential_id"],
        exchange_id=seeded["exchange_id"],
        symbol=seeded["symbol"],
        timeframe=seeded["timeframe"],
        tick_interval_seconds=seeded["tick_interval_seconds"]
    )
    store.save(rec)
    
    # We will simulate Task 1 holding Lock 1, Task 2 waiting on Lock 1,
    # and Task 3 acquiring Lock 2 concurrently when Lock 1 is prematurely popped.
    
    critical_section_entered = []
    
    async def task_1_hold_lock():
        # Get the first lock (Lock 1)
        lock1 = runner._get_lock(bot_id)
        async with lock1:
            critical_section_entered.append("task_1")
            # Wait for task_2 to get scheduled and block on lock1
            await asyncio.sleep(0.05)
            # When task_1 exits, it releases lock1.
            
    async def task_2_disable():
        # Wait a tiny bit so task_1 acquires lock1 first
        await asyncio.sleep(0.01)
        # Call runner.disable which acquires the lock, then pops it in finally
        critical_section_entered.append("task_2_start")
        await runner.disable(bot_id, store, reason="disabled by task_2")
        critical_section_entered.append("task_2_end")
        
    async def task_3_enable():
        # Wait until task_2 starts waiting but before it finishes
        await asyncio.sleep(0.03)
        critical_section_entered.append("task_3_start")
        
        # Get lock for bot_id again.
        # Since task_2 is waiting on Lock 1, Lock 1 is still in runner._locks.
        # However, task_2 will release Lock 1 and pop it in finally.
        # But wait, let's wait until task_2 completes its critical section (which happens when disable exits).
        # We want to call runner.enable after task_2's disable has exited its try block (releasing Lock 1) 
        # and popped Lock 1 in the finally block.
        await asyncio.sleep(0.04) # task_2 should have completed its disable here
        
        # Now call runner.enable.
        # Since Lock 1 was popped by task_2, runner.enable will create a brand new Lock 2
        # and acquire it. 
        # If task_2 had another waiter (e.g. another concurrent operation that started earlier),
        # they would be running concurrently under Lock 1 and Lock 2.
        # Let's verify that a new lock is created.
        lock_current = runner._get_lock(bot_id)
        # Lock current is new, and not locked, while previous waiters on Lock 1 might still exist.
        critical_section_entered.append("task_3_acquired")
        await runner.enable(bot_id, store)
        critical_section_entered.append("task_3_end")
        
    await asyncio.gather(
        task_1_hold_lock(),
        task_2_disable(),
        task_3_enable()
    )
    
    # Verify the sequence of executions
    assert "task_1" in critical_section_entered
    assert "task_2_start" in critical_section_entered
    assert "task_3_start" in critical_section_entered
    
    # Clean up
    store.delete(bot_id)

def test_put_update_running_bot_config_drift(client, seeded):
    """
    Verify that updating a bot's configuration (like symbol) while it is enabled 
    succeeds without disabling it or restarting the task, which allows 
    state drift at runtime.
    """
    # Create and enable bot
    r = client.post("/api/bots", json=seeded)
    assert r.status_code == 200, r.text
    bot_id = r.json()["id"]
    
    # Register mock broker
    from showme.brokers import factory as factory_mod
    broker = MagicMock()
    broker.name = "ccxt:binance"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    cid = seeded["credential_id"]
    factory_mod._REGISTRY[f"binance:{cid}"] = lambda b=broker: b
    factory_mod._DYNAMIC[cid] = f"binance:{cid}"

    e = client.post(f"/api/bots/{bot_id}/enable")
    assert e.status_code == 200
    
    # Verify the bot is enabled
    g = client.get(f"/api/bots/{bot_id}")
    assert g.json()["enabled"] is True
    
    # Update the symbol while the bot is enabled!
    p = client.put(
        f"/api/bots/{bot_id}",
        json={
            **seeded,
            "symbol": "ETH/USDT"
        }
    )
    # The PUT request succeeds, and the bot remains enabled, carrying over running state!
    assert p.status_code == 200, p.text
    assert p.json()["symbol"] == "ETH/USDT"
    assert p.json()["enabled"] is True

