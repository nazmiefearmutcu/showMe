"""MEET — world-events tracker pins (rebuilt 2026-09).

Contract:
  * scheduled rows come from the keyless ForexFactory weekly calendar
    (reused from ECO — the HTTP leg is driven via the ``_http_client``
    injection seam) and are anchored to UTC with affected FX pairs,
  * world headlines come from the keyless news path and are tagged with a
    country gazetteer (multi-country allowed, matched terms recorded),
  * windows are upcoming-ascending / past-descending with server-computed
    countdowns,
  * spot alerts cover rate decisions and wars,
  * an empty provider set yields an honest ``provider_unavailable``
    envelope — events are never invented.

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

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.comm import meet as meet_mod
from showme.engine.functions.macro import eco as eco_mod
from showme.engine.services import world_events as we

_TZ_TR = timezone(timedelta(hours=3))


def _run(coro):
    return asyncio.run(coro)


def _iso_in(offset: timedelta, *, tz: timezone = UTC) -> str:
    """Offset-aware ISO timestamp relative to now (never ages out)."""
    return (datetime.now(UTC) + offset).astimezone(tz).isoformat()


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeFFClient:
    """ForexFactory weekly-calendar HTTP stand-in."""

    def __init__(self, payload=None, boom: bool = False):
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
                    "actual": "",
                    "previous": "3.0%",
                },
                {
                    "title": "Bank Holiday",
                    "country": "JPY",
                    "date": _iso_in(timedelta(days=2)),
                    "impact": "Holiday",
                    "forecast": "",
                    "actual": "",
                    "previous": "",
                },
                {
                    "title": "Released yesterday",
                    "country": "EUR",
                    "date": _iso_in(timedelta(hours=-30), tz=timezone(timedelta(hours=2))),
                    "impact": "Medium",
                    "forecast": "",
                    "actual": "1.1%",
                    "previous": "1.0%",
                },
            ]
        self._payload = payload
        self._boom = boom
        self.calls = 0

    async def get(self, url, timeout=None):
        self.calls += 1
        if self._boom:
            raise RuntimeError("calendar unreachable")
        return _FakeResp(self._payload)


class _FakeGDELT:
    def __init__(self, articles=None, boom: bool = False):
        self.articles = articles if articles is not None else [
            {
                "title": "Turkey and the US hold defence talks as Russia warns Ukraine",
                "url": "https://example.test/a1",
                "published_at": _iso_in(timedelta(hours=-2)),
            },
            {
                "title": "Germany unveils budget after ceasefire deal",
                "url": "https://example.test/a2",
                "published_at": _iso_in(timedelta(hours=-4)),
            },
        ]
        self._boom = boom
        self.calls = 0

    async def fetch(self, request):
        self.calls += 1
        if self._boom:
            raise RuntimeError("news unreachable")
        return list(self.articles)


class _FakeRSS:
    def __init__(self, articles=None):
        self.articles = articles if articles is not None else [
            {
                "title": "Türkiye parliament debates budget as Ukraine truce holds",
                "link": "https://example.test/rss1",
                "published_at": _iso_in(timedelta(hours=-1)),
            },
        ]
        self.calls = 0

    async def fetch(self, request):
        self.calls += 1
        return list(self.articles)


@pytest.fixture(autouse=True)
def _reset_ff_cache():
    eco_mod._ff_cache["fetched_at"] = 0.0
    eco_mod._ff_cache["rows"] = []
    yield
    eco_mod._ff_cache["fetched_at"] = 0.0
    eco_mod._ff_cache["rows"] = []


def _meet(deps=None, client=None):
    fn = meet_mod.MEETFunction(deps=deps or FunctionDeps())
    if client is not None:
        fn._http_client = client
    return fn


# ---------------------------------------------------------------------------
# Canonicalization / row math (service level)
# ---------------------------------------------------------------------------


def test_tcmb_rate_decision_maps_to_tr_with_usdtry_pairs():
    """TRY → TR and the affected pairs are the quoted lira crosses."""
    now = datetime.now(UTC)
    stamp = _iso_in(timedelta(hours=4), tz=_TZ_TR)
    rows, dropped = we.economic_rows([{
        "country": "TRY",
        "event": "TCMB Interest Rate Decision",
        "date": stamp,
        "importance": "High",
        "forecast": "40.5%",
        "actual": None,
        "previous": "40.5%",
    }], now=now)

    assert dropped == 0
    row = rows[0]
    assert row["countries"] == ["TR"]
    assert row["country_names"] == ["Turkey"]
    assert row["pairs"] == ["USDTRY", "EURTRY"]
    assert row["currencies"] == ["TRY"]
    assert row["spot"] is True
    assert row["pinned"] is True
    # Offset-aware provider timestamp → the same real UTC instant.
    when = datetime.fromisoformat(row["when_utc"])
    assert when == datetime.fromisoformat(stamp)
    assert when.utcoffset() == timedelta(0)


def test_seconds_to_event_and_age_minutes_math():
    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    rows, _ = we.economic_rows([
        {"country": "USD", "event": "CPI y/y", "date": "2026-09-16T14:30:00+00:00", "importance": "High"},
        {"country": "USD", "event": "PPI m/m", "date": "2026-09-16T09:00:00+00:00", "importance": "Medium"},
        {"country": "USD", "event": "Retail Sales", "date": "2026-09-15T08:30:00-04:00", "importance": "Medium"},
    ], now=now)

    cpi = next(r for r in rows if r["title"] == "CPI y/y")
    assert cpi["seconds_to_event"] == 9000.0
    assert cpi["age_minutes"] is None

    ppi = next(r for r in rows if r["title"] == "PPI m/m")
    assert ppi["seconds_to_event"] == -10800.0
    assert ppi["age_minutes"] == 180.0

    # 08:30-04:00 == 12:30 UTC → 3.5h before now.
    retail = next(r for r in rows if r["title"] == "Retail Sales")
    assert retail["when_utc"] == "2026-09-15T12:30:00+00:00"
    assert retail["seconds_to_event"] == pytest.approx(-84600.0)


def test_rows_without_parseable_time_are_dropped_and_counted():
    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    rows, dropped = we.economic_rows([
        {"country": "USD", "event": "No time", "date": "", "importance": "High"},
    ], now=now)
    assert rows == []
    assert dropped == 1


def test_upcoming_ascending_and_past_descending():
    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    rows, _ = we.economic_rows([
        {"country": "USD", "event": "Later", "date": "2026-09-17T12:00:00+00:00", "importance": "High"},
        {"country": "USD", "event": "Sooner", "date": "2026-09-16T13:00:00+00:00", "importance": "Medium"},
        {"country": "USD", "event": "Old", "date": "2026-09-15T12:00:00+00:00", "importance": "Low"},
        {"country": "USD", "event": "Older", "date": "2026-09-14T12:00:00+00:00", "importance": "Low"},
    ], now=now)

    upcoming, past = we.split_window(rows, days_ahead=30, days_back=7)
    assert [r["title"] for r in upcoming] == ["Sooner", "Later"]
    assert [r["title"] for r in past] == ["Old", "Older"]
    assert all(r["seconds_to_event"] >= 0 for r in upcoming)
    assert all(r["seconds_to_event"] < 0 for r in past)


def test_country_index_next_event_and_state():
    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    rows, _ = we.economic_rows([
        {"country": "TRY", "event": "TCMB Interest Rate Decision", "date": "2026-09-17T11:00:00+00:00", "importance": "High"},
        {"country": "TRY", "event": "Old print", "date": "2026-09-15T11:00:00+00:00", "importance": "Low"},
        {"country": "CHF", "event": "SNB Rate Decision", "date": "2026-09-16T12:05:00+00:00", "importance": "High"},
    ], now=now)

    index = {b["iso"]: b for b in we.build_country_index(rows, now=now)}
    assert index["TR"]["next_event"]["title"] == "TCMB Interest Rate Decision"
    assert index["TR"]["upcoming_count"] == 1
    assert index["TR"]["past_count"] == 1
    assert index["TR"]["state"] == "soon"
    # 5 minutes out → the live state.
    assert index["CH"]["state"] == "live"


def test_alerts_cover_spot_rate_decisions_with_default_leads():
    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    rows, _ = we.economic_rows([
        {"country": "TRY", "event": "TCMB Interest Rate Decision", "date": "2026-09-17T11:00:00+00:00", "importance": "High"},
        {"country": "JPY", "event": "Bank Holiday", "date": "2026-09-17T00:00:00+00:00", "importance": "Holiday"},
    ], now=now)
    upcoming, _ = we.split_window(rows, days_ahead=7, days_back=7)

    alerts = we.build_alerts(upcoming)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["spot"] is True
    assert alert["countries"] == ["TR"]
    assert alert["pairs"] == ["USDTRY", "EURTRY"]
    assert alert["lead_minutes"] == [5, 60, 1440]
    assert alert["seconds_to_event"] > 0


def test_world_rows_tag_multiple_countries_with_matched_terms():
    now = datetime.now(UTC)
    rows = we.world_rows([{
        "title": "Turkey and the US hold defence talks as Russia warns Ukraine",
        "url": "https://example.test/x",
        "published_at": (now - timedelta(hours=2)).isoformat(),
    }], now=now, source="gdelt")

    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "world"
    assert set(row["countries"]) >= {"TR", "US", "RU", "UA"}
    assert row["country_names"][0]
    assert row["details"]["matched_terms"]
    # Multi-country attribution is term-auditable: each tagged country has
    # at least one matched term string.
    assert len(row["details"]["matched_terms"]) == len(row["countries"])


def test_world_war_headline_is_spot_high_impact():
    now = datetime.now(UTC)
    rows = we.world_rows([{
        "title": "Missile strikes hit power grid after invasion escalation",
        "url": "https://example.test/war",
        "published_at": now.isoformat(),
    }], now=now)
    assert rows[0]["impact"] == "high"
    assert rows[0]["spot"] is True


def test_gdelt_seendate_stamp_parses_to_utc():
    """GDELT's DOC API emits compact 20260916T103000Z stamps, not ISO."""
    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    rows = we.world_rows([{
        "title": "Russia and Ukraine exchange accusations at the border",
        "seendate": "20260916T103000Z",
        "url": "https://example.test/gdelt",
    }], now=now)
    assert len(rows) == 1
    assert rows[0]["when_utc"] == "2026-09-16T10:30:00+00:00"
    assert rows[0]["age_minutes"] == 90.0
    assert rows[0]["undated"] is False


