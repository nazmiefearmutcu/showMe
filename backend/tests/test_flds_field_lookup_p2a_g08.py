"""FLDS (Field Lookup) honesty and search-quality pins (p2a-g08).

Network-free: FLDS is an in-process catalog, so these tests call execute()
directly.
"""

from __future__ import annotations

import asyncio
import re

from showme.engine.functions.api.flds import FLDSFunction

_BQL_GET_OHLCV = {"price", "open", "high", "low", "close", "volume"}


def _run(prefix: str = "", limit: int = 100):
    return asyncio.run(FLDSFunction().execute(prefix=prefix, limit=limit))


def _fields(res) -> list[str]:
    return [row["field"] for row in res.data["rows"]]


# ── FLDS#3: prefix search must not match arbitrary substrings ───────────────


def test_pe_prefix_does_not_match_substrings_inside_other_words():
    fields = _fields(_run("pe"))
    # "open" contains "pe" only inside the word; "operating_income", "cfo",
    # "capex" have no word or name beginning with "pe".
    for noisy in ("open", "operating_income", "cfo", "capex"):
        assert noisy not in fields, f"{noisy} matched 'pe' by substring: {fields}"


def test_name_prefix_matches_are_ranked_first():
    fields = _fields(_run("pe"))
    assert fields[0] == "pe", fields
    assert "fwd_pe" in fields


def test_every_match_starts_a_name_or_word_with_the_prefix():
    res = _run("pe")
    for row in res.data["rows"]:
        words = set(re.findall(r"[a-z0-9]+", f"{row['field']} {row['description']} {row['category']}".lower()))
        assert row["field"].startswith("pe") or any(w.startswith("pe") for w in words), row


def test_multiword_query_is_a_phrase_match():
    fields = _fields(_run("session open"))
    assert fields == ["open"], fields


# ── FLDS#1: BQL get() only returns OHLCV; the catalog must say so ───────────


def test_bql_get_flag_is_true_only_for_ohlcv_fields():
    rows = {row["field"]: row for row in _run("").data["rows"]}
    for field, row in rows.items():
        assert row["bql_get"] is (field in _BQL_GET_OHLCV), (field, row)
    assert rows["close"]["bql_get"] is True
    assert rows["pe"]["bql_get"] is False


def test_field_dictionary_does_not_claim_bql_accepts_every_field():
    dictionary = _run("").data["field_dictionary"]
    assert "bql_get" in dictionary
    assert "accepted by BQL, screeners" not in dictionary["field"]


# ── FLDS#4: examples must point only at functions that exist ───────────────


def test_examples_do_not_reference_a_screen_function_that_is_not_in_the_index():
    for row in _run("").data["rows"]:
        assert "SCREEN" not in row["example"], row
        assert "screen functions" not in row["example"], row


def test_technical_example_names_the_mlsig_feature_names():
    tech = [r for r in _run("").data["rows"] if r["category"] == "technical"]
    assert tech
    assert all("rsi_14" in r["example"] and "atr_14" in r["example"] for r in tech), tech
