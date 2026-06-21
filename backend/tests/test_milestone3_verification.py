import pytest
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient
import httpx

from showme.server import build_app
from showme.bots.record import BotRecord, SignalEntry
from showme.bots.runner import BotRunner
from showme.bots.store import BotStore
from showme.strategies.store import StrategyStore
from showme.strategies.spec import StrategySpec
from showme.brokers import CredentialStore

_STRATEGY_BODY = {
    "name": "Verification RSI (test fixture)",
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
    
    # Register broker mock so bot can be enabled
    from showme.brokers import factory as factory_mod
    broker = MagicMock()
    broker.name = "ccxt:binance"
    broker.aclose = AsyncMock() # Ensure aclose is a coroutine function
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    factory_mod._REGISTRY[f"binance:{cid}"] = lambda b=broker: b
    factory_mod._DYNAMIC[cid] = f"binance:{cid}"

    return {
        "strategy_id": sid,
        "credential_id": cid,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "tick_interval_seconds": 900,
    }

def _get_async_client(app):
    headers = {"X-ShowMe-Token": "test-token"}
    if hasattr(httpx, "ASGITransport"):
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers)
    else:
        return httpx.AsyncClient(app=app, base_url="http://test", headers=headers)

@pytest.mark.asyncio
async def test_delete_credential_cascades_and_halts_bots(client, seeded):
    """
    Deleting an exchange credential successfully halts all active bots linked to it
    and appends stopped/error status to signal logs.
    """
    from showme.bots.lifespan import get_runner
    runner = get_runner()
    cid = seeded["credential_id"]

    async with _get_async_client(client.app) as ac:
        # 1. Create the bot
        r = await ac.post("/api/bots", json=seeded)
        assert r.status_code == 200, r.text
        bot_id = r.json()["id"]

        # 2. Enable the bot directly in runner to run on the test event loop
        store = BotStore.fresh()
        await runner.enable(bot_id, store)

        # Confirm it is running and has lock cached
        assert runner.is_running(bot_id) is True
        assert bot_id in runner._locks

        # 3. Delete the credential with force=true
        d = await ac.delete(f"/api/exchange/credentials/{cid}?force=true")
        assert d.status_code == 200, d.text

        # Wait briefly for cascade tasks
        await asyncio.sleep(0.1)

        # 4. Verify bot is disabled
        g = await ac.get(f"/api/bots/{bot_id}")
        assert g.status_code == 200
        assert g.json()["enabled"] is False

        # 5. Verify the runner halted the bot
        assert runner.is_running(bot_id) is False

        # 6. Verify the signal logs contains stopped/error status
        signals = g.json()["signal_log"]
        assert len(signals) > 0
        last_signal = signals[-1]
        assert last_signal["action"] == "skipped"
        assert last_signal["error"] == "stopped/error: exchange credential deleted"

        # 7. Verify lock is evicted from runner._locks
        assert bot_id not in runner._locks

@pytest.mark.asyncio
async def test_delete_strategy_cascades_and_halts_bots(client, seeded):
    """
    Deleting a strategy successfully halts all active bots linked to it
    and appends stopped/error status to signal logs.
    """
    from showme.bots.lifespan import get_runner
    runner = get_runner()
    sid = seeded["strategy_id"]

    async with _get_async_client(client.app) as ac:
        # 1. Create the bot
        r = await ac.post("/api/bots", json=seeded)
        assert r.status_code == 200, r.text
        bot_id = r.json()["id"]

        # 2. Enable the bot directly in runner
        store = BotStore.fresh()
        await runner.enable(bot_id, store)

        # Confirm it is running and lock is cached
        assert runner.is_running(bot_id) is True
        assert bot_id in runner._locks

        # 3. Delete the strategy with force=true
        d = await ac.delete(f"/api/strategies/{sid}?force=true")
        assert d.status_code == 200, d.text

        # Wait briefly for cascade tasks
        await asyncio.sleep(0.1)

        # 4. Verify bot is disabled
        g = await ac.get(f"/api/bots/{bot_id}")
        assert g.status_code == 200
        assert g.json()["enabled"] is False

        # 5. Verify the runner halted the bot
        assert runner.is_running(bot_id) is False

        # 6. Verify the signal logs contains stopped/error status
        signals = g.json()["signal_log"]
        assert len(signals) > 0
        last_signal = signals[-1]
        assert last_signal["action"] == "skipped"
        assert last_signal["error"] == "stopped/error: strategy deleted"

        # 7. Verify lock is evicted
        assert bot_id not in runner._locks

