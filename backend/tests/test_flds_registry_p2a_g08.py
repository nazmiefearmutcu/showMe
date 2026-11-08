"""FLDS field registry pins (p2a-g08, FLDS#2).

Network-free: FLDS is an in-process catalog, so execute() is called directly.
Every catalog row must carry a mnemonic alias and a unit. Names added beyond
the original OHLCV/valuation set are reference-only: provider is null and no
value is returned for them, so no data is implied.
"""

from __future__ import annotations

import asyncio

from showme.engine.functions.api.flds import FLDSFunction

_BQL_GET_OHLCV = {"price", "open", "high", "low", "close", "volume"}
_ADDED_REFERENCE_FIELDS = {
    "eps_ttm",
    "eps_fwd",
    "book_value_per_share",
    "ebitda",
    "gross_profit",
    "free_cash_flow",
    "dividend_per_share",
    "roe",
    "gross_margin",
    "debt_to_equity",
    "current_ratio",
    "coupon",
    "yield_to_worst",
    "implied_vol",
}


def _all_rows() -> list[dict]:
    return asyncio.run(FLDSFunction().execute(prefix="", limit=100)).data["rows"]


def _rows() -> dict[str, dict]:
    return {row["field"]: row for row in _all_rows()}


def test_every_row_carries_mnemonic_and_unit():
    for row in _all_rows():
        assert isinstance(row.get("mnemonic"), str) and row["mnemonic"], row
        assert isinstance(row.get("unit"), str) and row["unit"], row


def test_mnemonics_are_unique_and_uppercase_identifiers():
    mnemonics = [row["mnemonic"] for row in _all_rows()]
    assert len(mnemonics) == len(set(mnemonics)), mnemonics
    for mnemonic in mnemonics:
        assert mnemonic == mnemonic.upper() and mnemonic.replace("_", "").isalnum(), mnemonic


def test_price_mnemonic_is_px_last_and_units_are_right():
    rows = _rows()
    assert rows["price"]["mnemonic"] == "PX_LAST"
    assert rows["price"]["unit"] == "currency"
    assert rows["volume"]["unit"] == "shares"
    assert rows["pe"]["unit"] == "ratio (x)"
    assert rows["ytm"]["unit"] == "percent (%)"
    assert rows["div_yield"]["unit"] == "percent (%)"
    assert rows["rsi"]["unit"] == "index (0-100)"
    assert rows["duration"]["unit"] == "years"


def test_catalog_grows_beyond_the_original_35_names():
    rows = _rows()
    assert len(rows) >= 49, len(rows)
    for field in _ADDED_REFERENCE_FIELDS:
        assert field in rows, field


def test_added_fields_are_reference_only_with_no_provider_or_value():
    rows = _rows()
    for field in _ADDED_REFERENCE_FIELDS:
        row = rows[field]
        assert row["provider"] is None, row
        assert row["availability"] == "reference_only", row
        assert row["bql_get"] is False, row
        assert "value" not in row and "price" not in row and "last" not in row, row


def test_no_non_ohlcv_field_is_mapped_to_a_provider():
    for row in _all_rows():
        if row["field"] in _BQL_GET_OHLCV:
            assert row["provider"] == "yfinance", row
        else:
            assert row["provider"] is None, row


def test_mnemonic_is_searchable_as_a_word():
    fields = [row["field"] for row in asyncio.run(FLDSFunction().execute(prefix="px_last", limit=20)).data["rows"]]
    assert fields[:1] == ["price"], fields


def test_field_dictionary_documents_mnemonic_and_unit():
    dictionary = asyncio.run(FLDSFunction().execute(prefix="pe", limit=5)).data["field_dictionary"]
    assert "mnemonic" in dictionary
    assert "unit" in dictionary
    assert "alias" in dictionary["mnemonic"].lower()
