"""MEET Bloomberg Faz 2 — tag hibriti (BTC+makro çekirdek) pins.

Covers the Phase 2 acceptance criteria:
  * ``Bitcoin ETF inflows hit record`` -> asset_tags BTC+ETF, impact != low,
    visible with the country filter off,
  * ``FOMC ... rate`` -> topic_tags FED, event_type=rate_decision,
  * WBTC -> base BTC, WETH -> ETH (+ XBT alias, no satoshi noise),
  * pairs BTCUSD, assets/topics/tags filters,
  * provider-carried tags are unioned, never overwritten,
  * the hybrid AI hook stays silent-passive without onnxruntime.

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

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.comm import meet as meet_mod
from showme.engine.services import news_intelligence as ni
from showme.engine.services import semantic_tagger as st
from showme.engine.services import world_events as we


def _run(coro):
    return asyncio.run(coro)


def _iso_in(offset: timedelta) -> str:
    return (datetime.now(UTC) + offset).isoformat()


def _rows(articles, source="gdelt"):
    return we.world_rows(articles, now=datetime.now(UTC), source=source)


def _by_title(rows, needle):
    return next(r for r in rows if needle in r["title"])


# ---------------------------------------------------------------------------
# Asset / topic tagging
# ---------------------------------------------------------------------------


def test_btc_etf_headline_tags_btc_and_etf_with_raised_impact():
    rows = _rows([{
        "title": "Bitcoin ETF inflows hit record",
        "url": "https://example.test/etf1",
        "published_at": _iso_in(timedelta(hours=-1)),
    }])
    assert len(rows) == 1
    row = rows[0]
    assert "BTC" in row["details"]["asset_tags"]
    assert "ETF" in row["details"]["asset_tags"]
    assert row["impact"] != "low"
    assert row["details"]["event_type"] == "etf_flow"


def test_btc_tagged_row_visible_with_country_filter_off():
    rows = _rows([
        {"title": "Bitcoin ETF inflows hit record", "url": "https://example.test/etf1",
         "published_at": _iso_in(timedelta(hours=-1))},
        {"title": "Turkey parliament debates budget", "url": "https://example.test/tr1",
         "published_at": _iso_in(timedelta(hours=-2))},
    ])
    visible = we.apply_filters(rows, countries=(), limit=100)
    assert any("Bitcoin" in r["title"] for r in visible)


def test_fomc_rate_headline_topic_fed_and_rate_decision():
    rows = _rows([{
        "title": "FOMC announces rate decision as Powell speaks",
        "url": "https://example.test/fomc1",
        "published_at": _iso_in(timedelta(hours=-3)),
    }])
    row = rows[0]
    assert "FED" in row["details"]["topic_tags"]
    assert row["details"]["event_type"] == "rate_decision"
    assert row["impact"] != "low"


def test_inflation_and_employment_event_types():
    rows = _rows([
        {"title": "US CPI inflation cools to 2.4% in June", "url": "https://example.test/cpi1",
         "published_at": _iso_in(timedelta(hours=-1))},
        {"title": "US NFP payrolls beat forecasts as unemployment falls",
         "url": "https://example.test/nfp1", "published_at": _iso_in(timedelta(hours=-2))},
    ])
    assert _by_title(rows, "CPI")["details"]["event_type"] == "inflation_print"
    assert _by_title(rows, "NFP")["details"]["event_type"] == "employment_print"


def test_crypto_pairs_btcusd_and_ethusd():
    rows = _rows([
        {"title": "Bitcoin reclaims 75k on strong demand", "url": "https://example.test/b1",
         "published_at": _iso_in(timedelta(hours=-1))},
        {"title": "Ethereum upgrade lifts ether sentiment", "url": "https://example.test/e1",
         "published_at": _iso_in(timedelta(hours=-2))},
    ])
    assert "BTCUSD" in _by_title(rows, "Bitcoin")["pairs"]
    assert "ETHUSD" in _by_title(rows, "Ethereum")["pairs"]


def test_apply_filters_assets_topics_and_tags():
    rows = _rows([
        {"title": "Bitcoin ETF inflows hit record", "url": "https://example.test/etf1",
         "published_at": _iso_in(timedelta(hours=-1))},
        {"title": "FOMC announces rate decision as Powell speaks",
         "url": "https://example.test/fomc1", "published_at": _iso_in(timedelta(hours=-2))},
    ])
    by_assets = we.apply_filters(rows, assets=("BTC",), limit=100)
    assert [r["title"] for r in by_assets] == ["Bitcoin ETF inflows hit record"]
    by_topics = we.apply_filters(rows, topics=("FED",), limit=100)
    assert [r["title"] for r in by_topics] == ["FOMC announces rate decision as Powell speaks"]
    by_tags = we.apply_filters(rows, tags=("BTC",), limit=100)
    assert any("Bitcoin" in r["title"] for r in by_tags)


# ---------------------------------------------------------------------------
# news_intelligence fixes
# ---------------------------------------------------------------------------


def test_wrapped_tokens_resolve_to_base():
    assert ni.crypto_base("WBTC") == "BTC"
    assert ni.crypto_base("WETH") == "ETH"
    assert ni.crypto_base("BTCUSDT") == "BTC"
    assert ni.crypto_base("ETH") == "ETH"


def test_symbol_terms_btc_gains_xbt_without_satoshi_noise():
    terms = ni.symbol_terms("BTC")
    assert "XBT" in terms
    assert "bitcoin" in terms
    assert not any("satoshi" in str(t).lower() for t in terms)
    assert "ether" in ni.symbol_terms("ETH")


# ---------------------------------------------------------------------------
# Provider ground truth + symbol view
# ---------------------------------------------------------------------------


def test_provider_carried_tags_are_union_not_overwritten():
    rows = _rows([{
        "title": "Market update: funds rotate",
        "category": "Bitcoin",
        "url": "https://example.test/ct1",
        "published_at": _iso_in(timedelta(hours=-1)),
    }], source="symbol_feed")
    row = rows[0]
    assert "BTC" in row["details"]["asset_tags"]
    assert "Bitcoin" in (row["details"].get("provider_tags") or [])


def test_symbol_view_matches_on_asset_tags():
    gdelt_articles = [{
        "title": "Bitcoin ETF inflows hit record",
        "url": "https://example.test/etf1",
        "published_at": _iso_in(timedelta(hours=-3)),
    }]

    class _FakeGDELT:
        calls = 0

        async def fetch(self, request):
            type(self).calls += 1
            return list(gdelt_articles)

    class _FakeFFClient:
        async def get(self, url, timeout=None):
            class _Resp:
                def raise_for_status(self):
                    return None

                def json(self):
                    return []

            return _Resp()

    meet_mod._WORLD_CACHE = None
    meet_mod._SYMBOL_NEWS_CACHE = None
    try:
        fn = meet_mod.MEETFunction(deps=FunctionDeps(gdelt=_FakeGDELT()))
        fn._http_client = _FakeFFClient()
        result = _run(fn.execute(symbols="BTC", limit=100))
    finally:
        meet_mod._WORLD_CACHE = None
        meet_mod._SYMBOL_NEWS_CACHE = None
    headline_rows = [
        r for r in result.data["symbol_rows"]
        if r.get("symbol_relevance") != "market_wide"
    ]
    assert len(headline_rows) == 1
    assert "BTC" in (headline_rows[0].get("symbol_matches") or [])


# ---------------------------------------------------------------------------
# Hybrid hook: passive without onnxruntime
# ---------------------------------------------------------------------------


def test_semantic_hook_passive_without_model():
    assert st.available is False
    suggestion = st.suggest_tags("Bitcoin ETF inflows", rule_tags=["BTC", "ETF"])
    assert suggestion["tag_status"] == "confirmed"
    assert suggestion["tags"] == ["BTC", "ETF"]
    assert st.tag_status(0.5) == "provisional"
    row = {"details": {"asset_tags": ["BTC"]}}
    stamped = st.apply_tags(row, {"tags": [], "tag_status": "provisional"})
    assert stamped["details"]["asset_tags"] == ["BTC"]
    assert stamped["details"]["tag_status"] == "provisional"
