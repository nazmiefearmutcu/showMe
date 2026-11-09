"""FLDS#1-RQ / FLDS#2-RQ: reference-only rows must not imply screener or BQL use.

The catalog methodology says reference-only names are "not implied to be BQL,
screener or analytics fields". The per-category example used to put an EQS or
SRCH query on those rows (for example coupon and yield_to_worst showed
"SRCH query: ytm >= 4 AND duration <= 10"), which contradicts that claim.

Network-free: FLDS is an in-process catalog, so execute() is called directly.
"""

from __future__ import annotations

import asyncio

from showme.engine.functions.api.flds import _BQL_GET_FIELDS, FLDSFunction

_SCREENER_MARKERS = ("EQS", "SRCH", "SCREEN")


def _rows() -> list[dict]:
    res = asyncio.run(FLDSFunction().execute(prefix="", limit=100))
    return res.data["rows"]


def test_reference_only_rows_do_not_name_a_screener_example() -> None:
    reference = [r for r in _rows() if r["field"] not in _BQL_GET_FIELDS and r["category"] != "technical"]
    assert reference
    for row in reference:
        for marker in _SCREENER_MARKERS:
            assert marker not in row["example"], (row["field"], row["example"])


def test_coupon_and_yield_to_worst_no_longer_show_a_srch_query() -> None:
    by_field = {r["field"]: r for r in _rows()}
    for field in ("coupon", "yield_to_worst", "ytm", "duration"):
        assert "SRCH query" not in by_field[field]["example"], by_field[field]
        assert by_field[field]["bql_get"] is False


def test_eps_ttm_and_pe_do_not_show_an_eqs_query() -> None:
    by_field = {r["field"]: r for r in _rows()}
    for field in ("eps_ttm", "pe"):
        assert "EQS query" not in by_field[field]["example"], by_field[field]


def test_bql_get_fields_keep_their_concrete_example() -> None:
    by_field = {r["field"]: r for r in _rows()}
    assert by_field["close"]["example"].startswith("BQL get(close, volume)")


def test_reference_rows_say_bql_get_does_not_return_them() -> None:
    by_field = {r["field"]: r for r in _rows()}
    assert "bql_get" in by_field["pe"]["example"] or "BQL get()" in by_field["pe"]["example"]
