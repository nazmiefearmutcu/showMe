"""MEET Task A — dead-host removal + GDELT leg-cap pins (2026-09-19).

Covers brief items 1-2:
  * GlobeNewswire (dead host) is gone from ``_MARKET_FEEDS`` (15 -> 14);
  * the GDELT leg of ``_world_headlines`` is capped at 5 s so a wedged DOC
    endpoint fails fast into the RSS win (RSS leg keeps the full timeout).

Fully offline: no test performs real network I/O, and the cap test never
waits out a real 5 s timeout (it spies on the ``wait_for`` timeout values
while a hanging GDELT loses the race to an instant RSS).
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.core.base_function import FunctionDeps
from showme.engine.data_sources.news.rss_adapter import _MARKET_FEEDS
from showme.engine.functions.comm import meet as meet_mod


def test_market_feeds_drop_dead_globenewswire_host():
    """Dead host removed: no globenewswire URL, market feed count 15 -> 14."""
    assert not any("globenewswire" in url.lower() for url in _MARKET_FEEDS)
    assert len(_MARKET_FEEDS) == 14


class _HangingGDELT:
    """Simulates a wedged DOC endpoint: never answers."""

    async def fetch(self, request):
        await asyncio.Event().wait()
        return []  # pragma: no cover


class _InstantRSS:
    def __init__(self, articles):
        self._articles = articles

    async def fetch(self, request):
        return list(self._articles)


def test_gdelt_leg_capped_so_wedged_doc_fails_fast_into_rss_win():
    """news_timeout=15: GDELT leg capped at 5 s, RSS leg keeps 15 s."""
    meet_mod._WORLD_CACHE = None
    meet_mod._gdelt_429_until = 0.0
    rss_articles = [
        {
            "title": "RSS wire on budgets",
            "link": "https://example.test/rss-win",
            "published_at": (datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
        }
    ]
    fn = meet_mod.MEETFunction(
        deps=FunctionDeps(gdelt=_HangingGDELT(), rss=_InstantRSS(rss_articles))
    )
    real_wait_for = asyncio.wait_for
    seen_timeouts: list[float | None] = []

    async def _spy(coro, *, timeout=None, **kwargs):
        seen_timeouts.append(timeout)
        return await real_wait_for(coro, timeout=timeout, **kwargs)

    started = time.monotonic()
    try:
        with mock.patch.object(meet_mod.asyncio, "wait_for", _spy):
            items, source, _error = asyncio.run(
                fn._world_headlines(now=datetime.now(UTC), timeout=15.0)
            )
    finally:
        meet_mod._WORLD_CACHE = None
        meet_mod._gdelt_429_until = 0.0
    elapsed = time.monotonic() - started
    assert source == "rss"
    assert [a["title"] for a in items] == ["RSS wire on budgets"]
    assert elapsed < 2.0, f"wedged GDELT held the race {elapsed:.2f}s"
    # Only the two world legs call wait_for: GDELT capped, RSS uncapped.
    assert sorted(seen_timeouts) == [5.0, 15.0]


class _Flaky429GDELT:
    """First call 429s, then answers instantly (quota recovered)."""

    def __init__(self):
        self.calls = 0

    async def fetch(self, request):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("GDELT 429 Too Many Requests")
        return [{"title": "GDELT wire recovered", "url": "https://example.test/g",
                 "published_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat()}]


def test_gdelt_429_parks_leg_and_rss_serves_with_backoff_note():
    """A 429 parks the GDELT leg: retry skips GDELT, serves RSS, notes backoff."""
    meet_mod._WORLD_CACHE = None
    meet_mod._gdelt_429_until = 0.0
    try:
        gdelt = _Flaky429GDELT()
        rss_articles = [{
            "title": "RSS wire on budgets",
            "link": "https://example.test/rss-win",
            "published_at": (datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
        }]
        fn = meet_mod.MEETFunction(
            deps=FunctionDeps(gdelt=gdelt, rss=_InstantRSS(rss_articles))
        )
        items, source, error = asyncio.run(
            fn._world_headlines(now=datetime.now(UTC), timeout=8.0)
        )
        assert source == "rss" and gdelt.calls == 1
        assert error is not None and "429" in error
        # Second fetch inside the backoff window: GDELT untouched.
        meet_mod._WORLD_CACHE = None
        items, source, error = asyncio.run(
            fn._world_headlines(now=datetime.now(UTC), timeout=8.0)
        )
        assert source == "rss" and gdelt.calls == 1
        assert error is not None and "backoff" in error
    finally:
        meet_mod._WORLD_CACHE = None
        meet_mod._gdelt_429_until = 0.0


class _Boom4290GDELT:
    """Error text containing 4290 is not a 429 — no backoff may trigger."""

    def __init__(self):
        self.calls = 0

    async def fetch(self, request):
        self.calls += 1
        raise RuntimeError("boom 4290 gone wrong")


def test_near_429_text_does_not_park_gdelt_leg():
    """\b429\b matching only: '4290' must not start the backoff window."""
    meet_mod._WORLD_CACHE = None
    meet_mod._gdelt_429_until = 0.0
    try:
        gdelt = _Boom4290GDELT()
        fn = meet_mod.MEETFunction(deps=FunctionDeps(gdelt=gdelt, rss=_InstantRSS([])))
        for _ in range(2):
            meet_mod._WORLD_CACHE = None
            asyncio.run(fn._world_headlines(now=datetime.now(UTC), timeout=8.0))
        assert gdelt.calls == 2
        assert meet_mod._gdelt_429_until == 0.0
    finally:
        meet_mod._WORLD_CACHE = None
        meet_mod._gdelt_429_until = 0.0


def test_backoff_note_keeps_original_429_detail():
    """The backoff-window note carries the parked 429 message, not just a label."""
    meet_mod._WORLD_CACHE = None
    meet_mod._gdelt_429_until = 0.0
    try:
        gdelt = _Flaky429GDELT()
        rss_articles = [{
            "title": "RSS wire on budgets",
            "link": "https://example.test/rss-win",
            "published_at": (datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
        }]
        fn = meet_mod.MEETFunction(
            deps=FunctionDeps(gdelt=gdelt, rss=_InstantRSS(rss_articles))
        )
        asyncio.run(fn._world_headlines(now=datetime.now(UTC), timeout=8.0))
        meet_mod._WORLD_CACHE = None
        _, _, error = asyncio.run(
            fn._world_headlines(now=datetime.now(UTC), timeout=8.0)
        )
        assert error is not None and "backoff" in error
        assert "429" in error
    finally:
        meet_mod._WORLD_CACHE = None
        meet_mod._gdelt_429_until = 0.0
