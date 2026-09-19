"""MEET RSS feed-config parity: code, YAML config and probe measure one list.

Regression pin for the round-4 finding: ``backend/config/data_sources.yaml``
overrode ``RSSAdapter._MARKET_FEEDS`` with a stale 10-feed list (no world
wires), so production MEET starved while ``scripts/meet_probe.py`` measured
the code's 14-feed list and reported healthy. All three must agree as sets.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from showme.engine.data_sources.news.rss_adapter import (
    _CRYPTO_FEEDS,
    _DEFAULT_FEEDS,
    _MARKET_FEEDS,
)

_BACKEND = Path(__file__).resolve().parents[1]
REPO = _BACKEND.parent


def _yaml_rss() -> dict:
    with open(_BACKEND / "config" / "data_sources.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["adapters"]["rss"]


def _probe_full_feeds() -> list[str]:
    text = (REPO / "scripts" / "meet_probe.py").read_text(encoding="utf-8")
    block = text.split("RSS_FEEDS_FULL = [", 1)[1].split("]", 1)[0]
    return re.findall(r'"(https?://[^"]+)"', block)


def test_yaml_market_feeds_match_code():
    assert set(_yaml_rss()["market_feeds"]) == set(_MARKET_FEEDS)


def test_yaml_combined_feeds_match_code():
    assert set(_yaml_rss()["feeds"]) == set(_DEFAULT_FEEDS)


def test_yaml_crypto_feeds_match_code():
    assert set(_yaml_rss()["crypto_feeds"]) == set(_CRYPTO_FEEDS)


def test_probe_full_feeds_match_code_market_list():
    assert set(_probe_full_feeds()) == set(_MARKET_FEEDS)


def test_no_dead_globenewswire_anywhere():
    for source in (
        list(_MARKET_FEEDS) + list(_DEFAULT_FEEDS)
        + list(_yaml_rss()["market_feeds"]) + list(_yaml_rss()["feeds"])
        + _probe_full_feeds()
    ):
        assert "globenewswire" not in source.lower()


def test_world_wires_present_everywhere():
    required = {
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://feeds.bbci.co.uk/news/business/rss.xml",
        "https://www.theguardian.com/world/rss",
    }
    assert required <= set(_MARKET_FEEDS)
    assert required <= set(_yaml_rss()["market_feeds"])
    assert required <= set(_probe_full_feeds())
