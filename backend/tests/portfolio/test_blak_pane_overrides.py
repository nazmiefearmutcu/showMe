"""BLAK#5 completion: the pane's relative views and market-cap overrides.

The first BLAK#5 fix exposed absolute views only. This file pins the rest of
what the finding asked for:

* ``views_text`` accepts relative views ``LONG>SHORT:percent`` (a spread row,
  long minus short, expected annual return) next to absolute ``SYMBOL:percent``;
* a relative view with a leg outside the aligned universe is ignored as a whole
  and named in a warning, never applied as a one-sided view;
* ``market_caps`` may arrive as the pane's text ``SYMBOL:USD, ...``; malformed or
  non-positive values are refused with ``input_error``; overrides for symbols
  outside the universe are named in a warning.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_data_source import DataKind
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.blak import BLAKFunction

_SYMBOLS = ["AAPL", "MSFT", "SPY"]
_CAPS = {"AAPL": 3.9e12, "MSFT": 3.5e12, "SPY": 7.9e11}


@dataclass
class _Ref:
    market_cap: float | None = None
    extras: dict = field(default_factory=dict)


def _frame(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=120, freq="B")
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.009, size=120)))
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99,
         "close": close, "volume": 1_000_000},
        index=idx,
    )


class _Yf:
    def __init__(self) -> None:
        self._frames = {sym: _frame(seed) for seed, sym in enumerate(_SYMBOLS, start=31)}

    async def fetch(self, request: Any) -> Any:
        sym = request.instrument.symbol.upper()
        if request.kind == DataKind.REFDATA:
            return _Ref(market_cap=_CAPS.get(sym))
        return self._frames[sym]


def _run(**params: Any):
    func = BLAKFunction(deps=FunctionDeps(yfinance=_Yf()))
    return asyncio.run(func.execute(symbols=_SYMBOLS, live=True, **params))


# --- relative views -------------------------------------------------------

def test_relative_view_text_becomes_a_spread_view() -> None:
    result = _run(views_text="AAPL>SPY:2")
    assert result.data["status"] == "ok"
    assert result.data["n_views"] == 1
    applied = result.data["views_applied"]
    assert len(applied) == 1
    assert applied[0]["long"] == ["AAPL"]
    assert applied[0]["short"] == ["SPY"]
    assert applied[0]["view_type"] == "spread"
    assert applied[0]["expected"] == pytest.approx(0.02)
    active = {row["symbol"]: row["view_active"] for row in result.data["rows"]}
    assert active == {"AAPL": True, "MSFT": False, "SPY": True}


def test_relative_view_moves_both_legs_of_the_posterior() -> None:
    plain = _run()
    spread = _run(views_text="AAPL>SPY:6")
    assert spread.data["posterior_returns"]["AAPL"] > plain.data["posterior_returns"]["AAPL"]
    assert spread.data["posterior_returns"]["SPY"] < plain.data["posterior_returns"]["SPY"]


def test_mixed_absolute_and_relative_views_are_both_applied() -> None:
    result = _run(views_text="MSFT:9, AAPL>SPY:2")
    assert result.data["n_views"] == 2
    kinds = sorted(v["view_type"] for v in result.data["views_applied"])
    assert kinds == ["absolute", "spread"]


def test_relative_view_with_leg_outside_universe_is_ignored_whole() -> None:
    # Applied as a one-sided view this would silently become "AAPL alone",
    # which is not the view the user typed. The whole view is dropped instead.
    result = _run(views_text="AAPL>NVDA:2")
    assert result.data["status"] == "ok"
    assert result.data["n_views"] == 0
    assert any("NVDA" in w and "ignored" in w for w in result.warnings)


@pytest.mark.parametrize("text", ["AAPL>:2", ">SPY:2", "AAPL>AAPL:2", "AAPL>SPY>MSFT:2"])
def test_malformed_relative_view_is_refused(text: str) -> None:
    result = _run(views_text=text)
    assert result.data["status"] == "input_error"
    assert "prior_covariance" not in result.data


# --- market-cap overrides as pane text ------------------------------------

def test_market_caps_text_overrides_the_cap_weights() -> None:
    result = _run(market_caps="AAPL:3, MSFT:1, SPY:1")
    assert result.data["status"] == "ok"
    weights = result.data["market_weights"]
    assert weights["AAPL"] == pytest.approx(0.6)
    assert weights["MSFT"] == pytest.approx(0.2)
    assert weights["SPY"] == pytest.approx(0.2)


def test_market_caps_text_accepts_scientific_notation() -> None:
    result = _run(market_caps="AAPL:3.9e12, MSFT:3.5e12, SPY:7.9e11")
    assert result.data["status"] == "ok"
    assert result.data["market_weights"]["AAPL"] == pytest.approx(3.9e12 / (3.9e12 + 3.5e12 + 7.9e11))


def test_empty_market_caps_text_keeps_provider_resolution() -> None:
    result = _run(market_caps="")
    assert result.data["status"] == "ok"
    assert result.data["market_weights"]["AAPL"] == pytest.approx(
        _CAPS["AAPL"] / sum(_CAPS.values())
    )


@pytest.mark.parametrize("text", ["AAPL", "AAPL:abc", "AAPL:-1", "AAPL:0", ":3"])
def test_malformed_market_caps_text_is_refused(text: str) -> None:
    result = _run(market_caps=text)
    assert result.data["status"] == "input_error"
    assert "prior_covariance" not in result.data


def test_market_cap_override_outside_universe_is_named() -> None:
    result = _run(market_caps="NVDA:5e12")
    assert result.data["status"] == "ok"
    assert any("NVDA" in w and "ignored" in w for w in result.warnings)
