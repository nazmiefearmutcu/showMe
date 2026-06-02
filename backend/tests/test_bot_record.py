"""BotRecord + SignalEntry tests."""
from __future__ import annotations

import pytest

from showme.bots.record import BotRecord, SignalEntry, SIGNAL_LOG_CAP


def _signal(idx: int = 0, kind: str = "entry") -> SignalEntry:
    return SignalEntry(bar_index=idx, bar_time=f"t{idx}", kind=kind,
                       price=100.0, action="shadow")


def _bot() -> BotRecord:
    return BotRecord(strategy_id="s1", credential_id="c1",
                     exchange_id="binance", symbol="BTC/USDT")


def test_roundtrip():
    b = _bot().append_signal(_signal(0))
    b2 = BotRecord.from_json(b.to_json())
    assert b2.id == b.id
    assert len(b2.signal_log) == 1


def test_append_signal_caps_at_100():
    b = _bot()
    for i in range(SIGNAL_LOG_CAP + 20):
        b = b.append_signal(_signal(i))
    assert len(b.signal_log) == SIGNAL_LOG_CAP
    assert b.signal_log[0].bar_index == 20  # FIFO drop
    assert b.signal_log[-1].bar_index == SIGNAL_LOG_CAP + 19


def test_append_updates_last_processed():
    b = _bot()
    s = _signal(5, "entry")
    b2 = b.append_signal(s)
    assert b2.last_processed_event is not None
    assert b2.last_processed_event.bar_index == 5


def test_tick_interval_min():
    with pytest.raises(Exception):
        BotRecord(strategy_id="s", credential_id="c", exchange_id="e",
                  symbol="X", tick_interval_seconds=3)


def test_mode_default_shadow():
    b = _bot()
    assert b.mode == "shadow"
    assert b.enabled is False


def test_signal_entry_validates_action():
    with pytest.raises(Exception):
        SignalEntry(bar_index=0, bar_time="t", kind="entry",
                    price=100.0, action="invalid")


def test_auto_derived_tick_interval():
    # 1h timeframe -> default is 3600 // 4 = 900
    b1 = BotRecord(strategy_id="s", credential_id="c", exchange_id="e",
                   symbol="X", timeframe="1h")
    assert b1.tick_interval_seconds == 900

    # 1m timeframe -> default is 60 // 4 = 15
    b2 = BotRecord(strategy_id="s", credential_id="c", exchange_id="e",
                   symbol="X", timeframe="1m")
    assert b2.tick_interval_seconds == 15

    # 1d timeframe -> default is 86400 // 4 = 21600 -> clamped to 3600 ceiling
    b3 = BotRecord(strategy_id="s", credential_id="c", exchange_id="e",
                   symbol="X", timeframe="1d")
    assert b3.tick_interval_seconds == 3600

    # Explicit value should be preserved
    b4 = BotRecord(strategy_id="s", credential_id="c", exchange_id="e",
                   symbol="X", timeframe="1h", tick_interval_seconds=120)
    assert b4.tick_interval_seconds == 120


def test_symbol_validation():
    # Valid symbols
    b1 = BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT")
    assert b1.symbol == "BTC/USDT"

    b2 = BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="aapl")
    assert b2.symbol == "AAPL"  # Normalization to uppercase

    b3 = BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTCUSDT")
    assert b3.symbol == "BTCUSDT"

    # Whitespace-only
    with pytest.raises(ValueError, match="symbol must not be empty or whitespace-only"):
        BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="   ")

    # Invalid characters/formats
    with pytest.raises(ValueError, match="symbol must be alphanumeric"):
        BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC$USDT")

    with pytest.raises(ValueError, match="symbol must be alphanumeric"):
        BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USD/EUR")

    # Control character injection
    with pytest.raises(ValueError, match="symbol must not contain control characters"):
        BotRecord(strategy_id="s", credential_id="c", exchange_id="e", symbol="BTC/USDT\n")

