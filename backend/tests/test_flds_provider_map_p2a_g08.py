"""FLDS provider/availability mapping pins (p2a-g08, FLDS#2).

Network-free: FLDS is an in-process catalog, so execute() is called directly.
"""

from __future__ import annotations

import asyncio

from showme.engine.functions.api.flds import FLDSFunction

_BQL_GET_OHLCV = {"price", "open", "high", "low", "close", "volume"}


def _rows() -> dict[str, dict]:
    res = asyncio.run(FLDSFunction().execute(prefix="", limit=100))
    return {row["field"]: row for row in res.data["rows"]}


def test_every_row_carries_provider_and_availability():
    for field, row in _rows().items():
        assert "provider" in row, field
        assert "availability" in row, field


def test_ohlcv_fields_map_to_the_live_bql_provider():
    rows = _rows()
    for field in _BQL_GET_OHLCV:
        assert rows[field]["provider"] == "yfinance", rows[field]
        assert rows[field]["availability"] == "bql_live_ohlcv", rows[field]


def test_reference_only_fields_have_no_provider_and_say_so():
    rows = _rows()
    for field in ("pe", "revenue", "ytm", "iv_rank"):
        assert rows[field]["provider"] is None, rows[field]
        assert rows[field]["availability"] == "reference_only", rows[field]


def test_availability_agrees_with_bql_get_flag():
    for field, row in _rows().items():
        assert (row["availability"] == "bql_live_ohlcv") is row["bql_get"], (field, row)


def test_field_dictionary_documents_provider_and_availability():
    res = asyncio.run(FLDSFunction().execute(prefix="pe", limit=5))
    dictionary = res.data["field_dictionary"]
    assert "provider" in dictionary
    assert "availability" in dictionary
