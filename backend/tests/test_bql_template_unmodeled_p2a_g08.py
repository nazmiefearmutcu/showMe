"""BQL template (computed_model) must not fabricate unmodeled fields (p2a-g08, FLDS#1).

Network-free: the template path never calls a provider; the offline payload is
built in-process, so these tests call execute() directly.
"""

from __future__ import annotations

import asyncio

from showme.engine.functions.api.bql import BQLFunction


def _run(query: str):
    return asyncio.run(BQLFunction().execute(query=query, symbols="AAPL", days=30)).data


def test_unmodeled_fundamental_field_is_null_not_the_close_value():
    data = _run("get(close, pe) for(['AAPL'])")
    rows = data["rows"]
    assert rows, data
    for row in rows:
        assert row["pe"] is None, row
        assert row["pe"] != row["close"], row


def test_unmodeled_field_is_reported_as_a_warning():
    data = _run("get(close, pe) for(['AAPL'])")
    assert any("pe" in str(w) for w in data["warnings"]), data["warnings"]


def test_modeled_ohlcv_fields_are_still_returned_as_numbers():
    data = _run("get(close, volume) for(['AAPL'])")
    for row in data["rows"]:
        assert isinstance(row["close"], float), row
        assert isinstance(row["volume"], int), row
    assert data["warnings"] == []
