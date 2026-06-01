"""PVAR — Position-level VaR + marginal contribution to risk (MCR).

Per-symbol, marginal contribution to portfolio VaR (and risk):
    σ_p = sqrt(w' Σ w)
    MCR_i = (Σw)_i / σ_p
    component_var_i = w_i × MCR_i × VaR_multiplier
    pct_contribution_i = (w_i × MCR_i) / σ_p

Output: ranked positions by absolute risk contribution.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

import numpy as np
import pandas as pd


def _norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (Acklam 2003 rational approximation).

    Used so PVAR can take an arbitrary `confidence` in (0,1) without
    needing scipy. Audit Q3 #11 — the legacy hardcoded `1.96 / 1.645 /
    2.326` returned the wrong z for any confidence not in {0.95, 0.99}.
    Max relative error of this approximation is ~1.15e-9 across [1e-15, 1-1e-15].
    """
    try:
        from scipy.stats import norm  # type: ignore
        return float(norm.ppf(p))
    except Exception:
        pass
    if not (0.0 < p < 1.0):
        if p <= 0.0:
            return float("-inf")
        return float("inf")
    a = (-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2,
         1.383577518672690e2, -3.066479806614716e1, 2.506628277459239e0)
    b = (-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2,
         6.680131188771972e1, -1.328068155288572e1)
    c = (-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838e0,
         -2.549732539343734e0, 4.374664141464968e0, 2.938163982698783e0)
    d = (7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996e0,
         3.754408661907416e0)
    plow = 0.02425
    phigh = 1.0 - plow
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (
            (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5])
            / ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)
        )
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q
            / (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1.0)
        )
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(
        (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5])
        / ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)
    )

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions.portfolio.return_series import align_return_series, close_to_daily_returns
from showme.engine.portfolio.state import PortfolioState


