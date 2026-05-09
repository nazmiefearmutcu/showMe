"""PCAS — PCA-based portfolio stress test."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions.portfolio.return_series import align_return_series, close_to_daily_returns
from showme.engine.portfolio.state import PortfolioState
from showme.engine.services import pca_stress


@FunctionRegistry.register
class PCASFunction(BaseFunction):
    code = "PCAS"
    name = "PCA Factor Stress"
    category = "portfolio"
    description = "Apply k-σ shock along principal components (correlated stress)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        days = int(params.get("days", 504))
        pc_index = int(params.get("pc_index", 0))
        k_sigma = float(params.get("k_sigma", 3.0))
        top_n = int(params.get("top_n", 8))
        live_portfolio = _truthy(
            params.get("live_portfolio") or params.get("live_prices") or params.get("live")
        )
        if not live_portfolio:
            return _empty_pcas(self.code, instrument, pc_index, k_sigma, "live=true required for PCA stress")
        portfolio = PortfolioState()
        if _truthy(params.get("include_legacy") or params.get("legacy")):
            portfolio.import_legacy_crypto()
        eligible = [p for p in portfolio.positions
                    if p.instrument.asset_class.value not in ("MACRO", "BOND")]
        if not eligible:
            return _empty_pcas(self.code, None, pc_index, k_sigma, "empty portfolio")
        from showme.engine.functions.portfolio.rpar import _template_returns
        symbols = [p.instrument.symbol for p in eligible]
        live_prices = bool(params.get("live_prices", False))
        if live_prices:
            timeout = float(params.get("timeout", 8))

            async def _ret(p) -> tuple[str, pd.Series, float]:
                try:
                    if not self.deps.yfinance:
                        raise RuntimeError("no yfinance")
                    df = await asyncio.wait_for(
                        self.deps.yfinance.fetch(DataRequest(
                            kind=DataKind.OHLCV, instrument=p.instrument,
                            start=datetime.utcnow() - timedelta(days=days),
                            interval="1d",
                        )),
                        timeout=timeout,
                    )
                    last = float(df["close"].iloc[-1])
                    return p.instrument.symbol, close_to_daily_returns(df), last
                except Exception:
                    return p.instrument.symbol, pd.Series(dtype=float), float(p.avg_cost or 100.0)

            results = await asyncio.gather(*(_ret(p) for p in eligible))
            last_map = {s: lp for s, _, lp in results}
            df = align_return_series((s, r) for s, r, _ in results)
            if df.shape[0] < 30:
                return _empty_pcas(self.code, None, pc_index, k_sigma, "no live return history")
        else:
            df = _template_returns(symbols, days)
            last_map = {p.instrument.symbol: float(p.avg_cost or 100.0) for p in eligible}
        # Build weights from positions
        notional = []
        for p in eligible:
            px = last_map.get(p.instrument.symbol) or p.avg_cost
            notional.append((p.instrument.symbol, p.quantity * px))
        total = sum(n for _, n in notional) or 1.0
        sym_to_w = {s: n / total for s, n in notional}
        cols = list(df.columns)
        weights = np.array([sym_to_w.get(s, 0.0) for s in cols])
        # PCA + factor shock
        try:
            decomp = pca_stress.pca_decompose(df.values)
            shock = pca_stress.apply_to_portfolio(
                weights, df.values, pc_index=pc_index, k_sigma=k_sigma)
        except Exception as e:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    **_empty_pcas(self.code, None, pc_index, k_sigma, f"pca: {e}").data,
                    "samples": int(df.shape[0]) if hasattr(df, "shape") else 0,
                },
                sources=["portfolio_state"],
                metadata={"provider_errors": [f"pca: {e}"]},
            )
        top = pca_stress.top_loadings(decomp["loadings"], cols, pc_index=pc_index,
                                      top_n=top_n)
        asset_returns = [
            {
                "symbol": s,
                "weight": float(weights[i]),
                "weight_pct": float(weights[i] * 100),
                "shock_return": float(shock["asset_returns"][i]),
                "shock_return_pct": float(shock["asset_returns"][i] * 100),
                "pnl": float(weights[i] * total * shock["asset_returns"][i]),
            }
            for i, s in enumerate(cols)
        ]
        loading_rows = [
            {
                "symbol": item.get("symbol"),
                "loading": float(item.get("loading") or 0.0),
                "pc_index": pc_index,
            }
            for item in top
        ]
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "pc_index": pc_index, "k_sigma": k_sigma,
                "explained_variance_ratio": decomp["explained_variance_ratio"][:5],
                "factor_shock_magnitude": shock["shock_magnitude"],
                "portfolio_return_pct": shock["portfolio_return"] * 100,
                "portfolio_pnl_dollar": shock["portfolio_return"] * total,
                "total_notional": total,
                "top_loadings": top,
                "asset_returns": asset_returns,
                "rows": asset_returns,
                "loadings": loading_rows,
                "samples": int(df.shape[0]),
                "summary": {
                    "pc_index": pc_index,
                    "k_sigma": k_sigma,
                    "portfolio_return_pct": shock["portfolio_return"] * 100,
                    "portfolio_pnl_dollar": shock["portfolio_return"] * total,
                },
                "methodology": (
                    "Run PCA on aligned daily return history, shock the selected principal component by "
                    "k standard deviations, then project the correlated asset return shock through current "
                    "portfolio weights to estimate P&L."
                ),
                "field_dictionary": {
                    "explained_variance_ratio": "Share of return variance explained by each principal component.",
                    "shock_return_pct": "Asset return implied by the selected PCA shock.",
                    "pnl": "Dollar contribution of the shock to portfolio P&L.",
                    "loading": "Symbol loading on the selected principal component.",
                },
            },
            sources=["yfinance" if live_prices else "portfolio_state_model"],
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _empty_pcas(
    code: str,
    instrument: Instrument | None,
    pc_index: int,
    k_sigma: float,
    reason: str,
) -> FunctionResult:
    return FunctionResult(
        code=code,
        instrument=instrument,
        data={
            "status": "ready_no_positions" if "portfolio" in reason else "provider_unavailable",
            "reason": reason,
            "pc_index": pc_index,
            "k_sigma": k_sigma,
            "explained_variance_ratio": [],
            "portfolio_return_pct": None,
            "portfolio_pnl_dollar": None,
            "top_loadings": [],
            "samples": 0,
            "rows": [],
            "next_actions": [
                "Add real positions through portfolio state.",
                "Set live=true and live_prices=true to fetch return history.",
            ],
            "methodology": (
                "PCA stress requires portfolio positions plus aligned return history. It shocks one "
                "principal component and maps the shock through position weights."
            ),
        },
        sources=["portfolio_state"],
        metadata={"empty": True, "requires_positions": True},
    )
