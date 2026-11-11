"""MEET — limit-after-window + GDELT/RSS race pins (2026-09-17).

Regression cover for two owner-observed bugs:
  * a small ``limit`` truncated the week-chronological feed BEFORE windowing,
    eating the entire upcoming section (``limit=5`` -> 0 upcoming);
  * the serial GDELT-timeout + RSS-fallback chain cost ~13 s on a cold cache.

Fully offline: no test performs real network I/O.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.comm import meet as meet_mod


@pytest.fixture(autouse=True)
def _reset_caches():
    meet_mod._SYMBOL_NEWS_CACHE = None
    yield
    meet_mod._SYMBOL_NEWS_CACHE = None


def _run(coro):
    return asyncio.run(coro)


def _iso_in(offset: timedelta) -> str:
    return (datetime.now(UTC) + offset).isoformat()


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _OldFirstFFClient:
    """12 stale rows first, then 2 upcoming — feed order is old-first."""

    def __init__(self):
        rows = [
            {
                "title": f"Old print {i}",
                "country": "USD",
                "date": _iso_in(timedelta(hours=-(72 + i))),
                "impact": "Low",
                "forecast": "",
                "actual": "",
                "previous": "",
            }
            for i in range(12)
        ]
        rows += [
            {
                "title": "Soon print A",
                "country": "USD",
                "date": _iso_in(timedelta(hours=5)),
                "impact": "Medium",
                "forecast": "",
                "actual": "",
                "previous": "",
            },
            {
                "title": "Soon print B",
                "country": "USD",
                "date": _iso_in(timedelta(hours=6)),
                "impact": "Medium",
                "forecast": "",
                "actual": "",
                "previous": "",
            },
        ]
        self._payload = rows

    async def get(self, url, timeout=None):
        return _FakeResp(self._payload)


class _InstantNews:
    def __init__(self, articles):
        self._articles = articles
        self.calls = 0

    async def fetch(self, request):
        self.calls += 1
        return list(self._articles)


class _SlowGDELT(_InstantNews):
    async def fetch(self, request):
        self.calls += 1
        await asyncio.sleep(5)
        return list(self._articles)


def _meet(deps=None, client=None):
    fn = meet_mod.MEETFunction(deps=deps or FunctionDeps())
    if client is not None:
        fn._http_client = client
    return fn


@pytest.fixture(autouse=True)
def _awareness_offline(monkeypatch):
    """Tests never hit the live awareness-markets service; injected fakes still win."""
    from showme.engine.data_sources.awareness import AwarenessUnavailable
    from showme.engine.functions.calendar import _common as _aw_common

    class _Offline:
        async def get(self, path, params=None):
            raise AwarenessUnavailable("awareness disabled in tests")

    monkeypatch.setattr(_aw_common, "get_awareness_client", lambda: _Offline())