@FunctionRegistry.register
class PVARFunction(BaseFunction):
    code = "PVAR"
    name = "Position-level VaR / MCR"
    category = "portfolio"
    description = "Per-symbol marginal contribution to portfolio risk + parametric VaR decomposition."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        days = int(params.get("days", params.get("lookback_days", 252)))
        confidence = float(params.get("confidence", params.get("confidence_level", 0.95)))
        if not (0.0 < confidence < 1.0):
            confidence = 0.95
        horizon_days = _horizon_days(params.get("horizon", "1d"))
        method = str(params.get("method", "parametric")).strip().lower()
        if method not in {"parametric", "historical"}:
            # monte_carlo is not implemented keyless-ly; fall back to the
            # most honest empirical estimator we can actually compute.
            method = "historical"
        max_positions = max(1, int(params.get("max_positions", 12)))
        provider_timeout = float(params.get("yfinance_timeout", params.get("quote_timeout", 4)))
        # Live, real-data is now the DEFAULT path. `live_risk=false` only
        # exists as an explicit offline escape hatch (template returns).
        live = _truthy(params.get("live_risk", True))
        portfolio = PortfolioState()
        portfolio.import_legacy_crypto()
        if not portfolio.positions:
            return _empty_pvar(self.code, confidence, params, instrument, "empty portfolio")
        # Resolve symbols (skip macro / unsupported)
        eligible = [p for p in portfolio.positions
                     if p.instrument.asset_class.value not in ("MACRO", "BOND")]
        if not eligible:
            return _empty_pvar(self.code, confidence, params, instrument, "no eligible portfolio positions")
        eligible = sorted(
            eligible,
            key=lambda p: abs(float(p.quantity or 0) * float(p.avg_cost or 0)),
            reverse=True,
        )[:max_positions]

        warnings: list[str] = []
        last_map = {}
        if live:
            async def _ret(p):
                try:
                    series, last = await asyncio.wait_for(
                        asyncio.to_thread(
                            _download_returns,
                            p.instrument.symbol,
                            days,
                            provider_timeout,
                        ),
                        timeout=provider_timeout + 0.5,
                    )
                    return p.instrument.symbol, series, last
                except Exception:
                    return p.instrument.symbol, pd.Series(dtype=float), None
            rs = await asyncio.gather(*(_ret(p) for p in eligible))
            # Audit Q3 #7: pairwise covariance for mixed universes.
            rets_df = align_return_series(
                ((s, r) for s, r, _ in rs), policy="pairwise"
            )
            last_map = {s: px for s, _, px in rs if px is not None}
            if rets_df.empty:
                # Genuine network/data outage — never fabricate numbers.
                return _empty_pvar(
                    self.code, confidence, params, instrument,
                    "no live return history (yfinance returned no data)",
                )
        else:
            from showme.engine.functions.portfolio.rpar import _template_returns
            rets_df = _template_returns([p.instrument.symbol for p in eligible], days)
            warnings.append("live_risk=false: returns are simulated, not market data.")
        # Build current weights from positions × last close
        notional_map = {}
        for p in eligible:
            px = last_map.get(p.instrument.symbol) or p.avg_cost
            notional_map[p.instrument.symbol] = p.quantity * px
        total = sum(abs(notional_map.get(s, 0.0)) for s in rets_df.columns) or 1.0
        weights = {s: notional_map.get(s, 0.0) / total for s in rets_df.columns}
        w_vec = np.array([weights[s] for s in rets_df.columns])
        # Audit Q3 #12 — operate on daily covariance directly. Annualizing
        # then de-annualizing for VaR is a wash that obscures the formula.
        cov_daily = np.atleast_2d(rets_df.cov().values)
        # Replace NaN cov entries (pairwise overlap edge cases) with 0 so
        # the quadratic form stays finite.
        if not np.isfinite(cov_daily).all():
            cov_daily = np.nan_to_num(cov_daily, nan=0.0, posinf=0.0, neginf=0.0)
        cov = cov_daily * 252  # kept for annualized rows below
        mu_daily = np.nan_to_num(rets_df.mean().values, nan=0.0)
        port_var_daily = float(w_vec @ cov_daily @ w_vec)
        port_vol_daily = float(np.sqrt(max(port_var_daily, 1e-12)))
        port_vol = port_vol_daily * float(np.sqrt(252))  # annualized for display
        port_mu_daily = float(w_vec @ mu_daily)
        sqrt_h = float(np.sqrt(max(horizon_days, 1)))
        # Audit Q3 #11 — proper inverse-normal at the requested confidence.
        z = float(_norm_ppf(confidence))

        # --- Parametric (variance-covariance) VaR & ES over the horizon ---
        # VaR as a positive loss return at the horizon: -μ Δt + z σ √Δt.
        param_var_pct = float(-port_mu_daily * horizon_days + z * port_vol_daily * sqrt_h)
        # Gaussian ES = μ - σ φ(z)/(1-α); express as positive loss.
        phi_z = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
        param_es_pct = float(
            -port_mu_daily * horizon_days
            + (phi_z / (1.0 - confidence)) * port_vol_daily * sqrt_h
        )

        # --- Historical-simulation VaR & ES (empirical tail of the P&L) ---
        port_returns = (rets_df.fillna(0.0).values @ w_vec)
        if horizon_days > 1 and len(port_returns) > horizon_days:
            # Non-overlapping multi-day P&L blocks for the requested horizon.
            n_blocks = len(port_returns) // horizon_days
            trimmed = port_returns[: n_blocks * horizon_days]
            port_returns_h = trimmed.reshape(n_blocks, horizon_days).sum(axis=1)
        elif horizon_days > 1:
            port_returns_h = port_returns * horizon_days  # too few rows to block
        else:
            port_returns_h = port_returns
        if len(port_returns_h):
            losses = -port_returns_h
            hist_var_pct = float(np.quantile(losses, confidence))
            tail = losses[losses >= hist_var_pct]
            hist_es_pct = float(tail.mean()) if tail.size else hist_var_pct
        else:
            hist_var_pct = param_var_pct
            hist_es_pct = param_es_pct

        # Selected method drives the headline VaR/ES; both are always reported.
        if method == "historical":
            var_pct = hist_var_pct
            es_pct = hist_es_pct
        else:
            var_pct = param_var_pct
            es_pct = param_es_pct
        # ES must dominate VaR (Euler / coherence); guard numeric edge cases.
        es_pct = max(es_pct, var_pct)

        var_dollar = var_pct * total
        es_dollar = es_pct * total

        # --- Component VaR decomposition (sums to total VaR by Euler) ---
        cov_w = cov_daily @ w_vec
        rows = []
        for i, sym in enumerate(rets_df.columns):
            # Marginal contribution to daily portfolio vol.
            mcr_daily = float(cov_w[i] / port_vol_daily) if port_vol_daily else 0.0
            comp_pct_of_risk = float((w_vec[i] * mcr_daily) / port_vol_daily) if port_vol_daily else 0.0
            component_var_dollar = float(comp_pct_of_risk * var_dollar)
            # Marginal VaR per unit weight (horizon-scaled), incremental VaR.
            marginal_var_dollar = float(z * mcr_daily * sqrt_h * total)
            rows.append({
                "symbol": sym,
                "weight": float(w_vec[i] * 100),
                "weight_pct": float(w_vec[i] * 100),
                "annualized_vol": float(np.sqrt(cov[i, i])),
                "marginal_contribution_to_risk": mcr_daily,
                "component_pct_of_portfolio_risk": comp_pct_of_risk * 100,
                "component_var": component_var_dollar,
                "marginal_var": marginal_var_dollar,
                "incremental_var": component_var_dollar,
                "notional_usd": notional_map.get(sym, 0.0),
                "asset_class": _asset_class_for(eligible, sym),
            })
        rows.sort(key=lambda x: -x["component_pct_of_portfolio_risk"])

        # Loss-distribution histogram for the chart_grammar DISTRIBUTION pane.
        series = _loss_histogram(port_returns_h * total)

        as_of = _utcnow_iso()
        cards = {
            "var": var_dollar,
            "expected_shortfall": es_dollar,
            "confidence_level": confidence,
            "horizon": params.get("horizon", "1d"),
            "method": method,
            "data_mode": "delayed_reference" if live else "modeled",
            "as_of": as_of,
        }

        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "status": "ok" if live else "modeled",
                "as_of": as_of,
                "data_mode": "delayed_reference" if live else "modeled",
                "method": method,
                "horizon": params.get("horizon", "1d"),
                "confidence_level": confidence,
                "confidence": confidence,
                # Headline VaR/ES (positive number = loss) in portfolio ccy.
                "var": var_dollar,
                "expected_shortfall": es_dollar,
                "var_pct": var_pct,
                "expected_shortfall_pct": es_pct,
                "parametric_var_dollar": param_var_pct * total,
                "parametric_es_dollar": param_es_pct * total,
                "historical_var_dollar": hist_var_pct * total,
                "historical_es_dollar": hist_es_pct * total,
                "portfolio_total_notional": total,
                "portfolio_annualized_vol": port_vol,
                # Legacy fields kept so existing UI bindings keep working
                # (negative = loss convention here, matches prior contract).
                "portfolio_daily_var_pct": -param_var_pct,
                "portfolio_daily_var_dollar": -param_var_pct * total,
                "samples": int(len(rets_df)),
                "positions_analyzed": int(len(rets_df.columns)),
                "max_positions": max_positions,
                "rows": rows,
                "series": series,
                "cards": cards,
                "summary": {
                    "confidence": confidence,
                    "method": method,
                    "horizon": params.get("horizon", "1d"),
                    "positions_analyzed": int(len(rets_df.columns)),
                    "var": var_dollar,
                    "expected_shortfall": es_dollar,
                },
                "methodology": (
                    "Position-level VaR/ES from real daily returns. Parametric (variance-"
                    "covariance) path estimates daily covariance Σ from yfinance OHLCV, computes "
                    "portfolio volatility sqrt(w'Σw), and reports VaR = -μΔt + z_α σ √Δt with ES = "
                    "μΔt + σ √Δt φ(z)/(1-α). Historical-simulation path takes the empirical loss "
                    "quantile of the realised portfolio P&L (non-overlapping blocks for multi-day "
                    "horizons) and the conditional tail mean for ES. Component VaR decomposes the "
                    "total by marginal contribution × weight (Euler-consistent). Both methods are "
                    "always returned; `method` selects the headline figures."
                ),
                "field_dictionary": {
                    "var": "Loss at the requested confidence and horizon; positive = loss, portfolio ccy.",
                    "expected_shortfall": "Conditional expected loss beyond VaR (>= VaR).",
                    "var_pct": "VaR as a fraction of portfolio notional.",
                    "parametric_var_dollar": "Variance-covariance (Gaussian) VaR in ccy.",
                    "historical_var_dollar": "Historical-simulation empirical VaR in ccy.",
                    "component_var": "Per-symbol contribution to total VaR (sums to VaR).",
                    "marginal_var": "Sensitivity of VaR to the symbol's weight.",
                    "marginal_contribution_to_risk": "Derivative of portfolio volatility wrt symbol weight.",
                    "component_pct_of_portfolio_risk": "Symbol share of portfolio risk contribution.",
                    "notional_usd": "Position notional used for portfolio weights.",
                },
            },
            sources=["yfinance"] if live else ["portfolio_state", "risk_model"],
            warnings=warnings,
            metadata={
                "live_risk": live,
                "method": method,
                "horizon_days": horizon_days,
                "positions_analyzed": int(len(rets_df.columns)),
            },
        )