# ---------------------------------------------------------------------------
# MEET execute() — end-to-end payload (offline fakes)
# ---------------------------------------------------------------------------


def test_execute_merges_calendar_and_world_headlines():
    client = _FakeFFClient()
    gdelt = _FakeGDELT()
    result = _run(_meet(FunctionDeps(gdelt=gdelt), client).execute(limit=100))

    assert result.data["status"] == "ok"
    assert set(result.sources) == {"forex_factory", "gdelt"}
    kinds = {r["kind"] for r in result.data["rows"]}
    assert kinds == {"economic", "world"}
    # Country catalog ships the full reference list for the filter bar.
    assert len(result.data["country_catalog"]) >= 90
    # Every row carries a source and a UTC timestamp.
    assert all(r["source"] for r in result.data["rows"])
    assert all(r["when_utc"] for r in result.data["rows"])
    # The world headline is available under TR and the rate decision too.
    tr_rows = [r for r in result.data["rows"] if "TR" in r["countries"]]
    assert any(r["title"] == "TCMB Interest Rate Decision" for r in tr_rows)
    assert any(r["kind"] == "world" for r in tr_rows)
    # Server parity countdown present on every row.
    assert all("seconds_to_event" in r for r in result.data["rows"])
    assert result.metadata["live"] is True


