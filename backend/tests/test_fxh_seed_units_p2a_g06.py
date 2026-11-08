"""P2A-G06 FXH#2: the manifest hedge-cost text must match the handler's pip size.

The handler uses pip_size 0.0001, or 0.01 when the home (quote) currency is JPY.
The seed used to say cost = hedge_notional x (bid_ask_pips / 10000) everywhere,
which is 100x off for USDJPY. These tests pin the seed text to the handler.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.fx.fxh import FXHFunction
from showme.manifest.seeds.fxh_seed import fxh


def test_fxh_seed_methodology_describes_pip_size_for_jpy() -> None:
    text = fxh.methodology
    assert "/ 10000" not in text
    assert "10000)" not in text
    assert "JPY" in text
    assert "0.01" in text
    assert "0.0001" in text


def test_fxh_seed_hedge_cost_formula_names_pip_size_not_fixed_divisor() -> None:
    formula = fxh.formula_dict["hedge_cost"]
    assert "10^{4}" not in formula.expression
    assert "pip" in formula.expression.lower() or "p" in formula.variables
    assert "JPY" in " ".join(formula.variables.values()) or "JPY" in (formula.notes or "")


def test_fxh_handler_usdjpy_hedge_cost_uses_jpy_pip_size() -> None:
    """USDJPY: home defaults to the JPY quote, so pip = 0.01 JPY.

    hedge_notional 750,000 USD x 2 pips x 0.01 = 15,000 JPY. The manifest text
    must describe this, so the number is not 100x the documented formula.
    """
    result = asyncio.run(FXHFunction(deps=FunctionDeps(yfinance=None)).execute(
        action="calc", pair="USDJPY", spot_rate=150.0, notional=1_000_000,
        base_rate=0.02, home_rate=0.03, hedge_ratio=0.75, bid_ask_pips=2.0,
    ))
    assert result.data["hedge_cost"] == pytest.approx(15_000.0)
    assert result.data["hedge_cost"] == pytest.approx(
        result.data["hedge_notional"] * 2.0 * 0.01
    )
