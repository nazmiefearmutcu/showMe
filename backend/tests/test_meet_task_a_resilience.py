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
    elapsed = time.monotonic() - started
    assert source == "rss"
    assert [a["title"] for a in items] == ["RSS wire on budgets"]
    assert elapsed < 2.0, f"wedged GDELT held the race {elapsed:.2f}s"
    # Only the two world legs call wait_for: GDELT capped, RSS uncapped.
    assert sorted(seen_timeouts) == [5.0, 15.0]
