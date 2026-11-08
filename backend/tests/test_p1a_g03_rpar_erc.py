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


class _HistoryProvider:
    """Test provider: a seeded price path per symbol (no network, no fallback).

    RPAR no longer builds weights from synthetic returns when the provider is
    missing (RPAR#4), so the ERC path is exercised through a provider that
    returns history, as in production.
    """

    async def fetch(self, request, *_a, **_kw):
        import numpy as np
        import pandas as pd

        sym = request.instrument.symbol
        rng = np.random.default_rng(sum(map(ord, sym)))
        vol = {"AAPL": 0.020, "MSFT": 0.017, "GLD": 0.009, "TLT": 0.011}.get(sym, 0.015)
        rets = rng.normal(0.0003, vol, 300)
        idx = pd.bdate_range(end="2026-10-30", periods=300)
        return pd.DataFrame({"close": 100.0 * np.exp(np.cumsum(rets))}, index=idx)


def _deps():
    from showme.engine.core.base_function import FunctionDeps

    return FunctionDeps(yfinance=_HistoryProvider())


def test_rpar_function_erc_output_has_equal_risk_shares() -> None:
    fn = RPARFunction(deps=_deps())
    out = asyncio.run(fn.execute(symbols="AAPL,MSFT,GLD,TLT", method="erc", live_risk=True))
    shares = [row["risk_contribution_pct"] for row in out.data["rows"]]
    assert out.data["info"]["converged"] is True
    assert shares == pytest.approx([25.0] * 4, abs=1e-3)


def test_rpar_function_warns_when_erc_does_not_converge() -> None:
    fn = RPARFunction(deps=_deps())
    out = asyncio.run(fn.execute(symbols="AAPL,MSFT,GLD,TLT", method="erc", max_iter=1, live_risk=True))
    assert out.data["info"]["converged"] is False
    assert any("did not converge" in w for w in out.warnings)
