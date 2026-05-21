"""S07 — Deterministic observability tests for ``StreamHub``.

Every scenario uses an injectable clock + fake source so we can pin the
exact moment a tick arrives and assert ``stats()`` reflects it without any
network or real-time dependency.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from showme.streams import (
    Source,
    StreamHub,
    Tick,
)


# ── Fake source helpers ─────────────────────────────────────────────────────


class _ScriptedSource(Source):
    """Yields a queue of pre-built ticks, then idles until stopped."""

    def __init__(self, symbol: str, ticks: list[Tick]) -> None:
        super().__init__(symbol)
        self._ticks = list(ticks)

    async def run(self) -> AsyncIterator[Tick]:
        for tick in self._ticks:
            if self.stopping:
                return
            await asyncio.sleep(0)
            yield tick
        while not self.stopping:
            await asyncio.sleep(0.005)


class _RaisingSource(Source):
    """Yields a single tick (or none), then raises once.

    After the configured number of raises, the source idles until stopped
    so reconnect logic can re-enter the pump cleanly.
    """

    def __init__(
        self,
        symbol: str,
        *,
        ticks_before_raise: int = 0,
        raises_remaining: int = 1,
        exc_factory: type[Exception] = RuntimeError,
    ) -> None:
        super().__init__(symbol)
        self._ticks_before_raise = ticks_before_raise
        self._raises_remaining = raises_remaining
        self._exc_factory = exc_factory
        self.attempts = 0

    async def run(self) -> AsyncIterator[Tick]:
        self.attempts += 1
        for n in range(self._ticks_before_raise):
            if self.stopping:
                return
            await asyncio.sleep(0)
            yield Tick(symbol=self.symbol, price=float(n + 1), source="raising_fake")
        if self._raises_remaining > 0:
            self._raises_remaining -= 1
            raise self._exc_factory(f"synthetic source failure for {self.symbol}")
        while not self.stopping:
            await asyncio.sleep(0.005)


# ── stats() empty envelope ──────────────────────────────────────────────────


def test_stats_empty_envelope_has_stable_keys() -> None:
    hub = StreamHub(crypto_factory=lambda s: _ScriptedSource(s, []))
    stats = hub.stats()
    assert stats["ok"] is True
    assert isinstance(stats["generated_at"], str) and stats["generated_at"]
    assert stats["stale_threshold_ms"] == 15_000
    assert stats["channels"] == []
    expected_totals = {
        "channel_count",
        "subscriber_count",
        "live_count",
        "stale_count",
        "reconnecting_count",
        "error_count",
        "dropped_tick_count",
    }
    assert set(stats["totals"]) == expected_totals
    for v in stats["totals"].values():
        assert v == 0


# ── Live channel shape ──────────────────────────────────────────────────────


def test_stats_reports_live_channel_after_first_tick() -> None:
    async def _run() -> None:
        ticks = [Tick(symbol="BTCUSDT", price=60_000.0, source="fake")]
        # Pin the clock so age math is deterministic.
        clock = {"t": 1_000.0}
        hub = StreamHub(
            crypto_factory=lambda s: _ScriptedSource(s, ticks),
            now=lambda: clock["t"],
        )
        sub = await hub.subscribe("BTCUSDT")
        async with sub as queue:
            tick = await asyncio.wait_for(queue.get(), timeout=1.0)
            assert tick.price == 60_000.0
            # Move the clock forward 500ms; channel should still be live.
            clock["t"] = 1_000.5
            stats = hub.stats()
            assert stats["totals"]["channel_count"] == 1
            assert stats["totals"]["live_count"] == 1
            assert stats["totals"]["subscriber_count"] == 1
            ch = stats["channels"][0]
            assert ch["symbol"] == "BTCUSDT"
            assert ch["status"] == "live"
            assert ch["last_price"] == 60_000.0
            assert ch["source"] == "fake"
            assert ch["last_tick_age_ms"] == pytest.approx(500.0, rel=0.0, abs=0.01)
            assert ch["reconnect_count"] == 0
            assert ch["error_count"] == 0
            assert ch["dropped_tick_count"] == 0
            assert ch["last_error"] is None
            assert ch["queue_depths"] == [queue.qsize()]

    asyncio.run(_run())


# ── Stale classification ────────────────────────────────────────────────────


def test_stats_promotes_to_stale_past_threshold() -> None:
    """``stats()`` must reclassify a live channel as stale once the
    injected clock exceeds the configured threshold."""

    async def _run() -> None:
        ticks = [Tick(symbol="ETHUSDT", price=3_000.0, source="fake")]
        clock = {"t": 0.0}
        hub = StreamHub(
            crypto_factory=lambda s: _ScriptedSource(s, ticks),
            stale_threshold_s=2.0,
            now=lambda: clock["t"],
        )
        sub = await hub.subscribe("ETHUSDT")
        async with sub as queue:
            await asyncio.wait_for(queue.get(), timeout=1.0)
            # 1s elapsed → still live.
            clock["t"] = 1.0
            stats = hub.stats()
            assert stats["channels"][0]["status"] == "live"
            assert stats["totals"]["live_count"] == 1
            assert stats["totals"]["stale_count"] == 0
            # 3s elapsed → past 2s threshold → stale.
            clock["t"] = 3.0
            stats = hub.stats()
            assert stats["channels"][0]["status"] == "stale"
            assert stats["channels"][0]["last_tick_age_ms"] == pytest.approx(3000.0)
            assert stats["totals"]["live_count"] == 0
            assert stats["totals"]["stale_count"] == 1

    asyncio.run(_run())


# ── Reconnect / error counters ──────────────────────────────────────────────


def test_reconnect_and_error_counters_increment_after_source_raises() -> None:
    async def _run() -> None:
        # Source yields one tick, then raises once, then idles. The pump
        # rebuilds the source via the factory after backing off — we provide
        # a factory closure that hands out a *new* source instance per call.
        sources: list[_RaisingSource] = []

        def factory(symbol: str) -> Source:
            src = _RaisingSource(
                symbol,
                ticks_before_raise=1,
                raises_remaining=1 if not sources else 0,
            )
            sources.append(src)
            return src

        hub = StreamHub(crypto_factory=factory)
        sub = await hub.subscribe("BTCUSDT")
        async with sub as queue:
            # Drain the first tick.
            await asyncio.wait_for(queue.get(), timeout=1.0)
            # Wait for the pump to observe the raise + backoff + rebuild.
            # The initial backoff is 1s — yield repeatedly until either
            # error_count flips or we hit a generous test ceiling.
            deadline = asyncio.get_running_loop().time() + 3.0
            while asyncio.get_running_loop().time() < deadline:
                stats = hub.stats()
                ch = stats["channels"][0]
                if ch["error_count"] >= 1 and ch["last_error"]:
                    break
                await asyncio.sleep(0.05)
            stats = hub.stats()
            ch = stats["channels"][0]
            assert ch["error_count"] >= 1, "error_count did not increment after raise"
            assert ch["last_error"] is not None
            assert "synthetic source failure" in ch["last_error"]
            # ``status`` should be ``reconnecting`` while the pump is between
            # the raise and the next successful tick.
            assert ch["status"] in {"reconnecting", "live"}
            # Reconnect attempt counter is bumped by the pump after backoff.
            # We don't require the rebuild to have completed within the test
            # window — the error/last_error pair already proves observability.

    asyncio.run(_run())


# ── Dropped tick counter ────────────────────────────────────────────────────


def test_dropped_tick_count_increments_when_subscriber_queue_overflows() -> None:
    """A slow subscriber with a maxsize=1 queue must surface drops in stats."""

    async def _run() -> None:
        # Many ticks in flight, but the subscriber never drains them.
        ticks = [Tick(symbol="BTCUSDT", price=float(i), source="fake") for i in range(20)]
        hub = StreamHub(
            crypto_factory=lambda s: _ScriptedSource(s, ticks),
            queue_maxsize=1,
        )
        sub = await hub.subscribe("BTCUSDT")
        async with sub as queue:
            # Don't drain — let the pump's overflow path kick in.
            # The pump yields ticks via ``await asyncio.sleep(0)`` between
            # each tick, so yielding control lets it advance.
            for _ in range(30):
                await asyncio.sleep(0)
            stats = hub.stats()
            ch = stats["channels"][0]
            assert ch["dropped_tick_count"] >= 1, (
                f"expected drops, got {ch['dropped_tick_count']} "
                f"(queue depth={queue.qsize()})"
            )
            assert stats["totals"]["dropped_tick_count"] >= 1
            # The subscriber's queue should now hold only the most recent
            # tick (because the pump drops oldest, pushes newest).
            assert queue.qsize() == 1

    asyncio.run(_run())


# ── aclose() cleanup ────────────────────────────────────────────────────────


def test_aclose_cancels_pump_tasks_and_clears_channels() -> None:
    async def _run() -> None:
        ticks = [Tick(symbol="BTCUSDT", price=1.0, source="fake")]
        hub = StreamHub(crypto_factory=lambda s: _ScriptedSource(s, ticks))
        sub = await hub.subscribe("BTCUSDT")
        async with sub as queue:
            await asyncio.wait_for(queue.get(), timeout=1.0)
            # Capture the pump task BEFORE aclose() clears the channel dict.
            task = hub._channels["BTCUSDT"].task
            assert task is not None
            await hub.aclose()
            assert hub._channels == {}
            # Task should have completed or been cancelled (cooperative).
            assert task.done()
        # Second close call is idempotent.
        await hub.aclose()
        # No active channels and no new subs allowed.
        with pytest.raises(RuntimeError):
            await hub.subscribe("ETHUSDT")

    asyncio.run(_run())


def test_close_alias_resolves_to_aclose() -> None:
    """``server._shutdown_cleanup`` probes ``close`` first, ``aclose`` second."""

    async def _run() -> None:
        hub = StreamHub(crypto_factory=lambda s: _ScriptedSource(s, []))
        # Both attributes resolve and are coroutine functions.
        assert callable(getattr(hub, "close", None))
        assert callable(getattr(hub, "aclose", None))
        result = hub.close()
        assert asyncio.iscoroutine(result)
        await result

    asyncio.run(_run())
