"""MEET Gate-2 — data-quality gates (2026-09-19).

A defective calendar (~40 rows: 2 dateless, 1 exact duplicate, 1 synthetic
``ALL`` global row, 1 unknown ``XX`` token, 1 naive stamp) plus ~30
headlines (5 countryless low-impact noise rows) pins the spec §4
data-quality leg:

  * ``dropped_no_time`` is an exact integer pin (2),
  * the exact duplicate adds zero rows (dupe = 0),
  * the server countdown is exact to ±2 s,
  * the unknown ``XX`` token is a whitelisted loss, not a failure (the
    row survives with empty countries and the loss is listed),
  * the mandatory ISO coverage set holds (US/EU/GB/JP/CH/CA/AU mapping
    + TR mapping existence),
  * the 5 noise headlines stay countryless and low-impact.

Fully offline: no test performs real network I/O.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest  # noqa: E402

from showme.engine.services import world_events as we  # noqa: E402

_NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)

# Mandatory currency -> ISO coverage (calendar tokens, incl. the UK alias).
_REQUIRED_MAPPING = {
    "USD": "US", "EUR": "EU", "GBP": "GB", "JPY": "JP",
    "CHF": "CH", "CAD": "CA", "AUD": "AU", "TRY": "TR",
}

_NOISE_TITLES = {
    "Local bakery wins award for sourdough loaf",
    "New study links morning coffee to longevity",
    "Oracle's $18 billion data center debt under pressure, FT reports",
    "Wales rugby win lifts spirits after rainy final",
    "Local council approves downtown parking plan",
}


def _defective_calendar() -> list[dict]:
    """40 inputs: 35 dated-valid (one naive stamp), 1 exact dupe,
    2 dateless, 1 ALL global, 1 unknown XX."""
    rows: list[dict] = [
        # Required-ISO coverage rows (UK exercises the provider alias fold).
        {"country": "USD", "event": "Countdown pin", "date": (_NOW + timedelta(hours=1)).isoformat(), "importance": "High"},
        {"country": "EUR", "event": "Euro area print", "date": (_NOW + timedelta(hours=2)).isoformat(), "importance": "High"},
        {"country": "UK", "event": "Official Bank Rate", "date": (_NOW + timedelta(hours=3)).isoformat(), "importance": "High"},
        {"country": "JPY", "event": "Naive stamp print", "date": (_NOW + timedelta(hours=50)).replace(tzinfo=None).isoformat(), "importance": "Medium"},
        {"country": "CHF", "event": "SNB assessment", "date": (_NOW + timedelta(hours=4)).isoformat(), "importance": "Medium"},
        {"country": "CAD", "event": "Canada CPI", "date": (_NOW + timedelta(hours=5)).isoformat(), "importance": "Medium"},
        {"country": "AUD", "event": "RBA minutes", "date": (_NOW + timedelta(hours=6)).isoformat(), "importance": "Medium"},
        {"country": "TRY", "event": "TCMB decision", "date": (_NOW + timedelta(hours=7)).isoformat(), "importance": "High"},
    ]
    filler_ccy = ["USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "TRY", "NZD", "SEK"]
    for i in range(27):
        rows.append({
            "country": filler_ccy[i % len(filler_ccy)],
            "event": f"Filler print {i:02d}",
            "date": (_NOW + timedelta(hours=8 + i)).isoformat(),
            "importance": "Low" if i % 2 else "Medium",
        })
    assert len(rows) == 35
    rows.append(dict(rows[10]))  # exact duplicate -> deduped, adds 0 rows
    rows.append({"country": "USD", "event": "No time A", "date": "", "importance": "High"})
    rows.append({"country": "EUR", "event": "No time B", "date": None, "importance": "Low"})
    rows.append({"country": "ALL", "event": "Global summit", "date": (_NOW + timedelta(hours=60)).isoformat(), "importance": "Medium"})
    rows.append({"country": "XX", "event": "Mystery print", "date": (_NOW + timedelta(hours=61)).isoformat(), "importance": "Low"})
    assert len(rows) == 40
    return rows


def _headlines() -> list[dict]:
    tagged = [
        "ECB holds rates steady as Brussels approves eurozone budget",
        "UK Official Bank Rate decision lifts pound to weekly high",
        "US and China hold Taiwan talks as Beijing warns Washington",
        "Missile strikes hit power grid after invasion escalation",
        "Bitcoin plunges as war fears grip crypto markets",
        "Crypto bridge hacked for $200M in major security breach",
        "Bitcoin ETF inflows hit record as BTC reclaims 75k",
        "btc reclaims 75k on strong demand",
        "TCMB faiz kararı sonrası dolar kuru yükseldi",
        "Turkeyrate decision expected Thursday, traders say",
        "US NFP payrolls beat forecasts as unemployment falls",
        "SEC sues crypto exchange over unregistered securities",
        "Bitcoin halving cuts miner rewards for fourth cycle",
        "US CPI inflation cools to 2.4% in June",
        "FOMC announces rate decision as Powell speaks",
        "Trump extends restrictions on H-1B visa program",
        "France and Germany agree cross-border accord in Paris",
        "Ethereum upgrade lifts ether sentiment",
        "Grayscale GBTC outflows slow as IBIT keeps gaining",
        "BOJ's Ueda hints at hike as yen slides",
        "China unveils stimulus as Shanghai stocks jump",
        "Japan's Nikkei hits record as yen weakens",
        "Swiss franc firms as Zurich markets rally",
        "Israel airstrikes target Gaza tunnels amid truce talks",
        "Singapore stocks rally as Straits Times hits record",
    ]
    assert len(tagged) == 25
    texts = tagged + sorted(_NOISE_TITLES)
    assert len(texts) == 30
    pub = (_NOW - timedelta(hours=1)).isoformat()
    return [
        {"title": text, "url": f"https://example.test/dq/{i:02d}", "published_at": pub}
        for i, text in enumerate(texts)
    ]


def _by_title(rows, title):
    return next(r for r in rows if r["title"] == title)


def test_dropped_no_time_is_exact_integer_pin():
    rows, dropped = we.economic_rows(_defective_calendar(), now=_NOW)
    assert isinstance(dropped, int)
    assert dropped == 2
    assert len(rows) == 37  # 40 inputs - 2 dateless - 1 exact dupe


def test_exact_duplicate_adds_zero_rows():
    calendar = _defective_calendar()
    rows, _ = we.economic_rows(calendar, now=_NOW)
    titles = [r["title"] for r in rows]
    assert titles.count("Filler print 02") == 1
    # Same input twice -> same output (idempotent dedupe).
    rows2, _ = we.economic_rows(calendar + [dict(calendar[10])], now=_NOW)
    assert len(rows2) == len(rows)


def test_server_countdown_within_two_seconds():
    rows, _ = we.economic_rows(_defective_calendar(), now=_NOW)
    pin = _by_title(rows, "Countdown pin")
    assert pin["seconds_to_event"] == pytest.approx(3600.0, abs=2.0)
    assert pin["when_utc"] == "2026-09-19T13:00:00+00:00"


def test_all_token_is_global_row_without_pairs():
    rows, _ = we.economic_rows(_defective_calendar(), now=_NOW)
    row = _by_title(rows, "Global summit")
    assert row["countries"] == []
    assert row["country_names"] == ["Global"]
    assert row["pairs"] == []
    assert row["details"]["is_global"] is True
    assert row["details"]["provider_country"] == "ALL"


def test_unknown_xx_token_is_whitelisted_loss_not_failure():
    rows, dropped = we.economic_rows(_defective_calendar(), now=_NOW)
    assert we.canonical_iso("XX") == ""
    row = _by_title(rows, "Mystery print")
    assert row["countries"] == []
    assert row["details"]["provider_country"] == "XX"
    assert not row["details"].get("is_global")
    # The loss is listed (auditable), and nothing else was dropped for it.
    lost = [
        r for r in rows
        if not r["countries"] and not (r["details"] or {}).get("is_global")
    ]
    assert [r["title"] for r in lost] == ["Mystery print"]
    assert dropped == 2


def test_naive_stamp_parsed_as_utc():
    rows, _ = we.economic_rows(_defective_calendar(), now=_NOW)
    row = _by_title(rows, "Naive stamp print")
    assert row["when_utc"] == "2026-09-21T14:00:00+00:00"
    assert row["countries"] == ["JP"]


def test_mandatory_iso_coverage_and_tr_mapping():
    for token, iso in _REQUIRED_MAPPING.items():
        assert we.canonical_iso(token) == iso, token
    assert we.canonical_iso("UK") == "GB"
    assert "TRY" in we.CURRENCY_TO_ISO
    rows, _ = we.economic_rows(_defective_calendar(), now=_NOW)
    seen = {iso for r in rows for iso in r["countries"]}
    assert {"US", "EU", "GB", "JP", "CH", "CA", "AU", "TR"} <= seen


def test_headline_noise_stays_countryless_and_low():
    rows = we.world_rows(_headlines(), now=_NOW, source="gdelt")
    assert len(rows) == 30
    for title in _NOISE_TITLES:
        row = _by_title(rows, title)
        assert row["countries"] == [], title
        assert row["impact"] == "low", title


def test_headline_country_tags_stay_auditable():
    rows = we.world_rows(_headlines(), now=_NOW, source="gdelt")
    for row in rows:
        assert row["when_utc"]
        assert len(row["details"]["matched_terms"]) == len(row["countries"]), row["title"]


@pytest.mark.parametrize("headline", ["BOJ raises interest rate", "BoJ raises interest rate"])
def test_boj_common_casing_tags_japan_and_boj(headline):
    row = we.world_rows(
        [{"title": headline, "published_at": _NOW.isoformat()}], now=_NOW
    )[0]
    assert row["countries"] == ["JP"]
    assert row["details"]["topic_tags"] == ["BOJ"]


def test_north_korean_does_not_false_positive_south_korea():
    row = we.world_rows(
        [{"title": "North Korean troops cross border", "published_at": _NOW.isoformat()}],
        now=_NOW,
    )[0]
    assert row["countries"] == ["KP"]


def test_explicit_north_and_south_korean_headline_keeps_both():
    row = we.world_rows([{
        "title": "North Korea and South Korean officials reopen talks",
        "published_at": _NOW.isoformat(),
    }], now=_NOW)[0]
    assert row["countries"] == ["KR", "KP"]


def test_provider_canonical_tags_survive_and_raw_tags_remain_auditable():
    row = we.world_rows([{
        "title": "Policy update",
        "published_at": _NOW.isoformat(),
        "topic_tags": ["FED"],
        "asset_tags": ["eth", "ETF"],
    }], now=_NOW)[0]
    assert row["details"]["topic_tags"] == ["FED"]
    assert set(row["details"]["asset_tags"]) == {"ETH", "ETF"}
    assert row["details"]["provider_tags"] == ["eth", "ETF", "FED"]


@pytest.mark.parametrize(
    "headline",
    [
        "Capital inflows strengthen the currency",
        "Bank deposit outflows accelerate",
        "Global fund inflows rise in September",
    ],
)
def test_generic_flows_are_not_etf_flows(headline):
    row = we.world_rows(
        [{"title": headline, "published_at": _NOW.isoformat()}], now=_NOW
    )[0]
    assert "ETF" not in row["details"]["asset_tags"]
    assert row["details"]["event_type"] != "etf_flow"


@pytest.mark.parametrize("headline", ["Bitcoin ETF inflows surge", "GBTC outflows continue"])
def test_named_etf_flows_remain_etf_flows(headline):
    row = we.world_rows(
        [{"title": headline, "published_at": _NOW.isoformat()}], now=_NOW
    )[0]
    assert "ETF" in row["details"]["asset_tags"]
    assert row["details"]["event_type"] == "etf_flow"


@pytest.mark.parametrize(
    "headline",
    ["Nuclear power plant opens new reactor", "Nuclear energy output reaches a record"],
)
def test_civilian_nuclear_headlines_are_not_conflict(headline):
    row = we.world_rows(
        [{"title": headline, "published_at": _NOW.isoformat()}], now=_NOW
    )[0]
    assert row["details"]["event_type"] != "geopolitics"
    assert row["impact"] != "high"
    assert row["spot"] is False


@pytest.mark.parametrize(
    "headline",
    [
        "Nuclear weapons threat escalates",
        "Military nuclear warhead test raises tensions",
        "Nuclear threats increase regional tensions",
        "Nuclear tests raise security concerns",
        "Nuclear strikes remain possible",
        "Nuclear arsenals expand amid confrontation",
    ],
)
def test_military_nuclear_headlines_remain_high_conflict(headline):
    row = we.world_rows(
        [{"title": headline, "published_at": _NOW.isoformat()}], now=_NOW
    )[0]
    assert row["details"]["event_type"] == "geopolitics"
    assert row["impact"] == "high"
    assert row["spot"] is True
