"""PORT_OPT regressions: risk parity must equalise risk contributions, and the
risk-free rate must be applied consistently to every mode's Sharpe.

Both defects are reproduced through ``PortOptFunction.execute`` with the
yfinance adapter replaced by an offline fake (no network).

* PORT_OPT#1 - ``risk_parity`` ran a fixed-step projected update for 1000
  iterations with no convergence check, so the returned weights did not
  equalise risk contributions (one asset got ~6% of risk against a 14.3% target).
* PORT_OPT#2 - ``min_volatility`` and ``risk_parity`` computed Sharpe with
  ``rf=0.0`` while ``max_sharpe`` used the user rate, so the three Sharpe
  figures shown side by side were not comparable.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.port_opt import PortOptFunction


SYMBOLS = ["SPY", "QQQ", "IWM", "TLT", "GLD", "EFA", "EEM"]


class _FakeYFinance:
    """Offline stand-in for the yfinance adapter: returns deterministic closes."""

    def __init__(self, daily_vols: dict[str, float], n_days: int = 500, seed: int = 7) -> None:
        rng = np.random.default_rng(seed)
        # Correlated factor + idiosyncratic noise, with heterogeneous vols so
        # that equal-risk-contribution weights differ materially from 1/n.
        factor = rng.normal(0.0, 1.0, n_days)
        self._closes: dict[str, pd.Series] = {}
        end = datetime(2026, 10, 30, tzinfo=timezone.utc)
        dates = [end - timedelta(days=n_days - 1 - i) for i in range(n_days)]
        for i, (sym, vol) in enumerate(daily_vols.items()):
            idio = rng.normal(0.0, 1.0, n_days)
            rets = 0.0002 + vol * (0.6 * factor + 0.8 * idio) / np.sqrt(1.0)
            closes = 100.0 * np.exp(np.cumsum(rets))
            self._closes[sym] = pd.Series(closes, index=pd.DatetimeIndex(dates))

    async def fetch(self, request):  # noqa: ANN001 - adapter protocol
        sym = request.instrument.symbol
        close = self._closes[sym]
        return pd.DataFrame({"close": close.to_numpy()}, index=close.index)


_VOLS = {
    "SPY": 0.010,
    "QQQ": 0.014,
    "IWM": 0.016,
    "TLT": 0.006,
    "GLD": 0.009,
    "EFA": 0.011,
    "EEM": 0.018,
}


def _run_port_opt(mode: str, risk_free: float) -> dict:
    fn = PortOptFunction(deps=FunctionDeps(yfinance=_FakeYFinance(_VOLS)))
    result = asyncio.run(
        fn.execute(symbols=SYMBOLS, mode=mode, live=True, days=756, risk_free=risk_free)
    )
    assert result.metadata["live"] is True, "fixture must exercise the live return path"
    return result.data


def _returns_frame() -> pd.DataFrame:
    fake = _FakeYFinance(_VOLS)
    cols = {}
    for sym in SYMBOLS:
        close = fake._closes[sym]
        cols[sym] = close.pct_change().dropna()
    return pd.DataFrame(cols).dropna()


def test_risk_parity_equalises_risk_contributions_through_execute() -> None:
    """PORT_OPT risk_parity weights must give equal risk contribution (ERC)."""
    data = _run_port_opt(mode="risk_parity", risk_free=0.04)
    weights = data["risk_parity"]["weights"]
    w = np.array([weights[s] for s in SYMBOLS])

    rets = _returns_frame()
    cov = rets.cov().values * 252
    port_var = float(w @ cov @ w)
    rc_share = w * (cov @ w) / port_var  # fraction of total variance per asset
    target = 1.0 / len(SYMBOLS)
    max_dev = float(np.max(np.abs(rc_share - target)) / target)
    assert max_dev < 0.01, (
        f"risk parity not equal-risk: max relative RC deviation {max_dev:.4f}; "
        f"weights={dict(zip(SYMBOLS, np.round(w, 4)))} rc_share={np.round(rc_share, 4)}"
    )
    assert abs(w.sum() - 1.0) < 1e-9
    assert np.all(w > 0)


def test_risk_parity_reports_convergence_status() -> None:
    """The solver must expose whether it converged instead of silently stopping."""
    data = _run_port_opt(mode="risk_parity", risk_free=0.04)
    rp = data["risk_parity"]
    assert rp.get("converged") is True
    assert float(rp.get("max_risk_contribution_error", 1.0)) < 1e-6


def test_min_volatility_sharpe_uses_user_risk_free_rate() -> None:
    """min_volatility Sharpe must deduct the same risk-free rate as max_sharpe."""
    rf = 0.04
    data = _run_port_opt(mode="all", risk_free=rf)
    mv = data["min_volatility"]
    expected = (float(mv["return"]) - rf) / float(mv["vol"])
    assert abs(float(mv["sharpe"]) - expected) < 1e-9, (
        f"min_vol sharpe {mv['sharpe']:.6f} != (ret-rf)/vol {expected:.6f}"
    )


def test_risk_parity_sharpe_uses_user_risk_free_rate() -> None:
    rf = 0.04
    data = _run_port_opt(mode="all", risk_free=rf)
    rp = data["risk_parity"]
    expected = (float(rp["return"]) - rf) / float(rp["vol"])
    assert abs(float(rp["sharpe"]) - expected) < 1e-9, (
        f"risk_parity sharpe {rp['sharpe']:.6f} != (ret-rf)/vol {expected:.6f}"
    )


def test_all_modes_sharpe_share_one_risk_free_definition() -> None:
    """With the same rf, every mode's Sharpe must be (return - rf) / vol."""
    rf = 0.04
    data = _run_port_opt(mode="all", risk_free=rf)
    for key in ("max_sharpe", "min_volatility", "risk_parity"):
        block = data[key]
        expected = (float(block["return"]) - rf) / float(block["vol"])
        assert abs(float(block["sharpe"]) - expected) < 1e-9, key


class _RaisingYFinance:
    """Offline stand-in for an unavailable yfinance adapter (every fetch fails)."""

    async def fetch(self, request):  # noqa: ANN001 - adapter protocol
        raise RuntimeError("yfinance offline (test)")


def test_live_request_that_falls_back_to_model_returns_says_so() -> None:
    """When live returns are requested but unavailable, the result must say the
    weights come from labelled model returns, not market data."""
    fn = PortOptFunction(deps=FunctionDeps(yfinance=_RaisingYFinance()))
    result = asyncio.run(
        fn.execute(symbols=SYMBOLS, mode="risk_parity", live=True, days=756, risk_free=0.04)
    )
    assert result.metadata["fallback"] is True
    assert result.sources == ["computed_return_model"]
    assert any("not market data" in w for w in result.warnings), result.warnings


def test_zero_variance_asset_reports_warning_and_no_risk_parity_weights() -> None:
    """A flat price series has no defined risk contribution: no equal-risk weights
    may be invented; the result must carry a warning instead."""
    fake = _FakeYFinance(_VOLS)
    fake._closes["TLT"] = pd.Series(100.0, index=fake._closes["TLT"].index)
    fn = PortOptFunction(deps=FunctionDeps(yfinance=fake))
    result = asyncio.run(
        fn.execute(symbols=SYMBOLS, mode="risk_parity", live=True, days=756, risk_free=0.04)
    )
    assert "risk_parity" not in result.data
    assert any(w.startswith("risk_parity unavailable") for w in result.warnings), result.warnings
