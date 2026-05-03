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
from typing import Any

import numpy as np
import pandas as pd

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.portfolio.state import PortfolioState


@FunctionRegistry.register
class PVARFunction(BaseFunction):
    code = "PVAR"
    name = "Position-level VaR / MCR"
    category = "portfolio"
    description = "Per-symbol marginal contribution to portfolio risk + parametric VaR decomposition."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        days = int(params.get("days", 252))
        confidence = float(params.get("confidence", 0.95))
        max_positions = max(1, int(params.get("max_positions", 12)))
        provider_timeout = float(params.get("yfinance_timeout", params.get("quote_timeout", 4)))
        live = _truthy(params.get("live_risk"))
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
        from src.functions.portfolio.rpar import _template_returns

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
            rets_df = pd.DataFrame({s: r for s, r, _ in rs if not r.empty}).dropna(how="any")
            last_map = {s: px for s, _, px in rs if px is not None}
            if rets_df.empty:
                return _empty_pvar(self.code, confidence, params, instrument, "no live return history")
        else:
            rets_df = _template_returns([p.instrument.symbol for p in eligible], days)
        # Build current weights from positions × last close
        notional_map = {}
        for p in eligible:
            px = last_map.get(p.instrument.symbol) or p.avg_cost
            notional_map[p.instrument.symbol] = p.quantity * px
        total = sum(abs(notional_map.get(s, 0.0)) for s in rets_df.columns) or 1.0
        weights = {s: notional_map.get(s, 0.0) / total for s in rets_df.columns}
        w_vec = np.array([weights[s] for s in rets_df.columns])
        cov = np.atleast_2d(rets_df.cov().values * 252)
        port_var = float(w_vec @ cov @ w_vec)
        port_vol = float(np.sqrt(max(port_var, 1e-12)))
        # Parametric daily VaR (negative number)
        from math import erf, sqrt
        # Inverse normal at confidence (95% → 1.645)
        z = 1.645 if abs(confidence - 0.95) < 1e-3 else 2.326 if abs(confidence - 0.99) < 1e-3 else 1.96
        # Daily-equivalent parametric VaR
        var_pct = -z * port_vol / np.sqrt(252)
        cov_w = cov @ w_vec
        rows = []
        for i, sym in enumerate(rets_df.columns):
            mcr = float(cov_w[i] / port_vol) if port_vol else 0
            comp_pct = float((w_vec[i] * mcr) / port_vol) if port_vol else 0
            rows.append({
                "symbol": sym,
                "weight_pct": float(w_vec[i] * 100),
                "annualized_vol": float(np.sqrt(cov[i, i])),
                "marginal_contribution_to_risk": mcr,
                "component_pct_of_portfolio_risk": comp_pct * 100,
                "notional_usd": notional_map.get(sym, 0.0),
            })
        rows.sort(key=lambda x: -x["component_pct_of_portfolio_risk"])
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "portfolio_total_notional": total,
                "portfolio_annualized_vol": port_vol,
                "portfolio_daily_var_pct": var_pct,
                "portfolio_daily_var_dollar": var_pct * total,
                "confidence": confidence,
                "samples": int(len(rets_df)),
                "positions_analyzed": int(len(rets_df.columns)),
                "max_positions": max_positions,
                "rows": rows,
            },
            sources=["yfinance"] if live else ["portfolio_state", "risk_model"],
            metadata={"live_risk": live, "positions_analyzed": int(len(rets_df.columns))},
        )


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
        return close.pct_change().dropna(), float(close.iloc[-1])
    except Exception:
        return pd.Series(dtype=float), None


def _yf_symbol(symbol: str) -> str:
    sym = str(symbol or "").upper().strip()
    if sym.endswith("USDT") and len(sym) > 4:
        return f"{sym[:-4]}-USD"
    return sym


def _sample_pvar(
    code: str,
    confidence: float,
    params: dict[str, Any],
    instrument: Instrument | None = None,
) -> FunctionResult:
    symbol = instrument.symbol if instrument else params.get("symbol", "BTCUSDT")
    asset_class = instrument.asset_class.value if instrument else params.get("asset_class", "CRYPTO")
    return FunctionResult(
        code=code,
        instrument=instrument,
        data={
            "portfolio_total_notional": 100000.0,
            "portfolio_annualized_vol": 0.22,
            "portfolio_daily_var_pct": -0.025,
            "portfolio_daily_var_dollar": -2500.0,
            "portfolio_vol": 0.22,
            "var": -0.025,
            "component_var": [
                {"symbol": symbol, "weight": 0.6, "component": -0.016, "asset_class": asset_class},
                {"symbol": "AAPL", "weight": 0.4, "component": -0.009, "asset_class": "EQUITY"},
            ],
            "rows": [
                {
                    "symbol": symbol,
                    "weight_pct": 60.0,
                    "annualized_vol": 0.28,
                    "marginal_contribution_to_risk": 0.16,
                    "component_pct_of_portfolio_risk": 64.0,
                    "notional_usd": 60000.0,
                    "asset_class": asset_class,
                },
                {
                    "symbol": "AAPL",
                    "weight_pct": 40.0,
                    "annualized_vol": 0.19,
                    "marginal_contribution_to_risk": 0.09,
                    "component_pct_of_portfolio_risk": 36.0,
                    "notional_usd": 40000.0,
                    "asset_class": "EQUITY",
                },
            ],
            "confidence": confidence,
            "samples": 252,
        },
        sources=["portfolio_state"],
        metadata={"live": False},
    )


def _empty_pvar(
    code: str,
    confidence: float,
    params: dict[str, Any],
    instrument: Instrument | None = None,
    reason: str = "empty portfolio",
) -> FunctionResult:
    return FunctionResult(
        code=code,
        instrument=instrument,
        data={
            "status": "ready_no_positions" if "portfolio" in reason else "provider_unavailable",
            "reason": reason,
            "portfolio_total_notional": 0.0,
            "portfolio_annualized_vol": None,
            "portfolio_daily_var_pct": None,
            "portfolio_daily_var_dollar": None,
            "confidence": confidence,
            "rows": [],
            "next_actions": [
                "Add real positions through portfolio state.",
                "Set live=true so the function can fetch return history.",
            ],
        },
        sources=["portfolio_state"],
        metadata={"empty": True, "requires_positions": True, "live": _truthy(params.get("live"))},
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
