"""MEET Bloomberg Faz 5 — realtime delta (since/known_ids cursor, hash, TTL).

Server stateless: delta girdisi client'tan gelir (since = önceki as_of,
bilgi amaçlı echo; known_ids = client baseline, CSV cap 1000). Full liste
HER ZAMAN döner + hash (sıralı id'lerin sha1'i), new_rows (cap 50),
removed_ids (cap 200). Paramsuz çağrı backward-compat: new_rows=[] ve
removed_ids=[]. filters_applied'a since/known_ids EKLENMEZ (plumbing).

Fully offline: no test performs real network I/O.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.comm import meet as meet_mod
from showme.engine.functions.macro import eco as eco_mod

_TZ_TR = timezone(timedelta(hours=3))


def _run(coro):
    return asyncio.run(coro)


def _iso_in(offset: timedelta, *, tz: timezone = UTC) -> str:
    return (datetime.now(UTC) + offset).astimezone(tz).isoformat()


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeFFClient:
    def __init__(self, payload=None):
        if payload is None:
            payload = [
                {
                    "title": "TCMB Interest Rate Decision",
                    "country": "TRY",
                    "date": _iso_in(timedelta(hours=3), tz=_TZ_TR),
                    "impact": "High",
                    "forecast": "40.5%",
                    "actual": "",
                    "previous": "40.5%",
                },
                {
                    "title": "CPI y/y",
                    "country": "USD",
                    "date": _iso_in(timedelta(hours=5), tz=timezone(timedelta(hours=-4))),
                    "impact": "High",
                    "forecast": "3.2%",
                    "actual": "3.3%",
                    "previous": "3.0%",
                },
            ]
        self._payload = payload

    async def get(self, url, timeout=None):
        return _FakeResp(self._payload)


class _FakeGDELT:
    def __init__(self, articles=None):
        if articles is None:
            articles = [
                {
                    "title": "Bitcoin ETF inflows hit a record as BTC reclaims 75k",
                    "url": "https://example.test/btc1",
                    "published_at": _iso_in(timedelta(hours=-2)),
                },
                {
                    "title": "Germany unveils budget after ceasefire deal",
                    "url": "https://example.test/de1",
                    "published_at": _iso_in(timedelta(hours=-4)),
                },
            ]
        self.articles = articles

    async def fetch(self, request):
        return list(self.articles)


class _FakeRSS:
    def __init__(self, articles=None):
        self.articles = articles if articles is not None else []

    async def fetch(self, request):
        return list(self.articles)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_caches():
    meet_mod._WORLD_CACHE = None
    meet_mod._SYMBOL_NEWS_CACHE = None
    eco_mod._ff_cache["fetched_at"] = 0.0
    eco_mod._ff_cache["rows"] = []
    yield
    meet_mod._WORLD_CACHE = None
    meet_mod._SYMBOL_NEWS_CACHE = None
    eco_mod._ff_cache["fetched_at"] = 0.0
    eco_mod._ff_cache["rows"] = []


def _meet(deps=None, client=None):
    fn = meet_mod.MEETFunction(deps=deps or FunctionDeps())
    if client is not None:
        fn._http_client = client
    return fn


def _base_call(**kwargs):
    return _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT()), _FakeFFClient()).execute(
            limit=100, **kwargs
        )
    )


# ---------------------------------------------------------------------------
# TTL + backward-compat
# ---------------------------------------------------------------------------


def test_world_cache_ttl_shortened_symbol_ttl_untouched():
    assert meet_mod._WORLD_CACHE_TTL_S == 60.0
    assert meet_mod._WORLD_CACHE_FAIL_TTL_S == 15.0
    assert meet_mod._SYMBOL_NEWS_TTL_S == 180.0


def test_paramsuz_call_is_backward_compat():
    result = _base_call()
    data = result.data
    assert data["status"] == "ok"
    assert data["new_rows"] == []
    assert data["removed_ids"] == []
    assert data["since_echo"] == ""
    assert isinstance(data["hash"], str) and len(data["hash"]) == 40
    int(data["hash"], 16)  # hex sha1


def test_since_echo_and_filters_applied_excludes_plumbing():
    result = _base_call(since="2026-09-17T10:00:00+00:00", known_ids="")
    assert result.data["since_echo"] == "2026-09-17T10:00:00+00:00"
    # known_ids empty -> no baseline -> still backward-compat lists
    assert result.data["new_rows"] == []
    assert result.data["removed_ids"] == []
    applied = result.data["filters_applied"]
    assert "since" not in applied
    assert "known_ids" not in applied


# ---------------------------------------------------------------------------
# hash + diff
# ---------------------------------------------------------------------------


def test_hash_stable_without_window_change():
    first = _base_call()
    meet_mod._WORLD_CACHE = None
    eco_mod._ff_cache["fetched_at"] = 0.0
    second = _base_call()
    assert first.data["hash"] == second.data["hash"]
    assert [r["id"] for r in first.data["rows"]] == [
        r["id"] for r in second.data["rows"]
    ]


def test_hash_changes_and_new_row_lands_in_new_rows():
    first = _base_call()
    ids = [r["id"] for r in first.data["rows"]]
    assert ids

    gdelt = _FakeGDELT(
        articles=[
            {
                "title": "Bitcoin ETF inflows hit a record as BTC reclaims 75k",
                "url": "https://example.test/btc1",
                "published_at": _iso_in(timedelta(hours=-2)),
            },
            {
                "title": "Germany unveils budget after ceasefire deal",
                "url": "https://example.test/de1",
                "published_at": _iso_in(timedelta(hours=-4)),
            },
            {
                "title": "France calls emergency summit on energy prices",
                "url": "https://example.test/fr9",
                "published_at": _iso_in(timedelta(hours=-1)),
            },
        ]
    )
    meet_mod._WORLD_CACHE = None
    second = _run(
        _meet(FunctionDeps(gdelt=gdelt), _FakeFFClient()).execute(
            limit=100, known_ids=",".join(ids)
        )
    )
    assert second.data["hash"] != first.data["hash"]
    new_ids = [r["id"] for r in second.data["new_rows"]]
    assert len(new_ids) == 1
    assert "France" in second.data["new_rows"][0]["title"]
    # new_rows preserves window order (upcoming asc, then past desc)
    rows = second.data["rows"]
    assert new_ids == [r["id"] for r in rows if r["id"] not in set(ids)]
    assert second.data["removed_ids"] == []


def test_gone_ids_land_in_removed_ids_in_client_order():
    first = _base_call()
    ids = [r["id"] for r in first.data["rows"]]
    ghost_b, ghost_a = "ghost-b", "ghost-a"
    second = _base_call(known_ids=",".join([ghost_b, *ids, ghost_a]))
    assert second.data["removed_ids"] == [ghost_b, ghost_a]
    assert second.data["new_rows"] == []
    assert second.data["hash"] == first.data["hash"]


# ---------------------------------------------------------------------------
# caps
# ---------------------------------------------------------------------------


def test_new_rows_capped_at_50():
    payload = [
        {
            "title": f"Test Event {n:03d}",
            "country": "USD" if n % 2 else "EUR",
            "date": _iso_in(timedelta(hours=n + 1)),
            "impact": "Medium",
            "forecast": "",
            "actual": "",
            "previous": "",
        }
        for n in range(60)
    ]
    result = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT([])), _FakeFFClient(payload)).execute(
            mode="calendar", limit=100, known_ids="some-old-id"
        )
    )
    assert result.data["status"] == "ok"
    assert len(result.data["rows"]) == 60
    assert len(result.data["new_rows"]) == 50
    assert [r["id"] for r in result.data["new_rows"]] == [
        r["id"] for r in result.data["rows"][:50]
    ]


def test_removed_ids_capped_at_200_in_client_order():
    ghosts = [f"ghost-{n:04d}" for n in range(300)]
    result = _base_call(known_ids=",".join(ghosts))
    assert result.data["removed_ids"] == ghosts[:200]


def test_known_ids_parse_capped_at_1000():
    first = _base_call()
    real_ids = [r["id"] for r in first.data["rows"]]
    assert real_ids
    # 1000 ghosts push the real baseline ids past the parse cap, so the
    # current rows read as new again.
    ghosts = [f"ghost-{n:04d}" for n in range(1000)]
    second = _base_call(known_ids=",".join([*ghosts, *real_ids]))
    new_ids = {r["id"] for r in second.data["new_rows"]}
    assert set(real_ids) <= new_ids


def test_empty_window_with_baseline_reports_removed():
    result = _run(
        _meet(FunctionDeps(), _FakeFFClient([])).execute(
            known_ids="old-a,old-b", limit=100
        )
    )
    assert result.data["rows"] == []
    assert result.data["new_rows"] == []
    assert result.data["removed_ids"] == ["old-a", "old-b"]
    assert isinstance(result.data["hash"], str) and len(result.data["hash"]) == 40
