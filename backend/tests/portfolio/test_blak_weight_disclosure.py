"""BLAK#7 regression: the long-only clip and renormalization are disclosed.

``optimal_weight`` clips negative mean-variance weights to zero and renormalizes
(black_litterman.implied_optimal_weights). Before the fix the payload gave no
trace of the raw solution, so the renormalized numbers looked like the
unconstrained answer. These tests pin:

* every row carries ``optimal_weight_unconstrained`` next to ``optimal_weight``;
* with no views the unconstrained weights sum to 1/(1+tau), which is the
  documented round trip, and ``optimal_weight`` returns the market weights;
* the methodology and field dictionary name the clip and renormalization.
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
        self._frames = {sym: _frame(seed) for seed, sym in enumerate(_SYMBOLS, start=21)}

    async def fetch(self, request: Any) -> Any:
        sym = request.instrument.symbol.upper()
        if request.kind == DataKind.REFDATA:
            return _Ref(market_cap=_CAPS.get(sym))
        return self._frames[sym]


def _run(**params: Any):
    func = BLAKFunction(deps=FunctionDeps(yfinance=_Yf()))
    return asyncio.run(func.execute(symbols=_SYMBOLS, live=True, **params))


def test_rows_carry_the_unconstrained_weight_beside_the_long_only_one() -> None:
    result = _run()
    for row in result.data["rows"]:
        assert "optimal_weight_unconstrained" in row
        assert "optimal_weight" in row
    raw = result.data["implied_optimal_weights_unconstrained"]
    assert set(raw) == set(_SYMBOLS)


def test_no_view_round_trip_and_raw_sum_are_disclosed() -> None:
    result = _run()
    tau = result.data["tau"]
    # With no views the raw weights are w_mkt / (1 + tau), so they sum to 1/(1+tau).
    assert abs(result.data["optimal_weight_raw_sum"] - 1.0 / (1.0 + tau)) < 1e-9
    # Clipping + renormalizing the raw weights returns the market weights.
    for row in result.data["rows"]:
        assert abs(row["optimal_weight"] - row["market_weight"]) < 1e-9
        assert abs(row["optimal_weight_unconstrained"] * (1.0 + tau) - row["market_weight"]) < 1e-9


def test_methodology_and_field_dictionary_name_the_transformation() -> None:
    result = _run()
    assert "clipped" in result.data["methodology"]
    assert "renormalized" in result.data["methodology"]
    fields = result.data["field_dictionary"]
    assert "long-only" in fields["optimal_weight"].lower()
    assert "clipping" in fields["optimal_weight_unconstrained"].lower()
    assert "optimal_weight_raw_sum" in fields["optimal_weight_unconstrained"]


def test_unconstrained_weights_are_consistent_with_the_posterior() -> None:
    """The raw column is the true (delta * Sigma_BL)^-1 pi_BL solution."""
    result = _run()
    delta = result.data["delta"]
    cols = result.data["symbols"]
    cov = np.array([[result.data["prior_covariance"][a][b] for b in cols] for a in cols])
    pi_bl = np.array([result.data["posterior_returns"][s] for s in cols])
    # Posterior return covariance is Sigma + tau*Sigma when no views are active.
    tau = result.data["tau"]
    sigma_bl = cov * (1.0 + tau)
    expected = np.linalg.pinv(delta * sigma_bl) @ pi_bl
    got = np.array([result.data["implied_optimal_weights_unconstrained"][s] for s in cols])
    assert np.allclose(got, expected, rtol=1e-7, atol=1e-10)
    assert np.allclose(got.sum(), np.sum(expected))
    assert np.isfinite(np.asarray(got)).all()
