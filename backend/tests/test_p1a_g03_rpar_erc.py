"""P1a-g03 RPAR#1 — the ERC solver must equalize risk contributions.

The old loop stopped when the residual *change* fell below tol (not when the
residual was small) and its update had no w_i term, so it returned weights
whose risk contributions simply equal the weights. The fixed solver uses the
cyclical update w_i <- b_i * sigma_p / (Sigma w)_i, stops on the residual
itself, and reports converged=False instead of a success-like result.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from showme.engine.functions.portfolio.rpar import RPARFunction
from showme.engine.services.risk_parity import equal_risk_contribution, risk_contributions


def _cov() -> np.ndarray:
    sigmas = np.array([0.20, 0.10, 0.30, 0.15])
    corr = np.array([
        [1.00, 0.30, 0.20, 0.10],
        [0.30, 1.00, 0.25, 0.05],
        [0.20, 0.25, 1.00, 0.15],
        [0.10, 0.05, 0.15, 1.00],
    ])
    return np.outer(sigmas, sigmas) * corr


def test_erc_equalizes_risk_contributions() -> None:
    cov = _cov()
    w, info = equal_risk_contribution(cov)
    shares = np.array(risk_contributions(w, cov)["risk_contributions_pct"])
    # RED before fix: shares equal the weights (not 0.25 each).
    assert shares == pytest.approx(np.full(4, 0.25), abs=1e-6)
    assert w.sum() == pytest.approx(1.0)
    assert np.all(w > 0)


def test_erc_reports_convergence_on_success() -> None:
    _, info = equal_risk_contribution(_cov())
    assert info["converged"] is True
    assert info["residual"] < 1e-6


def test_erc_reports_non_convergence_instead_of_success() -> None:
    cov = _cov()
    _, info = equal_risk_contribution(cov, max_iter=1)
    assert info["converged"] is False
    assert info["residual"] > 1e-6


def test_erc_respects_custom_target() -> None:
    cov = _cov()
    target = np.array([0.4, 0.3, 0.2, 0.1])
    w, info = equal_risk_contribution(cov, target=target)
    shares = np.array(risk_contributions(w, cov)["risk_contributions_pct"])
    assert shares == pytest.approx(target, abs=1e-6)
    assert info["converged"] is True


class _NoDeps:
    yfinance = None
    fred = None

    def __getattr__(self, item):  # pragma: no cover
        return None


def test_rpar_function_erc_output_has_equal_risk_shares() -> None:
    fn = RPARFunction(deps=_NoDeps())
    out = asyncio.run(fn.execute(symbols="AAPL,MSFT,GLD,TLT", method="erc"))
    shares = [row["risk_contribution_pct"] for row in out.data["rows"]]
    assert out.data["info"]["converged"] is True
    assert shares == pytest.approx([25.0] * 4, abs=1e-3)


def test_rpar_function_warns_when_erc_does_not_converge() -> None:
    fn = RPARFunction(deps=_NoDeps())
    out = asyncio.run(fn.execute(symbols="AAPL,MSFT,GLD,TLT", method="erc", max_iter=1))
    assert out.data["info"]["converged"] is False
    assert any("did not converge" in w for w in out.warnings)
