"""BLAK#5 regression: the prior's inputs typed in the pane reach the model.

Before the fix the pane could send only symbols and live, so views, tau and
delta were reachable through the API alone. These tests pin the contract the
pane now relies on:

* ``views_text`` ("AAPL:8, SPY:5", percent a year) becomes absolute views and is
  echoed in ``views_applied``;
* a malformed view, tau or delta is refused with ``input_error`` and a reason,
  never replaced by a silent default;
* a view on a symbol outside the aligned universe is named in a warning instead
  of being dropped without a word.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

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


def test_views_text_becomes_absolute_views_and_is_echoed() -> None:
    result = _run(views_text="AAPL:8, SPY:5")
    assert result.data["status"] == "ok"
    assert result.data["n_views"] == 2
    applied = result.data["views_applied"]
    assert [v["long"] for v in applied] == [["AAPL"], ["SPY"]]
    assert [round(v["expected"], 6) for v in applied] == [0.08, 0.05]
    assert all(v["view_type"] == "absolute" for v in applied)
    active = {row["symbol"]: row["view_active"] for row in result.data["rows"]}
    assert active == {"AAPL": True, "MSFT": False, "SPY": True}


def test_views_change_the_posterior() -> None:
    plain = _run()
    viewed = _run(views_text="AAPL:20")
    assert plain.data["posterior_returns"]["AAPL"] != viewed.data["posterior_returns"]["AAPL"]


def test_malformed_view_token_is_refused_not_dropped() -> None:
    result = _run(views_text="AAPL")
    assert result.data["status"] == "input_error"
    assert "AAPL" in result.data["reason"]
    assert "prior_covariance" not in result.data


def test_non_numeric_view_is_refused() -> None:
    result = _run(views_text="AAPL:eight")
    assert result.data["status"] == "input_error"
    assert "AAPL:eight" in result.data["reason"]


def test_non_numeric_tau_is_refused_not_defaulted() -> None:
    result = _run(tau="abc")
    assert result.data["status"] == "input_error"
    assert "tau" in result.data["reason"]
    assert "prior_covariance" not in result.data


def test_out_of_range_tau_and_delta_are_refused() -> None:
    assert _run(tau="1.5").data["status"] == "input_error"
    assert _run(delta="-1").data["status"] == "input_error"


def test_view_on_symbol_outside_the_universe_is_named() -> None:
    result = _run(views_text="NVDA:5")
    assert result.data["status"] == "ok"
    assert result.data["n_views"] == 0
    assert any("NVDA" in w and "ignored" in w for w in result.warnings)


def test_defaults_are_reported_when_fields_are_absent() -> None:
    result = _run()
    assert result.data["tau"] == 0.05
    assert result.data["delta"] == 2.5
    assert result.data["views_applied"] == []
