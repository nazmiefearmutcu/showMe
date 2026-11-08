"""FXIP data-honesty pins (wb1-g19 FXIP#1 and FXIP#2).

FXIP#1: the 1M ATM vol is an explicit assumption (default 8.45 %), so the
field must not be named "implied". FXIP#2: the policy rates are 2024-06
reference constants, so every rate row and the payload must say so, and the
result must carry a rate-vintage warning. Caller-supplied rates are labelled
as user input instead.

These tests run offline: no yfinance dependency and a manual spot.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.fx._funcs import FXIPFunction


def _run(**params):
    return asyncio.run(FXIPFunction(deps=FunctionDeps()).execute(symbol="EURUSD", spot=1.085, **params))


def _row(result, metric: str) -> dict:
    return next(row for row in result.data["rows"] if row["metric"] == metric)


# ── FXIP#1: the vol field is an assumption, not an implied quote ──────────


def test_atm_vol_field_is_named_assumed_not_implied() -> None:
    result = _run()
    assert "implied_vol_atm_1m" not in result.data
    assert result.data["assumed_vol_atm_1m_pct"] == 8.45


def test_atm_vol_row_is_labelled_as_assumption() -> None:
    result = _run()
    row = _row(result, "atm_vol_1m_pct")
    assert row["source"] == "reference_vol_assumption"
    assert row["value"] == 8.45


def test_caller_supplied_vol_is_still_reported_as_assumed() -> None:
    result = _run(atm_vol=0.10)
    assert result.data["assumed_vol_atm_1m_pct"] == 10.0


# ── FXIP#2: policy rates are dated reference constants ────────────────────


def test_default_policy_rates_are_labelled_with_2024_06_vintage() -> None:
    result = _run()
    basis = result.data["rate_basis"]
    assert basis["base"].startswith("reference_policy_rate")
    assert basis["quote"].startswith("reference_policy_rate")
    assert "2024-06" in basis["base"]
    assert "2024-06" in _row(result, "base_rate")["source"]
    assert "2024-06" in _row(result, "quote_rate")["source"]


def test_default_policy_rates_warn_about_rate_vintage() -> None:
    result = _run()
    assert any("2024-06" in w and "rate" in w.lower() for w in result.warnings), result.warnings


def test_caller_supplied_rates_are_user_input_without_vintage_warning() -> None:
    result = _run(r_base=0.04, r_quote=0.05)
    assert result.data["rate_basis"] == {"base": "user_input", "quote": "user_input"}
    assert _row(result, "base_rate")["source"] == "user_input"
    assert _row(result, "quote_rate")["source"] == "user_input"
    assert not any("2024-06" in w for w in result.warnings), result.warnings
