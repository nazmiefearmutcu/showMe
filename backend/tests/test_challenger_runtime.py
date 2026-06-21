"""Adversarial stress and edge-case tests for C-RUNTIME-1 and H-RT-2."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from pydantic import ValidationError

from showme.bots.record import BotRecord, SignalEntry
from showme.bots.runner import BotRunner
from showme.bots.store import BotStore


# =====================================================================
# C-RUNTIME-1: Tick interval vs Timeframe validation tests
# =====================================================================

@pytest.mark.parametrize(
    "timeframe,tick_interval,expected_valid",
    [
        # --- 1m timeframe (tf_s = 60) ---
        ("1m", 5, True),      # Min allowed globally
        ("1m", 15, True),     # Default
        ("1m", 60, True),     # Max allowed (tf_s)
        ("1m", 4, False),     # Invalid: under global floor ge=5
        ("1m", 61, False),    # Invalid: over tf_s (too slow)
        
        # --- 5m timeframe (tf_s = 300) ---
        ("5m", 5, True),
        ("5m", 75, True),     # Default
        ("5m", 300, True),
        ("5m", 301, False),   # Invalid: over tf_s (too slow)

        # --- 15m timeframe (tf_s = 900) ---
        ("15m", 5, True),
        ("15m", 225, True),   # Default
        ("15m", 900, True),
        ("15m", 901, False),  # Invalid: over tf_s (too slow)

        # --- 1h timeframe (tf_s = 3600) ---
        ("1h", 5, True),
        ("1h", 900, True),    # Default
        ("1h", 3600, True),
        ("1h", 3601, False),  # Invalid: over global ceiling le=3600

        # --- 4h timeframe (tf_s = 14400) ---
        ("4h", 30, True),     # Min allowed for >=4h (30s)
        ("4h", 3600, True),   # Default/Max allowed (global ceiling le=3600)
        ("4h", 5, False),     # Invalid: too aggressive (under 30s)
        ("4h", 29, False),    # Invalid: too aggressive (under 30s)
        ("4h", 3601, False),  # Invalid: over global ceiling le=3600

        # --- 1d timeframe (tf_s = 86400) ---
        ("1d", 30, True),     # Min allowed for >=4h (30s)
        ("1d", 3600, True),   # Default/Max allowed (global ceiling le=3600)
        ("1d", 5, False),     # Invalid: too aggressive (under 30s)
        ("1d", 29, False),    # Invalid: too aggressive (under 30s)
        ("1d", 3601, False),  # Invalid: over global ceiling le=3600
    ]
)
def test_tick_interval_validation_limits(timeframe: str, tick_interval: int, expected_valid: bool):
    """Test that all boundary combinations of tick_interval and timeframe are validated correctly."""
    if expected_valid:
        record = BotRecord(
            strategy_id="s",
            credential_id="c",
            exchange_id="e",
            symbol="BTC/USDT",
            timeframe=timeframe,
            tick_interval_seconds=tick_interval
        )
        assert record.tick_interval_seconds == tick_interval
    else:
        with pytest.raises((ValueError, ValidationError)):
            BotRecord(
                strategy_id="s",
                credential_id="c",
                exchange_id="e",
                symbol="BTC/USDT",
                timeframe=timeframe,
                tick_interval_seconds=tick_interval
            )


@pytest.mark.parametrize(
    "timeframe,expected_default",
    [
        ("1m", 15),
        ("5m", 75),
        ("15m", 225),
        ("1h", 900),
        ("4h", 3600),
        ("1d", 3600),
    ]
)
def test_tick_interval_auto_derivation(timeframe: str, expected_default: int):
    """Test that tick_interval_seconds is correctly derived from the timeframe if not specified."""
    record = BotRecord(
        strategy_id="s",
        credential_id="c",
        exchange_id="e",
        symbol="BTC/USDT",
        timeframe=timeframe
    )
    assert record.tick_interval_seconds == expected_default


# =====================================================================
# H-RT-2: Task disable, cancel, and lock release tests
# =====================================================================

@pytest.mark.asyncio
async def test_concurrent_disable_calls(tmp_path: Path):
    """Verify that multiple concurrent disable calls do not deadlock or raise,
    and correctly update the database under lock."""
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id="s1",
        credential_id="c1",
        exchange_id="binance",
        symbol="BTC/USDT",
        enabled=True,
        mode="shadow",
        tick_interval_seconds=10,
    ))

    runner = BotRunner()
    
    # Mock a running task
    async def dummy_loop():
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(dummy_loop())
    runner._tasks[bot.id] = task

    # Trigger multiple concurrent disable calls
    results = await asyncio.gather(
        runner.disable(bot.id, store),
        runner.disable(bot.id, store),
        runner.disable(bot.id, store),
        return_exceptions=True
    )

    # Ensure no exception was raised in any concurrent call
    for r in results:
        assert isinstance(r, BotRecord)
        assert r.enabled is False

    # The store must reflect the disabled state
    reloaded = store.get(bot.id)
    assert reloaded.enabled is False
    assert bot.id not in runner._tasks
    assert task.done()


@pytest.mark.asyncio
async def test_disable_cancels_task_holding_lock_in_long_io(monkeypatch, tmp_path: Path):
    """Verify that if a bot task is holding the lock (inside tick()) and is blocked 
    on long-running I/O, calling disable immediately cancels the task, releases the lock,
    updates the store, and returns without deadlock."""
    store = BotStore(tmp_path / "bots")
    bot = store.save(BotRecord(
        strategy_id="s1",
        credential_id="c1",
        exchange_id="binance",
        symbol="BTC/USDT",
        enabled=True,
        mode="shadow",
        tick_interval_seconds=10,
    ))

    runner = BotRunner()

    io_started = asyncio.Event()
    io_cancelled = asyncio.Event()

    async def mock_tick(bot_id: str, bot_store: BotStore, _now: any = None):
        async with runner._get_lock(bot_id):
            io_started.set()
            try:
                # Simulate long-running I/O while holding the lock
                await asyncio.sleep(10.0)
            except asyncio.CancelledError:
                io_cancelled.set()
                raise

    # Override runner.tick with mock_tick
    monkeypatch.setattr(runner, "tick", mock_tick)

    # Spawn run loop which will call our mock_tick
    task = asyncio.create_task(runner._run_loop(bot.id, store))
    runner._tasks[bot.id] = task

    # Wait for the task to acquire the lock and start mock I/O
    await io_started.wait()

    # Now, call disable while the task holds the lock and is blocked on mock I/O
    t0 = time.perf_counter()
    rec = await runner.disable(bot.id, store)
    t1 = time.perf_counter()

    # Ensure disable completes fast (does not block on the 10s sleep or task cleanup)
    assert t1 - t0 < 0.2
    assert rec.enabled is False

    # Yield control to the event loop so the CancelledError can be handled by the task
    await asyncio.sleep(0.01)

    assert io_cancelled.is_set()
    assert task.done()
    assert bot.id not in runner._tasks

    # Verify that the lock is not locked anymore
    lock = runner._get_lock(bot.id)
    assert not lock.locked()
