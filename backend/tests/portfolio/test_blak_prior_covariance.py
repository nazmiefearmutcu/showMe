"""BLAK#3 regression: the declared prior_covariance estimator must be applied.

The seed declared ``prior_covariance`` with options sample_cov / ledoit_wolf /
exp_cov and default ``ledoit_wolf``, but the handler always used the plain
sample covariance and never read the input. These tests pin:

* default run reports ``ledoit_wolf`` with a real shrinkage intensity and
  the shrunk matrix (1 - delta) * S + delta * mu * I (Ledoit & Wolf 2004 target);
* ``sample_cov`` reproduces the plain sample covariance with no shrinkage;
* ``exp_cov`` is applied (differs from the sample matrix, symmetric);
* an unknown estimator is refused with an explicit input_error, not ignored.
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

_SYMBOLS = ["AAPL", "MSFT", "SPY"]
_CAPS = {"AAPL": 3.9e12, "MSFT": 3.5e12, "SPY": 7.9e11}


@dataclass
class _Ref:
    market_cap: float | None = None
    extras: dict | None = None


def _frames(n_rows: int = 120, seed: int = 11) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    common = rng.normal(0.0004, 0.008, size=n_rows)
    idx = pd.date_range("2025-01-01", periods=n_rows, freq="B")
    out: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(_SYMBOLS):
        daily = 0.6 * common + rng.normal(0.0, 0.006 + 0.002 * i, size=n_rows)
        close = 100.0 * np.exp(np.cumsum(daily))
        out[sym] = pd.DataFrame(
            {"open": close, "high": close * 1.01, "low": close * 0.99,
             "close": close, "volume": 1_000_000},
            index=idx,
        )
    return out


class _Yf:
    def __init__(self) -> None:
        self._frames = _frames()

    async def fetch(self, request: Any) -> Any:
        sym = request.instrument.symbol.upper()
        if request.kind == DataKind.REFDATA:
            return _Ref(market_cap=_CAPS.get(sym))
        return self._frames[sym]


def _run(**params: Any):
    func = BLAKFunction(deps=FunctionDeps(yfinance=_Yf()))
    return asyncio.run(func.execute(symbols=_SYMBOLS, live=True, **params))


def _matrix(payload: dict[str, dict[str, float]]) -> np.ndarray:
    return np.array([[payload[a][b] for b in _SYMBOLS] for a in _SYMBOLS])


def test_default_estimator_is_ledoit_wolf_and_shrinks() -> None:
    result = _run()
    assert result.data["prior_covariance_estimator"] == "ledoit_wolf"
    delta = result.data["shrinkage_intensity"]
    assert 0.0 < delta <= 1.0

    sample = _matrix(_run(prior_covariance="sample_cov").data["prior_covariance"])
    shrunk = _matrix(result.data["prior_covariance"])
    mu = np.trace(sample) / len(_SYMBOLS)
    expected = (1 - delta) * sample + delta * mu * np.eye(len(_SYMBOLS))
    assert np.allclose(shrunk, expected, rtol=1e-9, atol=1e-12)
    # Shrinkage pulls off-diagonal covariances toward zero.
    off = ~np.eye(len(_SYMBOLS), dtype=bool)
    assert np.all(np.abs(shrunk[off]) < np.abs(sample[off]))


def test_sample_cov_is_plain_sample_covariance() -> None:
    result = _run(prior_covariance="sample_cov")
    assert result.data["prior_covariance_estimator"] == "sample_cov"
    assert result.data["shrinkage_intensity"] is None
    assert np.allclose(_matrix(result.data["prior_covariance"]),
                       _matrix(result.data["prior_covariance"]).T)


def test_exp_cov_is_applied() -> None:
    sample = _matrix(_run(prior_covariance="sample_cov").data["prior_covariance"])
    result = _run(prior_covariance="exp_cov")
    assert result.data["prior_covariance_estimator"] == "exp_cov"
    ewma = _matrix(result.data["prior_covariance"])
    assert np.allclose(ewma, ewma.T)
    assert not np.allclose(ewma, sample)
    assert np.all(np.linalg.eigvalsh(ewma) > 0)


def test_unknown_estimator_is_refused_not_ignored() -> None:
    result = _run(prior_covariance="bogus_shrinkage")
    assert result.data["status"] == "input_error"
    assert "prior_covariance" not in result.data
    assert any("bogus_shrinkage" in w for w in result.warnings)