def test_put_bots_rejects_pnl_and_preserves_created_at(client, seeded):
    """
    The PUT bots route rejects updates to cumulative_funding_pnl (reverting
    to existing DB value) and preserves created_at timestamp.
    """
    # 1. Create the bot
    r = client.post("/api/bots", json=seeded)
    assert r.status_code == 200, r.text
    bot_data = r.json()
    bot_id = bot_data["id"]
    original_created_at = bot_data["created_at"]
    
    # Verify default cumulative_funding_pnl is 0.0
    assert bot_data["cumulative_funding_pnl"] == 0.0

    # 2. Manually modify cumulative_funding_pnl in store (simulate running bot accumulating PnL)
    store = BotStore.fresh()
    rec = store.get(bot_id)
    rec = rec.model_copy(update={"cumulative_funding_pnl": 123.45})
    store.save(rec)

    # 3. Attempt to update the bot using PUT, trying to change cumulative_funding_pnl and created_at
    payload = {
        **seeded,
        "symbol": "ETH/USDT",
        "cumulative_funding_pnl": 9999.88,
        "created_at": "2020-01-01T12:00:00Z"
    }
    put_r = client.put(f"/api/bots/{bot_id}", json=payload)
    assert put_r.status_code == 200, put_r.text
    
    # 4. Verify returned data has original values preserved/reverted
    put_data = put_r.json()
    assert put_data["symbol"] == "ETH/USDT"
    assert put_data["cumulative_funding_pnl"] == 123.45
    assert put_data["created_at"] == original_created_at

    # 5. Double check via GET request
    get_r = client.get(f"/api/bots/{bot_id}")
    assert get_r.status_code == 200
    get_data = get_r.json()
    assert get_data["cumulative_funding_pnl"] == 123.45
    assert get_data["created_at"] == original_created_at


@pytest.mark.asyncio
async def test_startup_verification_auto_disables_orphans_and_pops_locks(client, seeded):
    """
    Startup verification auto-disables orphan bots and pops locks.
    """
    from showme.bots.lifespan import get_runner
    from showme.bots.store import BotStore
    
    # Create an orphan bot (referencing a non-existent strategy)
    store = BotStore.fresh()
    bot_id = "orphan_test_bot"
    
    rec = BotRecord(
        id=bot_id,
        strategy_id="non-existent-strategy-id",
        credential_id=seeded["credential_id"],
        exchange_id="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        tick_interval_seconds=900,
        enabled=True  # Seed it as enabled!
    )
    store.save(rec)
    
    # Acquire/create a lock for the orphan bot in the runner's lock dictionary
    runner = get_runner()
    lock = runner._get_lock(bot_id)
    assert bot_id in runner._locks

    # Run the startup verification (start_all)
    await runner.start_all(store)

    # 1. Verify the bot is now disabled in the store
    updated_rec = store.get(bot_id)
    assert updated_rec.enabled is False

    # 2. Verify signal logs has stopped/error: strategy deleted
    assert len(updated_rec.signal_log) > 0
    last_signal = updated_rec.signal_log[-1]
    assert last_signal.action == "skipped"
    assert last_signal.error == "stopped/error: strategy deleted"

    # 3. Verify the lock has been popped from the runner
    assert bot_id not in runner._locks

    # Clean up
    store.delete(bot_id)
