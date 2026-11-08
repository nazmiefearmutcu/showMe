"""BLAK#3 follow-up: a thin common history must not crash or yield a NaN prior.

The live path aligns returns pairwise, so the 10-row guard counts pairwise
rows. The shrinkage and EWMA estimators then drop incomplete rows, so two
symbols that overlap on only one or two days reached Ledoit-Wolf with
T = 1 (ZeroDivisionError) or T = 0 (NaN prior). The estimators need an
honest explicit state instead.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_data_source import DataKind
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.blak import BLAKFunction

_SYMBOLS = ["AAPL", "NEWIPO"]
_CAPS = {"AAPL": 3.9e12, "NEWIPO": 4.0e10}


@dataclass
class _Ref:
    market_cap: float | None = None
    extras: dict | None = None


def _frame(n_rows: int, seed: int, start: str) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n_rows, freq="B")
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, size=n_rows)))
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99,
         "close": close, "volume": 1_000_000},
        index=idx,
    )


class _Yf:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    async def fetch(self, request: Any) -> Any:
        sym = request.instrument.symbol.upper()
        if request.kind == DataKind.REFDATA:
            return _Ref(market_cap=_CAPS.get(sym))
        return self._frames[sym]


def _run(frames: dict[str, pd.DataFrame], **params: Any):
    func = BLAKFunction(deps=FunctionDeps(yfinance=_Yf(frames)))
    return asyncio.run(func.execute(symbols=_SYMBOLS, live=True, **params))


def _thin_overlap_frames(overlap_closes: int) -> dict[str, pd.DataFrame]:
    """AAPL has a long history; NEWIPO only trades for the final closes."""
    aapl = _frame(120, seed=3, start="2025-01-01")
    new_start = aapl.index[-overlap_closes]
    newipo = _frame(overlap_closes, seed=5, start=str(new_start.date()))
    return {"AAPL": aapl, "NEWIPO": newipo}


def test_ledoit_wolf_with_one_overlapping_day_does_not_crash() -> None:
    result = _run(_thin_overlap_frames(overlap_closes=2))
    assert result.data["status"] == "input_error"
    assert result.data["reason"]
    assert result.data["next_actions"]
    assert "prior_covariance" not in result.data
    assert any("overlap" in w.lower() for w in result.warnings)


def test_exp_cov_with_thin_overlap_is_refused_explicitly() -> None:
    result = _run(_thin_overlap_frames(overlap_closes=2), prior_covariance="exp_cov")
    assert result.data["status"] == "input_error"
    assert "prior_covariance" not in result.data


def test_sample_cov_with_thin_overlap_is_refused_not_nan() -> None:
    """Pairwise sample covariance on 2 overlapping days is NaN; refuse, do not crash."""
    result = _run(_thin_overlap_frames(overlap_closes=2), prior_covariance="sample_cov")
    assert result.data["status"] == "input_error"
    assert result.data["overlap_days"] == 1  # two closes give one return day
    assert "prior_covariance" not in result.data


def test_full_overlap_still_runs_for_every_estimator() -> None:
    frames = {"AAPL": _frame(120, seed=3, start="2025-01-01"),
              "NEWIPO": _frame(120, seed=5, start="2025-01-01")}
    for estimator in ("sample_cov", "ledoit_wolf", "exp_cov"):
        result = _run(frames, prior_covariance=estimator)
        assert result.data.get("status") != "input_error", estimator
        assert result.data["prior_covariance_estimator"] == estimator
