"""SECF text search must match whole words (word-start), not substrings.

Regression for wb1-g19 SECF#1: a substring test made the query "technology"
match "biotechnology" tags (ABBV, XLV, ...). The query must match a token that
starts at a word boundary, so "tech" still prefixes "technology" but never
matches inside "biotechnology".
"""

from __future__ import annotations

import asyncio

from showme.engine.functions.screen._funcs import SECFFunction, _security_text_search


def _row(symbol: str, name: str, tags: list[str]) -> dict:
    return {
        "symbol": symbol,
        "name": name,
        "exchange": "NASDAQ",
        "asset_class": "EQUITY",
        "sector": "Health Care",
        "tags": tags,
    }


def test_technology_does_not_match_biotechnology_tag() -> None:
    rows = [
        _row("ABBV", "AbbVie Inc.", ["biotechnology", "large cap"]),
        _row("ORCL", "Oracle Corporation", ["technology", "software"]),
    ]
    matched = _security_text_search(rows, "technology")
    symbols = [row["symbol"] for row in matched]
    assert symbols == ["ORCL"], f"biotech row must not match 'technology': {symbols}"


def test_prefix_at_word_start_still_matches() -> None:
    rows = [_row("ORCL", "Oracle Corporation", ["technology", "software"])]
    assert [r["symbol"] for r in _security_text_search(rows, "tech")] == ["ORCL"]


def test_symbol_with_punctuation_still_matches() -> None:
    rows = [_row("GC=F", "Gold Futures", ["metals"])]
    assert [r["symbol"] for r in _security_text_search(rows, "GC=F")] == ["GC=F"]


def test_all_terms_flag_requires_whole_word_for_every_term() -> None:
    rows = [
        _row("ABBV", "AbbVie Inc.", ["biotechnology", "large cap"]),
        _row("ORCL", "Oracle Corporation", ["technology", "software"]),
    ]
    matched = {r["symbol"]: r["match"] for r in _security_text_search(rows, "technology software")}
    assert matched == {"ORCL": "all_terms"}


def test_secf_text_query_drops_biotech_false_positives() -> None:
    out = asyncio.run(SECFFunction().execute(query="technology", reference=True, limit=500))
    symbols = {row["symbol"] for row in out.data["rows"]}
    # ABBV and XLV only matched through "biotechnology" tags.
    assert "ABBV" not in symbols
    assert "XLV" not in symbols
    # Real technology names and the technology sector ETF still match.
    assert {"AAPL", "MSFT", "XLK"} <= symbols
