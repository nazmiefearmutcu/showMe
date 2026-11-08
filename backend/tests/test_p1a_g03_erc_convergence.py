"""P1a-g03 RPAR#1 follow-up — the ERC solver must converge on ordinary universes.

The cyclical Jacobi-style update in equal_risk_contribution does not converge
on random covariance matrices, even with 4 assets, so RPAR reported
converged=False for most ordinary universes. These tests use seeded random
covariances (no network) and require convergence to equal risk shares.
"""

from __future__ import annotations

import numpy as np
import pytest

from showme.engine.services.risk_parity import equal_risk_contribution, risk_contributions


def _random_cov(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    scale = rng.uniform(0.005, 0.04, n)
    returns = rng.normal(size=(504, n)) * scale + rng.normal(0.0, 0.003, (504, 1))
    return np.cov(returns, rowvar=False) * 252


@pytest.mark.parametrize("n", [4, 10, 20, 50])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_erc_converges_on_random_universes(n: int, seed: int) -> None:
    cov = _random_cov(n, seed)
    w, info = equal_risk_contribution(cov, max_iter=500)
    # RED before fix: converged is False and residual is 0.03 to 0.8 for most cases.
    assert info["converged"] is True, info
    shares = np.asarray(risk_contributions(w, cov)["risk_contributions_pct"])
    assert np.max(np.abs(shares - 1.0 / n)) < 1e-6
    assert np.all(w > 0)
    assert abs(w.sum() - 1.0) < 1e-12
