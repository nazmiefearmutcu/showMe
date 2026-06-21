import asyncio
import time
import pytest
from pydantic import ValidationError
from showme.bots.record import BotRecord
from showme.bots.store import BotStore
from showme.bots.runner import BotRunner

# ── C-RUNTIME-1: Tick interval validation on various timeframes ──

def test_tick_interval_validation_5m():
    # 5m = 300 seconds bar period. Allowed: [5, 300]. Blocked: [301, 3600].
    # Valid min
    BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT", timeframe="5m", tick_interval_seconds=5)
    # Valid max
    BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT", timeframe="5m", tick_interval_seconds=300)
    # Invalid: too slow (> 300)
    with pytest.raises(ValueError, match="too slow for timeframe"):
        BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT", timeframe="5m", tick_interval_seconds=301)


def test_tick_interval_validation_1h():
    # 1h = 3600 seconds bar period. Allowed: [5, 3600]. Blocked: > 3600 (Pydantic ValidationError).
    BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT", timeframe="1h", tick_interval_seconds=5)
    BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT", timeframe="1h", tick_interval_seconds=3600)
    
    with pytest.raises(ValidationError):
        BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT", timeframe="1h", tick_interval_seconds=3601)


def test_tick_interval_validation_4h():
    # 4h = 14400 seconds. Allowed: [30, 3600]. Blocked: < 30 ("too aggressive").
    BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT", timeframe="4h", tick_interval_seconds=30)
    BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT", timeframe="4h", tick_interval_seconds=3600)
    
    with pytest.raises(ValueError, match="too aggressive for timeframe"):
        BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT", timeframe="4h", tick_interval_seconds=29)
    with pytest.raises(ValueError, match="too aggressive for timeframe"):
        BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT", timeframe="4h", tick_interval_seconds=5)


def test_tick_interval_validation_1d():
    # 1d = 86400 seconds. Allowed: [30, 3600]. Blocked: < 30 ("too aggressive").
    BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT", timeframe="1d", tick_interval_seconds=30)
    BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT", timeframe="1d", tick_interval_seconds=3600)
    
    with pytest.raises(ValueError, match="too aggressive for timeframe"):
        BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT", timeframe="1d", tick_interval_seconds=29)
    with pytest.raises(ValueError, match="too aggressive for timeframe"):
        BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT", timeframe="1d", tick_interval_seconds=5)


# ── H-RT-2: Disable lock release & task cancel ──

@pytest.mark.asyncio
async def test_multiple_concurrent_disable_calls(tmp_path):
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id="s1", credential_id="c1", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow",
        tick_interval_seconds=10,
    ))

    task_started = asyncio.Event()
    
    async def dummy_loop():
        task_started.set()
        try:
            while True:
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            raise

    runner = BotRunner()
    task = asyncio.create_task(dummy_loop())
    runner._tasks[bot.id] = task

    await task_started.wait()

    # Call disable concurrently
    results = await asyncio.gather(
        runner.disable(bot.id, store),
        runner.disable(bot.id, store),
        runner.disable(bot.id, store),
        return_exceptions=True
    )

    # All calls should complete without raising exceptions
    for res in results:
        assert not isinstance(res, Exception), f"Concurrent disable raised: {res}"
        assert isinstance(res, BotRecord)
        assert res.enabled is False

    # The store value should be disabled
    assert store.get(bot.id).enabled is False
    # Task should be popped and cancelled
    assert bot.id not in runner._tasks
    
    # Yield control to event loop to let task finalize cancellation
    await asyncio.sleep(0.01)
    assert task.done()


@pytest.mark.asyncio
async def test_disable_cancelled_task_blocked_on_long_running_io(tmp_path):
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id="s1", credential_id="c1", exchange_id="binance",
        symbol="BTC/USDT", enabled=True, mode="shadow",
        tick_interval_seconds=10,
    ))

    task_started = asyncio.Event()
    long_io_started = asyncio.Event()
    long_io_cancelled = asyncio.Event()

    async def long_io_loop():
        task_started.set()
        try:
            long_io_started.set()
            # Simulate blocking on long-running network/DB call
            await asyncio.sleep(100.0)
        except asyncio.CancelledError:
            long_io_cancelled.set()
            raise

    runner = BotRunner()
    task = asyncio.create_task(long_io_loop())
    runner._tasks[bot.id] = task

    await task_started.wait()
    await long_io_started.wait()

    t0 = time.perf_counter()
    rec = await runner.disable(bot.id, store)
    t1 = time.perf_counter()

    # The disable call must return immediately, not waiting for the 100s sleep
    assert t1 - t0 < 0.1
    assert rec.enabled is False
    assert bot.id not in runner._tasks

    # Yield control to event loop so that the loop schedules the CancelledError execution
    await asyncio.sleep(0.01)
    assert long_io_cancelled.is_set()
    assert task.done()
