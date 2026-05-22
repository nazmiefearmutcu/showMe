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
