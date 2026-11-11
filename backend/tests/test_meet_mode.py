"""MEET Bloomberg Faz 3 — manifest + kontrat (mode/tags/data_filter/symbols).

Binding ruling: Task 2 values (all/spot/pinned) AND spec values
(all/with_forecast/with_actual/surprise_only) are supported together;
unknown -> all.

  * mode=calendar never touches the world wire (gdelt.calls==0, rss untouched),
    only economic rows survive; mode wins over kind.
  * mode=wire drops every economic row.
  * tags=BTC keeps the Bitcoin row and drops the unrelated one.
  * data_filter=with_actual/with_forecast/surprise_only narrows calendar rows;
    spot/pinned keep working; unknown is a no-op.
  * REGISTRY.get("MEET") declares the new inputs; the agent-runtime MEET
    branch preserves caller mode/tags/data_filter/symbols.

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

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.functions.comm import meet as meet_mod  # noqa: E402

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
        self.calls = 0

    async def get(self, url, timeout=None):
        self.calls += 1
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
        self.calls = 0

    async def fetch(self, request):
        self.calls += 1
        return list(self.articles)


class _FakeRSS:
    def __init__(self, articles=None):
        self.articles = articles if articles is not None else []
        self.calls = 0

    async def fetch(self, request):
        self.calls += 1
        return list(self.articles)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_caches():
    meet_mod._SYMBOL_NEWS_CACHE = None
    yield
    meet_mod._SYMBOL_NEWS_CACHE = None


from _meet_awareness import awareness_from_ff_client  # noqa: E402


def _meet(deps=None, client=None):
    fn = meet_mod.MEETFunction(deps=deps or FunctionDeps())
    if client is not None:
        fn._http_client = client
        fn._awareness = awareness_from_ff_client(client)
    return fn


# ---------------------------------------------------------------------------
# Manifest contract
# ---------------------------------------------------------------------------


def test_manifest_declares_mode_tags_data_filter_symbols():
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    meet = REGISTRY.get("MEET")
    by_name = {i.name: i for i in meet.inputs}
    for name in ("mode", "tags", "data_filter", "symbols"):
        assert name in by_name, f"MEET manifest must declare input {name!r}"
    assert by_name["mode"].options == ["all", "calendar", "wire"]
    assert by_name["data_filter"].options == [
        "all",
        "spot",
        "pinned",
        "major_only",
        "with_forecast",
        "with_actual",
        "surprise_only",
    ]
    assert meet.defaults.get("mode") == "all"
    assert meet.defaults.get("tags") == ""
    assert meet.defaults.get("data_filter") == "all"
    assert meet.defaults.get("symbols") in ("", [], None)
    assert "calendar" in (by_name["symbols"].description or "").lower(), (
        "symbols desc must note that the symbol feed is skipped in calendar mode"
    )
    for key in (
        "rows[].details.actual",
        "rows[].details.forecast",
        "rows[].asset_tags",
        "rows[].event_type",
    ):
        assert key in meet.field_dict, f"MEET field_dict must declare {key!r}"
    blob = meet.methodology.lower()
    assert "mode" in blob and "tags" in blob and "data_filter" in blob
    names = [t.name for t in meet.semantic_tests]
    assert any("mode" in n or "calendar" in n for n in names)


# ---------------------------------------------------------------------------
# mode
# ---------------------------------------------------------------------------


def test_mode_calendar_skips_world_fetch():
    gdelt = _FakeGDELT()
    rss = _FakeRSS()
    result = _run(
        _meet(FunctionDeps(gdelt=gdelt, rss=rss), _FakeFFClient()).execute(
            mode="calendar", limit=100
        )
    )
    assert result.data["status"] == "ok"
    assert gdelt.calls == 0, "calendar mode must never touch the world wire"
    assert rss.calls == 0, "calendar mode must never touch RSS either"
    assert result.data["rows"]
    assert all(r["kind"] == "economic" for r in result.data["rows"])
    assert result.data["filters_applied"]["mode"] == "calendar"
    assert result.data["filters_applied"]["kind"] == "all"


def test_mode_wins_over_kind():
    gdelt = _FakeGDELT()
    result = _run(
        _meet(FunctionDeps(gdelt=gdelt), _FakeFFClient()).execute(
            mode="calendar", kind="world", limit=100
        )
    )
    assert gdelt.calls == 0
    assert result.data["rows"]
    assert all(r["kind"] == "economic" for r in result.data["rows"])
    assert result.data["filters_applied"]["kind"] == "world"


def test_kind_backward_compat_without_mode():
    gdelt = _FakeGDELT()
    result = _run(
        _meet(FunctionDeps(gdelt=gdelt), _FakeFFClient()).execute(
            kind="economic", limit=100
        )
    )
    assert gdelt.calls == 0, "legacy kind=economic still skips the world fetch"
    assert result.data["rows"]
    assert all(r["kind"] == "economic" for r in result.data["rows"])
    assert result.data["filters_applied"]["mode"] == "calendar"
    assert result.data["filters_applied"]["kind"] == "economic"


# ---------------------------------------------------------------------------
# tags
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# data_filter (superset ruling)
# ---------------------------------------------------------------------------

_DATA_ROWS = [
    {
        "title": "CPI y/y",
        "country": "USD",
        "date": _iso_in(timedelta(hours=5), tz=timezone(timedelta(hours=-4))),
        "impact": "High",
        "forecast": "3.2%",
        "actual": "3.3%",
        "previous": "3.0%",
    },
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
        "title": "Retail Sales m/m",
        "country": "USD",
        "date": _iso_in(timedelta(hours=7), tz=timezone(timedelta(hours=-4))),
        "impact": "Medium",
        "forecast": "",
        "actual": "0.4%",
        "previous": "0.2%",
    },
]


@pytest.mark.parametrize(
    "bad", [float("nan"), float("inf"), float("-inf"), "NaN", "Infinity"]
)
def test_data_filter_surprise_only_rejects_non_finite_numbers(bad):
    row = {"kind": "economic", "details": {"actual": bad, "forecast": 1.0}}
    assert meet_mod._passes_data_filter(row, "surprise_only") is False
    assert meet_mod._passes_data_filter(row, "with_actual") is False


def test_data_filter_unknown_is_all_noop():
    base = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT()), _FakeFFClient(_DATA_ROWS)).execute(
            limit=100
        )
    )
    odd = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT()), _FakeFFClient(_DATA_ROWS)).execute(
            data_filter="bogus_value", limit=100
        )
    )
    assert odd.data["filters_applied"]["data_filter"] == "all"
    assert [r["id"] for r in odd.data["rows"]] == [r["id"] for r in base.data["rows"]]


# ---------------------------------------------------------------------------
# Agent-runtime pop protection (caller values survive)
# ---------------------------------------------------------------------------


def test_agent_runtime_meet_branch_preserves_caller_contract_params():
    from showme.server_routes._agent_runtime import _route_function_params

    routed = _route_function_params(
        "MEET",
        {
            "mode": "calendar",
            "tags": "BTC",
            "data_filter": "with_actual",
            "symbols": "BTCUSDT",
        },
    )
    assert routed.get("mode") == "calendar"
    assert routed.get("tags") == "BTC"
    assert routed.get("data_filter") == "with_actual"
    assert routed.get("symbols") == "BTCUSDT"
    assert (routed.get("query") or "") != "bitcoin cryptocurrency"


def test_mode_calendar_with_symbols_skips_symbol_feed():
    gdelt = _FakeGDELT()
    rss = _FakeRSS()
    result = _run(
        _meet(FunctionDeps(gdelt=gdelt, rss=rss), _FakeFFClient(_DATA_ROWS)).execute(
            mode="calendar", symbols="BTCUSDT", limit=100
        )
    )
    assert result.data["status"] == "ok"
    assert gdelt.calls == 0
    assert rss.calls == 0, "calendar mode never pulls the symbol feed either"
    assert "symbol_feed" not in (result.sources or [])


def test_filters_applied_kind_carries_raw_input():
    result = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT()), _FakeFFClient()).execute(
            mode="calendar", kind="world", limit=100
        )
    )
    assert result.data["filters_applied"]["mode"] == "calendar"
    assert result.data["filters_applied"]["kind"] == "world"
    assert all(r["kind"] == "economic" for r in result.data["rows"])


@pytest.fixture(autouse=True)
def _awareness_offline(monkeypatch):
    """Tests never hit the live awareness-markets service; injected fakes still win."""
    from showme.engine.data_sources.awareness import AwarenessUnavailable
    from showme.engine.functions.calendar import _common as _aw_common

    class _Offline:
        async def get(self, path, params=None):
            raise AwarenessUnavailable("awareness disabled in tests")

    monkeypatch.setattr(_aw_common, "get_awareness_client", lambda: _Offline())