_HORIZON_MAP = {"1d": 1, "5d": 5, "10d": 10, "20d": 20}


def _horizon_days(value: Any) -> int:
    """Parse a manifest horizon control ('1d'/'5d'/'10d'/'20d') to trading days."""
    if isinstance(value, (int, float)):
        return max(1, int(value))
    key = str(value or "1d").strip().lower()
    if key in _HORIZON_MAP:
        return _HORIZON_MAP[key]
    digits = "".join(ch for ch in key if ch.isdigit())
    return max(1, int(digits)) if digits else 1


def _utcnow_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _asset_class_for(positions, symbol: str) -> str:
    for p in positions:
        if p.instrument.symbol == symbol:
            return p.instrument.asset_class.value
    return ""


def _loss_histogram(pnl_dollars, bins: int = 21) -> list[dict[str, float]]:
    """Build a simple P&L distribution series for the DISTRIBUTION chart pane."""
    arr = np.asarray(pnl_dollars, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return []
    counts, edges = np.histogram(arr, bins=min(bins, max(5, arr.size)))
    centers = (edges[:-1] + edges[1:]) / 2.0
    return [
        {"pnl": float(c), "density": float(n)}
        for c, n in zip(centers, counts)
    ]


def _download_returns(symbol: str, days: int, timeout: float) -> tuple[pd.Series, float | None]:
    try:
        import yfinance as yf

        yf_symbol = _yf_symbol(symbol)
        df = yf.download(
            yf_symbol,
            period=f"{max(days, 5)}d",
            interval="1d",
            progress=False,
            threads=False,
            timeout=timeout,
            auto_adjust=True,
        )
        if df is None or df.empty:
            return pd.Series(dtype=float), None
        close = df["Close"] if "Close" in df else df.get("close")
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = pd.to_numeric(close, errors="coerce").dropna()
        if close.empty:
            return pd.Series(dtype=float), None
        returns = close_to_daily_returns(pd.DataFrame({"close": close}))
        return returns, float(close.iloc[-1])
    except Exception:
        return pd.Series(dtype=float), None


def _yf_symbol(symbol: str) -> str:
    sym = str(symbol or "").upper().strip()
    if sym.endswith("USDT") and len(sym) > 4:
        return f"{sym[:-4]}-USD"
    return sym


def _empty_pvar(
    code: str,
    confidence: float,
    params: dict[str, Any],
    instrument: Instrument | None = None,
    reason: str = "empty portfolio",
) -> FunctionResult:
    no_positions = "portfolio" in reason or "positions" in reason
    status = "empty" if no_positions else "provider_unavailable"
    return FunctionResult(
        code=code,
        instrument=instrument,
        data={
            "status": status,
            "reason": reason,
            "as_of": _utcnow_iso(),
            "data_mode": "unavailable",
            "method": str(params.get("method", "parametric")),
            "horizon": params.get("horizon", "1d"),
            "confidence_level": confidence,
            "confidence": confidence,
            "var": None,
            "expected_shortfall": None,
            "portfolio_total_notional": 0.0,
            "portfolio_annualized_vol": None,
            "portfolio_daily_var_pct": None,
            "portfolio_daily_var_dollar": None,
            "rows": [],
            "series": [],
            "cards": {},
            "next_actions": (
                ["Add real positions through portfolio state."]
                if no_positions
                else [
                    "Retry once the price provider (yfinance) is reachable.",
                    "Confirm the portfolio symbols resolve on yfinance.",
                ]
            ),
            "methodology": (
                "VaR/ES requires positions and a real return covariance matrix from yfinance. No "
                "decomposition is shown until portfolio positions and return history are available."
            ),
            "field_dictionary": {
                "var": "Loss at the requested confidence; positive number = loss.",
                "expected_shortfall": "Conditional expected loss beyond VaR.",
            },
        },
        sources=["portfolio_state"] if no_positions else ["yfinance"],
        warnings=[reason],
        metadata={
            "empty": no_positions,
            "requires_positions": no_positions,
            "live": _truthy(params.get("live_risk", True)),
        },
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
