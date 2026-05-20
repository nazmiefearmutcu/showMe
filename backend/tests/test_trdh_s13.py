"""S13 BugHunt 2026-05-17 — pin TRDH `next_close_utc` + `seconds_until_close`.

The pre-fix TRDH always reported `seconds_until_open` even for currently-open
exchanges, so the UI countdown on an open NYSE pointed at the *next* open
(~22h away) instead of today's close (~few hours away). The fix added
`next_close` to `CalendarRegistry` and made TRDH emit both close and open
deltas, plus a unified `value` that the UI uses for the primary countdown.
"""

from __future__ import annotations

import sys
import asyncio
from datetime import datetime, timezone, timedelta
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


@pytest.mark.asyncio
async def test_trdh_emits_close_countdown_for_open_exchanges():
    """Smoke: TRDH should attach `next_close_utc` and `seconds_until_close`
    to every non-24/7 exchange row, and `value` should track close-when-open.
    """
    # Import inside the test so module-level FunctionRegistry.register side
    # effects don't pollute other tests' fixtures.
    from showme.engine.functions.macro.trdh import TRDHFunction

    class _Deps:
        symbol_registry = None
        yfinance = None

    fn = TRDHFunction(_Deps())
    res = await fn.execute(exchanges=["NYSE", "LSE", "BINANCE"])
    rows = {r["exchange"]: r for r in res.data["rows"]}
    # Both NYSE and LSE expose both deltas.
    for code in ("NYSE", "LSE"):
        assert "next_close_utc" in rows[code]
        assert "seconds_until_close" in rows[code]
        assert "hours_until_close" in rows[code]
    # 24/7 venues should not have a scheduled close (next_close_utc is None)
    assert rows["BINANCE"]["next_close_utc"] is None
    # When an exchange is open NOW, `value` should match hours_until_close.
    # We can't depend on wall-clock time inside the test, so just verify the
    # invariant: if is_open_now, value equals hours_until_close (and vice
    # versa).
    for code in ("NYSE", "LSE"):
        row = rows[code]
        if row.get("is_open_now"):
            assert row["value"] == row["hours_until_close"]
        else:
            assert row["value"] == row["hours_until_open"]


def test_trdh_field_dictionary_documents_close_fields():
    from showme.engine.functions.macro.trdh import TRDHFunction

    class _Deps:
        symbol_registry = None
        yfinance = None

    fn = TRDHFunction(_Deps())
    res = asyncio.run(fn.execute(exchanges=["NYSE"]))
    fd = res.data["field_dictionary"]
    assert "next_close_utc" in fd
    assert "seconds_until_close" in fd
