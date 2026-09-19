"""MEET Task 6 — contract + regression pins (world_events + meet).

Locks the final fix wave:
  * EU gazetteer alive (REGION_NAMES wired into _TERM_PATTERNS, EUR code).
  * Top-level data_mode / alerts_count / countries_tracked mirror metadata.
  * provider_mode echo (filters_applied + metadata.requested_mode, no behaviour change).
  * Undated world-row ids stable across polls (no delta churn).
  * GDELT error surfaced with "(rss served)" when RSS wins the race.
  * war -> event_type geopolitics; hack -> medium impact; ETF plurals;
    rate-decision word boundary; PAIR_MAP USD crosses.
  * Combined {tags:BTC, data_filter:with_actual} drops the BTC world row
    (documents current calendar-only filter behaviour — no behaviour change).

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
from showme.engine.services import world_events as we

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
                    "actual": "3.3%",
                    "previous": "3.0%",
                },
            ]
        self._payload = payload
        self._boom = boom

    async def get(self, url, timeout=None):
        if self._boom:
            raise RuntimeError("forex_factory down")
        return _FakeResp(self._payload)


class _FakeGDELT:
    def __init__(self, articles=None, boom: bool = False):
        if articles is None:
            articles = [
                {
                    "title": "Bitcoin ETF inflows hit a record as BTC reclaims 75k",
                    "url": "https://example.test/btc1",
                    "published_at": _iso_in(timedelta(hours=-2)),
                },
            ]
        self.articles = articles
        self._boom = boom
        self.calls = 0

    async def fetch(self, request):
        self.calls += 1
        if self._boom:
            raise RuntimeError("GDELT 429 Too Many Requests")
        return list(self.articles)


class _SlowRSS:
    """RSS leg that answers after the instant GDELT boom (deterministic race)."""

    def __init__(self, articles):
        self.articles = articles
        self.calls = 0

    async def fetch(self, request):
        self.calls += 1
        await asyncio.sleep(0.05)
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


# ---------------------------------------------------------------------------
# 1. EU gazetteer
# ---------------------------------------------------------------------------


def test_eu_gazetteer_brussels_summit_tags_eu_and_be():
    isos, _matched = we.match_countries("EU leaders meet in Brussels summit")
    assert "EU" in isos
    assert "BE" in isos


def test_eur_currency_code_tags_eu():
    isos, _matched = we.match_countries("EUR climbs as eurozone data beats")
    assert "EU" in isos


def test_european_union_tags_eu():
    isos, _matched = we.match_countries("European Union summit in Brussels")
    assert "EU" in isos


# ---------------------------------------------------------------------------
# 2. Top-level contract mirrors
# ---------------------------------------------------------------------------


def test_top_level_data_mode_alerts_count_countries_tracked():
    result = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT()), _FakeFFClient()).execute(limit=100)
    )
    data = result.data
    assert data["status"] == "ok"
    assert data["data_mode"] == result.metadata["data_mode"]
    assert data["data_mode"].startswith("live_")
    assert data["alerts_count"] == len(data["alerts"])
    assert data["alerts_count"] == result.metadata["counts"]["alerts"]
    assert data["countries_tracked"] == len(data["country_index"])


def test_empty_envelope_carries_top_level_contract():
    result = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT(boom=True)), _FakeFFClient(boom=True)).execute()
    )
    assert result.data["status"] == "provider_unavailable"
    assert result.data["data_mode"] == "provider_unavailable"
    assert result.data["data_mode"] == result.metadata["data_mode"]
    assert result.data["alerts_count"] == 0
    assert result.data["countries_tracked"] == 0


# ---------------------------------------------------------------------------
# 4. provider_mode echo (no behaviour change)
# ---------------------------------------------------------------------------


def test_provider_mode_defaults_to_live_official_without_warning():
    result = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT()), _FakeFFClient()).execute(limit=100)
    )
    assert result.data["filters_applied"]["provider_mode"] == "live_official"
    assert result.metadata["requested_mode"] == "live_official"
    assert not any("requested cached_snapshot" in w for w in result.warnings)


def test_provider_mode_cached_snapshot_echoes_and_warns_when_live_served():
    result = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT()), _FakeFFClient()).execute(
            provider_mode="cached_snapshot", limit=100
        )
    )
    assert result.data["filters_applied"]["provider_mode"] == "cached_snapshot"
    assert result.metadata["requested_mode"] == "cached_snapshot"
    live_mode = result.metadata["data_mode"]
    assert live_mode.startswith("live_")
    assert f"requested cached_snapshot, served {live_mode}" in result.warnings
    # Behaviour unchanged: the live chain still answers.
    assert result.data["status"] == "ok"
    assert result.data["rows"]


# ---------------------------------------------------------------------------
# 5. Undated id stability
# ---------------------------------------------------------------------------


def test_undated_world_row_id_stable_across_polls():
    article = {"title": "Markets eye central bank chatter", "url": "https://example.test/u1"}
    first = we.world_rows([article], now=datetime.now(UTC), source="rss")
    second = we.world_rows(
        [article], now=datetime.now(UTC) + timedelta(seconds=61), source="rss"
    )
    assert first[0]["undated"] is True
    assert first[0]["id"].startswith("world:undated:")
    assert first[0]["id"] == second[0]["id"]


def test_undated_ids_still_unique_per_article():
    now = datetime.now(UTC)
    rows = we.world_rows(
        [
            {"title": "Markets eye central bank chatter", "url": "https://example.test/u1"},
            {"title": "Markets eye central bank chatter", "url": "https://example.test/u2"},
        ],
        now=now,
        source="rss",
    )
    assert len(rows) == 2
    assert rows[0]["id"] != rows[1]["id"]


# ---------------------------------------------------------------------------
# 6. GDELT error surfaced when RSS wins
# ---------------------------------------------------------------------------


def test_gdelt_error_noted_when_rss_serves():
    rss = _SlowRSS([
        {
            "title": "RSS wire on budgets",
            "link": "https://example.test/r1",
            "published_at": _iso_in(timedelta(minutes=-30)),
        },
    ])
    result = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT(boom=True), rss=rss), _FakeFFClient()).execute(
            kind="world", limit=100
        )
    )
    assert "rss" in result.sources
    assert "gdelt" not in result.sources
    blob = " ".join(result.warnings)
    assert "gdelt" in blob
    assert "(rss served)" in blob
    world_rows = [r for r in result.data["rows"] if r["kind"] == "world"]
    assert world_rows
    assert all(r["source"] == "rss" for r in world_rows)


# ---------------------------------------------------------------------------
# 7. war / hack / ETF plural / rate boundary
# ---------------------------------------------------------------------------


def test_war_headline_classifies_geopolitics_not_etf_flow():
    rows = we.world_rows(
        [{
            "title": "War erupts as Bitcoin ETF inflows hit record",
            "url": "https://example.test/war1",
            "published_at": _iso_in(timedelta(hours=-1)),
        }],
        now=datetime.now(UTC),
        source="gdelt",
    )
    assert rows[0]["details"]["event_type"] == "geopolitics"
    assert rows[0]["impact"] == "high"
    assert rows[0]["spot"] is True


def test_hack_headline_is_medium_impact():
    rows = we.world_rows(
        [{
            "title": "bridge hack stolen funds vanish",
            "url": "https://example.test/hack1",
            "published_at": _iso_in(timedelta(hours=-1)),
        }],
        now=datetime.now(UTC),
        source="gdelt",
    )
    assert rows[0]["details"]["event_type"] == "hack"
    assert rows[0]["impact"] == "medium"


def test_etf_plural_inflows_tags_etf():
    tags, _matched = we.match_assets("Bitcoin inflows hit record")
    assert "BTC" in tags
    assert "ETF" in tags


def test_rate_decision_regex_rejects_glued_turkeyrate():
    now = datetime.now(UTC)
    glued, _ = we.economic_rows(
        [{
            "country": "USD",
            "event": "Turkeyrate decision",
            "date": (now + timedelta(hours=4)).isoformat(),
            "importance": "High",
        }],
        now=now,
        source="forex_factory",
    )
    assert glued[0]["spot"] is False
    spaced, _ = we.economic_rows(
        [{
            "country": "USD",
            "event": "Turkey rate decision",
            "date": (now + timedelta(hours=4)).isoformat(),
            "importance": "High",
        }],
        now=now,
        source="forex_factory",
    )
    assert spaced[0]["spot"] is True


# ---------------------------------------------------------------------------
# 8. PAIR_MAP USD crosses
# ---------------------------------------------------------------------------


def test_pair_map_usd_crosses_for_uncovered_currencies():
    for currency, pair in {
        "RUB": "USDRUB", "UAH": "USDUAH", "HKD": "USDHKD", "SAR": "USDSAR",
        "AED": "USDAED", "QAR": "USDQAR", "RON": "USDRON", "BGN": "USDBGN",
        "HRK": "USDHRK", "DKK": "USDDKK",
    }.items():
        assert we.pairs_for([currency]) == [pair], currency


# ---------------------------------------------------------------------------
# 9. Combined tags + data_filter (behaviour lock, no behaviour change)
# ---------------------------------------------------------------------------


def test_tags_btc_with_actual_drops_btc_world_row():
    """data_filter=with_actual applies to calendar rows only: the BTC world
    row (no Actual cell) is dropped when combined with tags=BTC, while the
    tags-only call keeps it. Locks current behaviour."""
    base = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT()), _FakeFFClient()).execute(
            tags="BTC", limit=100
        )
    )
    assert any("Bitcoin" in r["title"] for r in base.data["rows"])
    combo = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT()), _FakeFFClient()).execute(
            tags="BTC", data_filter="with_actual", limit=100
        )
    )
    assert not any("Bitcoin" in r["title"] for r in combo.data["rows"])
    assert all(r["kind"] == "economic" for r in combo.data["rows"])


def test_gdelt_empty_result_serves_rss_without_note():
    rss = _SlowRSS([
        {
            "title": "RSS wire on budgets",
            "link": "https://example.test/r1",
            "published_at": _iso_in(timedelta(minutes=-30)),
        },
    ])
    result = _run(
        _meet(FunctionDeps(gdelt=_FakeGDELT(articles=[]), rss=rss), _FakeFFClient()).execute(
            kind="world", limit=100
        )
    )
    assert "rss" in result.sources
    assert "(rss served)" not in " ".join(result.warnings)
    world_rows = [r for r in result.data["rows"] if r["kind"] == "world"]
    assert world_rows
    assert all(r["source"] == "rss" for r in world_rows)


def test_undated_empty_url_same_title_dedupes_to_one_row():
    rows = we.world_rows([{"title": "Same wire title"}, {"title": "Same wire title"}], now=datetime.now(UTC), source="rss")
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# D2 Task B — data quality: ALL global + major_only + Turkish + pairs
# ---------------------------------------------------------------------------


def test_all_global_row_bypasses_country_filter_and_skips_index():
    now = datetime.now(UTC)
    rows, _ = we.economic_rows(
        [{
            "country": "ALL",
            "event": "G20 Summit Statement",
            "date": (now + timedelta(hours=4)).isoformat(),
            "importance": "High",
        }],
        now=now,
        source="forex_factory",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["countries"] == []
    assert row["country_names"] == ["Global"]
    assert row["pairs"] == []
    assert row["details"]["provider_country"] == "ALL"
    assert row["details"]["is_global"] is True
    kept = we.apply_filters(rows, countries=["TR"])
    assert [r["id"] for r in kept] == [row["id"]]
    index = we.build_country_index(rows, now=now)
    assert index == []


def test_major_only_drops_lifestyle_noise_keeps_majors():
    now = datetime.now(UTC)
    noise = {
        "id": "world:noise1", "kind": "world",
        "title": "Most Handsome Melons in Mexico",
        "countries": [], "country_names": [], "when_utc": now.isoformat(),
        "impact": "low", "currencies": [], "pairs": [], "source": "rss",
        "spot": False, "pinned": False,
        "details": {"asset_tags": [], "topic_tags": []},
        "seconds_to_event": -60.0, "age_minutes": 1.0,
    }
    grounded_medium = {
        "id": "eco:med1", "kind": "economic", "title": "CPI y/y",
        "countries": ["US"], "country_names": ["United States"],
        "when_utc": now.isoformat(),
        "impact": "medium", "currencies": ["USD"], "pairs": ["DXY"],
        "source": "forex_factory", "spot": False, "pinned": False,
        "details": {"provider_country": "USD", "is_global": False},
        "seconds_to_event": 3600.0, "age_minutes": None,
    }
    major = {
        "id": "eco:major1", "kind": "economic",
        "title": "FOMC Interest Rate Decision",
        "countries": ["US"], "country_names": ["United States"],
        "when_utc": now.isoformat(),
        "impact": "high", "currencies": ["USD"], "pairs": ["DXY"],
        "source": "forex_factory", "spot": True, "pinned": True,
        "details": {"provider_country": "USD", "is_global": False},
        "seconds_to_event": 7200.0, "age_minutes": None,
    }
    rows = [noise, grounded_medium, major]
    assert len(we.apply_filters(rows, data_filter="all")) == 3
    kept = we.apply_filters(rows, data_filter="major_only")
    assert [r["id"] for r in kept] == ["eco:med1", "eco:major1"]


def test_major_only_is_registered_passthrough():
    assert "major_only" in meet_mod._DATA_FILTERS


def test_turkish_rate_decision_world_vs_economic():
    now = datetime.now(UTC)
    world = we.world_rows(
        [{
            "title": "TCMB faiz kararı",
            "url": "https://example.test/tcmb1",
            "published_at": (now - timedelta(hours=1)).isoformat(),
        }],
        now=now,
        source="gdelt",
    )
    assert world[0]["details"]["event_type"] == "rate_decision"
    assert world[0]["impact"] == "medium"
    assert world[0]["spot"] is False
    eco, _ = we.economic_rows(
        [{
            "country": "TRY",
            "event": "TCMB faiz kararı",
            "date": (now + timedelta(hours=4)).isoformat(),
            "importance": "High",
        }],
        now=now,
        source="forex_factory",
    )
    assert eco[0]["spot"] is True


def test_pair_map_task_b_usd_crosses_and_legacy_untouched():
    for currency, pair in {
        "RSD": "USDRSD", "ISK": "USDISK", "GEL": "USDGEL",
        "AMD": "USDAMD", "AZN": "USDAZN",
    }.items():
        assert we.pairs_for([currency]) == [pair], currency
    assert we.pairs_for(["TRY"]) == ["USDTRY", "EURTRY"]
    assert we.pairs_for(["USD"]) == list(we.PAIR_MAP["USD"])
    assert we.pairs_for(["EUR"]) == ["EURUSD", "EURGBP", "EURJPY", "EURCHF"]
