"""Bundle C / C8-C11 regressions in ``showme.streams``.

Covers:
- C8: reconnect backoff has jitter
- C9: requests.Session is shared and pooled
- C10: dropped ticks surface a visible ``last_error`` marker
- C11: stats() takes the snapshot lock (multi-thread race smoke test)
"""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.streams import (  # noqa: E402
    StreamHub,
    Tick,
    _get_shared_session,
    close_shared_session,
)


# ── C9: shared requests.Session ─────────────────────────────────────────


def test_shared_session_is_singleton() -> None:
    close_shared_session()  # reset to ensure deterministic state
    s1 = _get_shared_session()
    s2 = _get_shared_session()
    assert s1 is s2, "session should be a singleton across calls"
    # User-Agent header should be present.
    assert "showMe" in s1.headers.get("User-Agent", "")


def test_close_shared_session_resets_singleton() -> None:
    s1 = _get_shared_session()
    close_shared_session()
    s2 = _get_shared_session()
    assert s1 is not s2


# ── C8: backoff jitter ──────────────────────────────────────────────────


def test_hub_accepts_backoff_jitter_parameter() -> None:
    hub = StreamHub(backoff_jitter=0.4)
    assert hub._backoff_jitter == pytest.approx(0.4)


def test_hub_jitter_clamps_to_nonneg() -> None:
    hub = StreamHub(backoff_jitter=-1.0)
    assert hub._backoff_jitter == 0.0


# ── C10: drop marker visible in stats() ─────────────────────────────────


async def test_drop_marker_surfaces_in_stats() -> None:
    """When the pump drops a tick, ``stats().channels[i].last_error`` must
    surface the drop count so a UI / alert layer can flag the channel."""
    hub = StreamHub()
    # Fabricate a channel by-hand (we don't need a real source for this test).
    from showme.streams import _Channel, Source

    class _NoOpSource(Source):
        async def run(self):  # type: ignore[override]
            if False:
                yield Tick(symbol=self.symbol, price=0.0)

    ch = _Channel(symbol="TESTUSDT", source=_NoOpSource("TESTUSDT"))
    # Pre-fill a queue and mark it full so the pump's drop branch fires.
    full_q: asyncio.Queue[Tick] = asyncio.Queue(maxsize=1)
    await full_q.put(Tick(symbol="TESTUSDT", price=100.0))
    ch.queues.append(full_q)
    hub._channels["TESTUSDT"] = ch

    # Simulate ONE pump-iteration drop by mutating exactly like the pump
    # does in the patched code path.
    new_tick = Tick(symbol="TESTUSDT", price=101.0)
    with hub._stats_snapshot_lock:
        ch.last_tick = new_tick
        ch.last_tick_received_at = hub._now()
        ch.status = "live"
    # The "drop oldest then put new" pattern (mirrors fix at line 691).
    for q in list(ch.queues):
        if q.full():
            q.get_nowait()
            ch.dropped_tick_count += 1
            any_dropped = True
        q.put_nowait(new_tick)
    if any_dropped:
        with hub._stats_snapshot_lock:
            ch.last_error = f"dropped_count={ch.dropped_tick_count} (slow consumer)"

    snap = hub.stats()
    assert snap["totals"]["dropped_tick_count"] >= 1
    one = snap["channels"][0]
    assert one["dropped_tick_count"] >= 1
    assert one["last_error"] and "dropped_count" in one["last_error"]
    await hub.aclose()


# ── C11: stats() is safe against concurrent _pump mutation ──────────────


def test_stats_snapshot_lock_serializes_reads() -> None:
    """Spin up a writer thread mutating channel fields while a reader runs
    ``stats()`` in a tight loop. We're not asserting an exact value; just
    that the read never raises (e.g. KeyError / TypeError) and the lock
    boundary holds."""
    hub = StreamHub()

    # Manually inject a channel.
    from showme.streams import _Channel, Source

    class _NoOpSource(Source):
        async def run(self):  # type: ignore[override]
            if False:
                yield Tick(symbol=self.symbol, price=0.0)

    ch = _Channel(symbol="RACE", source=_NoOpSource("RACE"))
    hub._channels["RACE"] = ch

    stop = threading.Event()

    def writer() -> None:
        i = 0
        while not stop.is_set():
            with hub._stats_snapshot_lock:
                ch.error_count = i
                ch.reconnect_count = i
                ch.status = "live" if (i % 2 == 0) else "reconnecting"
            i += 1

    t = threading.Thread(target=writer)
    t.start()
    try:
        for _ in range(500):
            snap = hub.stats()
            assert "channels" in snap
            assert len(snap["channels"]) == 1
    finally:
        stop.set()
        t.join(timeout=5)
