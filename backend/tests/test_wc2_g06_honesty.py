"""WC2-G06 honesty regressions: OVME placeholder inputs, TAUC template horizon.

Each test reproduces a finding through the public handler with the network
patched out (no adapter is reachable here).
"""
from __future__ import annotations

import asyncio

from showme.engine.functions.derivative.ovme import OVMEFunction


def _run_ovme(**params):
    fn = OVMEFunction()
    fn.deps = None
    return asyncio.run(fn.execute(**params))


def test_ovme_with_no_inputs_does_not_price_a_demo_option() -> None:
    res = _run_ovme()
    assert res.data["status"] == "needs_input"
    assert "price" not in res.data
    assert res.data["curve"] == []
    assert set(res.data["missing_inputs"]) == {"spot", "strike", "years_to_expiry", "vol"}


def test_ovme_missing_spot_is_not_filled_with_100() -> None:
    res = _run_ovme(strike=100, years_to_expiry=0.5, vol=0.25)
    assert res.data["status"] == "needs_input"
    assert res.data["missing_inputs"] == ["spot"]
    assert "price" not in res.data


def test_ovme_non_numeric_input_is_an_input_error_not_a_crash() -> None:
    res = _run_ovme(spot="abc", strike=100, years_to_expiry=0.5, vol=0.25)
    assert res.data["status"] == "input_error"
    assert any("spot" in w for w in res.warnings)


# ---------------------------------------------------------------- TAUC#2
from datetime import date, timedelta  # noqa: E402

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.functions.bond.tauc import TAUCFunction  # noqa: E402


def _tauc_reference(**params):
    return asyncio.run(TAUCFunction(FunctionDeps()).execute(reference=True, **params))


def test_tauc_reference_model_honours_the_horizon() -> None:
    res = _tauc_reference(horizon_days=7)
    today = date.today()
    rows = res.data["rows"]
    assert rows, "the 7-day window still holds the nearest model auctions"
    for row in rows:
        day = date.fromisoformat(row["auction_date"][:10])
        assert today - timedelta(days=1) <= day <= today + timedelta(days=7), row


def test_tauc_reference_model_honours_the_limit() -> None:
    res = _tauc_reference(horizon_days=30, limit=2)
    assert len(res.data["rows"]) == 2


def test_tauc_reference_model_invents_no_offering_sizes() -> None:
    res = _tauc_reference(horizon_days=30)
    assert res.data["rows"]
    for row in res.data["rows"]:
        assert row["offering_amount"] is None, row
    assert all(slot["total_offering"] is None for slot in res.data["by_type"])


# ---------------------------------------------------------------- FSRC#1-RQ
from showme.engine.functions.screen._funcs import FSRCFunction  # noqa: E402


def test_fsrc_rows_mark_expense_and_dividend_as_curated_reference() -> None:
    out = asyncio.run(FSRCFunction(deps=FunctionDeps()).execute(query="expenseRatio <= 0.001"))
    assert out.data["rows"]
    for row in out.data["rows"]:
        assert row.get("expense_state") == "reference", row["symbol"]
        assert row.get("dividend_state") == "reference", row["symbol"]


def test_fsrc_field_dictionary_documents_reference_states() -> None:
    out = asyncio.run(FSRCFunction(deps=FunctionDeps()).execute(query="expenseRatio <= 0.001"))
    fields = {entry["field"] for entry in out.data["field_dictionary"]}
    assert {"expense_state", "dividend_state"} <= fields
