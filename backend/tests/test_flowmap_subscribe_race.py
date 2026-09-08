"""FeedHub.subscribe create-lock race regression tests (review F1).

Commit 8a48f69 claimed "regression tests for all five" FLW fixes, but the
subscribe create-lock race (``FeedHub._create_lock``) had NO test: a revert
of the lock passed the whole suite.

``subscribe()`` separates its limit-check / registry-insert / session-boot
sections with real network awaits (the boot kline backfill). Without the
create lock, concurrent first-subscribes interleave at that await and:

- for the SAME key, each racing coroutine builds its own feed + session
  (double feeds, duplicated backfills; one silently wins the registry), and
- for DISTINCT keys, every coroutine passes the ``max_sessions`` limit check
  before any slot is registered, oversubscribing past the cap.

These tests drive N concurrent ``hub.subscribe()`` calls under
``asyncio.gather`` with an interleaving backfill and pin the post-fix
behavior: exactly one session (and one feed) per key, and
``SessionLimitError`` beyond the cap.
"""
from __future__ import annotations

import asyncio

from showme.flowmap import events
from showme.flowmap.session import ClientTx, FeedHub, SessionLimitError


class FakeFeed:
    """Feed double: emits nothing; never touches the network."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.synced = True
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    async def events(self):
        # Yield forever without doing work: the session run task parks here.
        await asyncio.Event().wait()
        yield  # pragma: no cover - never reached


def _make_hub(max_sessions: int, feeds: list[str] | None = None,
              backfill_ticks: int = 3):
    """Hub whose boot backfill yields to the loop ``backfill_ticks`` times.

    The yields give concurrent subscribers the same interleaving window the
    real network awaits (kline fetch) provide in production.
    """
    feeds_created: list[str] = []

    def feed_factory(symbol: str) -> FakeFeed:
        feeds_created.append(symbol)
        return FakeFeed(symbol)

    async def backfill(symbol: str, *, max_cols: int, now_ns: int) -> list[dict]:
        for _ in range(backfill_ticks):
            await asyncio.sleep(0)
        return []

    hub = FeedHub(
        feed_factory=feed_factory,
        backfill_fn=backfill,
        backfill_max_cols=16,
        max_sessions=max_sessions,
    )
    return hub, feeds_created


def _subscribe(symbol: str, band: str = "wide") -> events.Subscribe:
    return events.Subscribe(market="crypto", symbol=symbol, mode="live", band=band)


def _stop_all(hub: FeedHub) -> None:
    for session in list(hub._sessions.values()):  # noqa: SLF001 - test teardown
        session.stop()


def test_concurrent_same_key_subscribe_creates_exactly_one_session():
    """N concurrent first-subscribes to ONE key must boot ONE feed/session.

    Pre-fix (no create lock): every coroutine observed ``session is None``
    during another's boot await, so N feeds were constructed and N sessions
    raced for the registry slot.
    """
    n = 6

    async def scenario():
        hub, feeds_created = _make_hub(max_sessions=2)
        try:
            results = await asyncio.gather(*(
                hub.subscribe(_subscribe("BTCUSDT"), ClientTx())
                for _ in range(n)
            ))
            return hub, feeds_created, results
        except BaseException:
            _stop_all(hub)
            raise

    hub, feeds_created, results = asyncio.run(scenario())
    try:
        assert hub.live_feed_count == 1
        assert len(feeds_created) == 1, (
            f"expected exactly one feed boot, got {len(feeds_created)}"
        )
        sessions = {id(s) for s in results}
        assert len(sessions) == 1, "all subscribers must share one session"
        session = hub.session_for("BTCUSDT", "wide")
        assert session is not None
        assert session.client_count == n
    finally:
        _stop_all(hub)


def test_concurrent_same_key_subscribe_reuses_session_after_boot():
    """A subscribe racing a boot-in-progress subscriber must ATTACH to the
    reserved session, not double-create; the latecomer's snapshot still
    arrives (frames enqueued before subscribe returns)."""

    async def scenario():
        hub, feeds_created = _make_hub(max_sessions=2)
        try:
            first, *rest = await asyncio.gather(*(
                hub.subscribe(_subscribe("ETHUSDT"), ClientTx(cap=5000))
                for _ in range(4)
            ))
            return hub, feeds_created, first, rest
        except BaseException:
            _stop_all(hub)
            raise

    hub, feeds_created, first, rest = asyncio.run(scenario())
    try:
        assert len(feeds_created) == 1
        for s in rest:
            assert s is first
        # A follow-up subscribe after boot attaches to the same session.
        late = asyncio.run(_late_attach(hub))
        assert late is first
    finally:
        _stop_all(hub)


async def _late_attach(hub: FeedHub):
    return await hub.subscribe(_subscribe("ETHUSDT"), ClientTx())


def test_concurrent_distinct_keys_enforce_session_cap():
    """max_sessions+1 concurrent first-subscribes to DISTINCT keys: exactly
    max_sessions succeed, the rest raise SessionLimitError, and the live
    feed count never exceeds the cap.

    Pre-fix: every coroutine passed the limit check before any slot was
    registered (the check and the insert are separated by the boot await),
    so all four keys went live under a cap of two.
    """
    max_sessions = 2
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

    async def scenario():
        hub, feeds_created = _make_hub(max_sessions=max_sessions)
        try:
            results = await asyncio.gather(*(
                hub.subscribe(_subscribe(sym), ClientTx())
                for sym in symbols
            ), return_exceptions=True)
            return hub, feeds_created, results
        except BaseException:
            _stop_all(hub)
            raise

    hub, feeds_created, results = asyncio.run(scenario())
    try:
        ok = [r for r in results if not isinstance(r, BaseException)]
        limited = [r for r in results if isinstance(r, SessionLimitError)]
        assert len(ok) == max_sessions
        assert len(limited) == len(symbols) - max_sessions
        assert all(isinstance(r, SessionLimitError) for r in limited)
        assert hub.live_feed_count == max_sessions
        assert len(feeds_created) == max_sessions, (
            "a rejected subscribe must never construct a feed"
        )
    finally:
        _stop_all(hub)


def test_subscribe_at_full_cap_never_creates_feed():
    """With the cap already reached, a burst of concurrent subscribes to a
    NEW key all fail with SessionLimitError and no feed is constructed."""

    async def scenario():
        hub, feeds_created = _make_hub(max_sessions=1)
        await hub.subscribe(_subscribe("BTCUSDT"), ClientTx())
        assert hub.live_feed_count == 1
        try:
            results = await asyncio.gather(*(
                hub.subscribe(_subscribe("ETHUSDT"), ClientTx())
                for _ in range(5)
            ), return_exceptions=True)
            return hub, feeds_created, results
        except BaseException:
            _stop_all(hub)
            raise

    hub, feeds_created, results = asyncio.run(scenario())
    try:
        assert len(results) == 5
        assert all(isinstance(r, SessionLimitError) for r in results)
        assert len(feeds_created) == 1  # only the pre-existing BTCUSDT feed
        assert hub.live_feed_count == 1
    finally:
        _stop_all(hub)
