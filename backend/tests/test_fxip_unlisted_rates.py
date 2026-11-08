"""FXIP#2 follow-up: unlisted currencies must not get an invented policy rate.

``_rate_for`` silently returns 0.04 for any currency missing from the 2024-06
reference table. FXIP must not present that value as a dated reference rate,
so an unlisted currency with no caller-supplied rate yields an explicit
``needs_input`` state with null rates, forwards and carry.

These tests run offline: a manual spot and no adapters.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.fx._funcs import FXIPFunction


def _run(**params):
    return asyncio.run(
        FXIPFunction(deps=FunctionDeps()).execute(symbol="USDSEK", spot=10.5, **params)
    )


def _row(result, metric: str) -> dict:
    return next(row for row in result.data["rows"] if row["metric"] == metric)


def test_unlisted_quote_currency_is_not_given_an_invented_rate() -> None:
    result = _run()
    assert result.data["status"] == "needs_input"
    assert _row(result, "quote_rate")["value"] is None
    assert 0.04 not in [row["value"] for row in result.data["rows"]]


def test_unlisted_currency_is_not_labelled_as_dated_reference_rate() -> None:
    result = _run()
    quote_source = result.data["rate_basis"]["quote"]
    assert "2024-06" not in quote_source
    assert not quote_source.startswith("reference_policy_rate")
    assert "2024-06" not in _row(result, "quote_rate")["source"]


def test_forwards_and_carry_are_null_when_a_rate_is_unavailable() -> None:
    result = _run()
    assert result.data["one_month_forward"] is None
    assert result.data["three_month_forward"] is None
    assert result.data["carry_annualized"] is None
    assert _row(result, "1m_forward")["value"] is None
    assert _row(result, "3m_forward")["value"] is None
    assert _row(result, "carry_annualized")["value"] is None


def test_unavailable_state_explains_reason_and_next_actions() -> None:
    result = _run()
    assert result.data.get("reason")
    assert "SEK" in result.data["reason"]
    assert result.data.get("next_actions")


def test_listed_base_with_caller_quote_rate_still_computes_forwards() -> None:
    result = _run(r_quote=0.03)
    assert result.data.get("status") != "needs_input"
    assert result.data["rate_basis"]["quote"] == "user_input"
    assert _row(result, "quote_rate")["value"] == 0.03
    assert result.data["one_month_forward"] is not None
    assert result.data["carry_annualized"] is not None
