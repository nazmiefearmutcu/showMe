"""S13 BugHunt 2026-05-17 — pin TRDH `next_close_utc` + `seconds_until_close`.

The pre-fix TRDH always reported `seconds_until_open` even for currently-open
exchanges, so the UI countdown on an open NYSE pointed at the *next* open
(~22h away) instead of today's close (~few hours away). The fix added
`next_close` to `CalendarRegistry` and made TRDH emit both close and open
deltas, plus a unified `value` that the UI uses for the primary countdown.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from showme.engine.reference.calendar_registry import CalendarRegistry  # noqa: E402


def test_calendar_registry_exposes_next_close():
    cal = CalendarRegistry()
    # NYSE: 09:30 → 16:00 America/New_York. At 14:00 ET an open NYSE is
    # ~2h from close and ~19.5h from the next open.
    when = datetime(2026, 5, 18, 18, 0, 0, tzinfo=timezone.utc)  # 14:00 ET Monday
    nxt_close = cal.next_close("NYSE", when)
    nxt_open = cal.next_open("NYSE", when)
    assert nxt_close is not None
    assert nxt_open is not None
    # next_close is in the future, but well before next_open.
    assert nxt_close > when
    assert nxt_close < nxt_open
    # Close-to-when is roughly 2 hours.
    delta = (nxt_close - when).total_seconds() / 3600
    assert 1.5 < delta < 2.5, f"NYSE close should be ~2h away, got {delta:.2f}h"


def test_calendar_registry_next_close_returns_none_for_247_venues():
    cal = CalendarRegistry()
    when = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)
    assert cal.next_close("BINANCE", when) is None
    assert cal.next_close("DERIBIT", when) is None


@pytest.fixture(autouse=True)
def _awareness_offline(monkeypatch):
    """Tests never hit the live awareness-markets service; injected fakes still win."""
    from showme.engine.data_sources.awareness import AwarenessUnavailable
    from showme.engine.functions.calendar import _common as _aw_common

    class _Offline:
        async def get(self, path, params=None):
            raise AwarenessUnavailable("awareness disabled in tests")

    monkeypatch.setattr(_aw_common, "get_awareness_client", lambda: _Offline())