def test_countries_filter_tr_keeps_only_turkey_rows():
    result = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT()), _FakeFFClient())
        .execute(countries="TR", limit=100)
    )
    assert result.data["rows"], "TR filter must keep rows"
    for row in result.data["rows"]:
        assert "TR" in row["countries"], row
    titles = [r["title"] for r in result.data["rows"]]
    assert "TCMB Interest Rate Decision" in titles
    assert "CPI y/y" not in titles


def test_kind_economic_skips_world_fetch():
    gdelt = _FakeGDELT()
    result = _run(
        _meet(FunctionDeps(gdelt=gdelt), _FakeFFClient())
        .execute(kind="economic")
    )
    assert gdelt.calls == 0, "world kind excluded → news provider untouched"
    assert result.data["rows"]
    assert all(r["kind"] == "economic" for r in result.data["rows"])


def test_filtered_empty_says_so_without_inventing_rows():
    result = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT()), _FakeFFClient())
        .execute(countries="ZZ", limit=100)
    )
    assert result.data["status"] == "ok"
    assert result.data["rows"] == []
    assert result.data["filtered_empty"] is True
    # Provider rows still exist for the footer/index (nothing was fabricated).
    assert result.data["unfiltered_upcoming_count"] >= 1


def test_all_providers_down_is_an_honest_empty_envelope():
    result = _run(
        _meet(
            FunctionDeps(gdelt=_FakeGDELT(boom=True)),
            _FakeFFClient(boom=True),
        ).execute()
    )
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.data["upcoming"] == []
    assert result.data["alerts"] == []
    assert result.sources == ["no_live_source"]
    warning_blob = " ".join(result.warnings).lower()
    assert "forex_factory" in warning_blob
    assert "gdelt" in warning_blob
    assert result.metadata["live"] is False
    assert result.metadata["fallback"] is True


def test_world_headlines_keep_their_source_label():
    result = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT()), _FakeFFClient()).execute(limit=100)
    )
    world_rows = [r for r in result.data["rows"] if r["kind"] == "world"]
    assert world_rows
    assert all(r["source"] == "gdelt" for r in world_rows)
    assert all(r["details"]["url"] for r in world_rows)


def test_rss_fallback_when_gdelt_returns_empty():
    """An empty-but-OK GDELT result falls back to the keyless RSS stream."""
    rss = _FakeRSS()
    result = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT(articles=[]), rss=rss), _FakeFFClient())
        .execute(limit=100)
    )
    assert rss.calls == 1
    assert "rss" in result.sources
    world_rows = [r for r in result.data["rows"] if r["kind"] == "world"]
    assert world_rows
    assert all(r["source"] == "rss" for r in world_rows)
    # The empty GDELT result is not an error — no spurious warning.
    assert not any("gdelt" in w for w in result.warnings)


def test_dropped_no_time_is_reported():
    payload = [
        {"title": "Undated print", "country": "USD", "date": "", "impact": "High"},
    ]
    result = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT()), _FakeFFClient(payload=payload))
        .execute(include_world=True)
    )
    assert result.data["dropped_no_time"] == 1
    assert all(r["kind"] != "economic" for r in result.data["rows"])
