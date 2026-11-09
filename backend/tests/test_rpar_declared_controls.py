"""RPAR declared controls are honoured (RPAR#4).

The manifest declares covariance_model (default ledoit_wolf) and risk_target
(default 0.10, weights scaled so portfolio vol hits it), and its methodology
describes a log-barrier/Newton solver. Pre-fix, the handler always used the
sample covariance, never scaled to risk_target, and the solver it described
does not exist. These tests pin the real behaviour.

No network: the market-data adapter is a deterministic fake keyed by symbol.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio import rpar as rpar_mod
from showme.engine.functions.portfolio.rpar import RPARFunction
from showme.manifest import REGISTRY, load_seeds


class _FakeYfinance:
    """Deterministic daily closes per symbol; no network."""

    async def fetch(self, request: Any, *_args: Any, **_kwargs: Any) -> pd.DataFrame:
        symbol = request.instrument.symbol
        seed = sum(ord(ch) for ch in symbol)
        rng = np.random.default_rng(seed)
        n = 320
        vol = 0.008 + (seed % 7) * 0.003
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, vol, n)))
        idx = pd.bdate_range(end="2026-10-30", periods=n)
        return pd.DataFrame({"close": close}, index=idx)


def _run(**params: Any):
    deps = FunctionDeps(yfinance=_FakeYfinance())
    return asyncio.run(RPARFunction(deps).execute(symbols="AAA,BBB,CCC", **params))


def test_risk_target_is_honoured_for_erc() -> None:
    """Pre-fix: portfolio_vol was whatever the weights implied (about 0.08-0.11), never the target."""
    out = _run(method="erc", risk_target=0.10, covariance_model="ledoit_wolf")
    assert out.data["portfolio_vol"] == pytest.approx(0.10, abs=1e-6)
    assert out.data["risk_target"] == pytest.approx(0.10)
    assert out.metadata["fallback"] is False


def test_risk_target_is_honoured_for_inverse_vol() -> None:
    out = _run(risk_target=0.07)
    assert out.data["portfolio_vol"] == pytest.approx(0.07, abs=1e-6)


def test_scaled_weights_sum_to_reported_gross_exposure() -> None:
    """Scaling to a vol target means weights sum to gross exposure, not to 1."""
    out = _run(method="erc", risk_target=0.10)
    weights = out.data["weights"]
    assert out.data["gross_exposure"] == pytest.approx(sum(weights.values()), rel=1e-9)
    assert out.data["gross_exposure"] != pytest.approx(1.0, abs=1e-3)


def test_covariance_model_is_reported_and_applied() -> None:
    out = _run(method="erc", covariance_model="ledoit_wolf")
    assert out.data["covariance_model"] == "ledoit_wolf"


def test_unknown_covariance_model_is_reported_not_silent() -> None:
    out = _run(method="erc", covariance_model="magic_cov")
    assert out.data["covariance_model"] == "sample_cov"
    assert any("magic_cov" in w for w in out.warnings), out.warnings


def test_shrinkage_estimators_differ_from_sample_and_shrink_off_diagonals() -> None:
    """Pre-fix: no covariance_model branch existed, so every estimator equalled df.cov()."""
    returns = pd.DataFrame(_returns_frame().T, columns=["AAA", "BBB", "CCC"])
    sample, _, _ = rpar_mod.estimate_covariance(returns, "sample_cov")
    off = lambda m: np.abs(m - np.diag(np.diag(m))).sum()  # noqa: E731

    for model in ("ledoit_wolf", "oracle_approximating"):
        cov, effective, _ = rpar_mod.estimate_covariance(returns, model)
        assert effective == model
        assert not np.allclose(cov, sample)
        assert off(cov) <= off(sample) + 1e-12
        assert np.linalg.eigvalsh(cov).min() > -1e-12

    ewm, effective, _ = rpar_mod.estimate_covariance(returns, "exp_cov")
    assert effective == "exp_cov"
    assert not np.allclose(ewm, sample)


def test_seed_methodology_describes_the_real_solver() -> None:
    """Pre-fix: the manifest claimed a log-barrier/Newton solver the code does not run."""
    load_seeds()
    text = REGISTRY.get("RPAR").methodology.lower()
    assert "log-barrier" not in text
    assert "newton" not in text
    assert "damped" in text
    assert "risk_target" in text or "risk target" in text


def _returns_frame() -> np.ndarray:
    rng = np.random.default_rng(42)
    base = rng.normal(0.0003, 0.01, (3, 300))
    base[1] = 0.6 * base[0] + 0.8 * base[1]  # correlated pair keeps shrinkage non-trivial
    return base
