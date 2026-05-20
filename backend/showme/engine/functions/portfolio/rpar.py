"""RPAR — Risk parity portfolio construction (ERC weights)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.return_series import align_return_series, close_to_daily_returns
from showme.engine.services.risk_parity import (
    equal_risk_contribution,
    naive_inverse_vol,
    risk_contributions,
)


def _template_returns(symbols: list[str], days: int) -> pd.DataFrame:
    periods = max(60, min(days, 504))
    index = pd.date_range(end=datetime.now(timezone.utc).date(), periods=periods, freq="B")
    periods = len(index)
    t = np.arange(periods, dtype=float)
    rows = {}
    for i, sym in enumerate(symbols):
        rows[sym] = 0.0002 + i * 0.00002 + np.cos((t + i * 5) / (13 + i)) * (0.005 + i * 0.0008)
    return pd.DataFrame(rows, index=index)


@FunctionRegistry.register
class RPARFunction(BaseFunction):
    code = "RPAR"
    name = "Risk Parity (ERC)"
    category = "portfolio"
    description = "Compute equal-risk-contribution weights for given universe."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbols = params.get("symbols") or []
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbols:
            symbol = params.get("symbol") or (instrument.symbol if instrument else None)
            symbols = [symbol] if symbol else ["AAPL", "MSFT", "BTCUSDT", "EURUSD", "GC=F"]
        days = int(params.get("days", 504))
        target = params.get("target")  # optional list of weights
        method = (params.get("method") or "inverse_vol").lower()
        # S12 BugHunt: default flipped to LIVE when yfinance is available.
        # Previous behavior silently returned a deterministic template (with
        # source `risk_parity_model`) on every call that did not explicitly
        # set `live_risk=true` or `method=erc`. Callers can still opt back
        # into the fast template by passing `model=true`.
        force_model = _truthy(params.get("model"))
        live_param = params.get("live_risk")
        if live_param is None:
            live_param = params.get("live")
        if live_param is None:
            live = bool(self.deps.yfinance) and not force_model
        else:
            live = _truthy(live_param)
        if (force_model or not live) and "method" not in params and not target:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_fast_template(symbols, days),
                sources=["risk_parity_model"],
                metadata={
                    "live": False,
                    "method": "inverse_vol_model",
                    "fallback": True,
                    "fallback_reason": "model_requested" if force_model else "yfinance_unavailable",
                },
                warnings=["RPAR served a deterministic risk-parity_model template; pass live_risk=true for yfinance-derived weights"],
            )
        sources = ["yfinance"] if live else ["computed_return_model"]
        async def _ret(sym: str) -> tuple[str, pd.Series]:
            try:
                inst = Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
                if self.deps.symbol_registry:
                    r = await self.deps.symbol_registry.resolve(sym)
                    if r:
                        inst = r
                df = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.OHLCV, instrument=inst,
                        start=datetime.now(timezone.utc) - timedelta(days=days),
                        interval="1d",
                    )),
                    timeout=8,
                )
                return sym, close_to_daily_returns(df)
            except Exception:
                return sym, pd.Series(dtype=float)
        if live and self.deps.yfinance:
            rs = await asyncio.gather(*(_ret(s) for s in symbols))
            df = align_return_series(rs)
        else:
            df = pd.DataFrame()
        fallback_used = False
        fallback_reason: str | None = None
        if df.shape[0] < 10:
            # S12 BugHunt: when live mode falls through to the synthetic
            # return series, surface it via metadata + warnings so the UI
            # can render a visible badge instead of trusting the table.
            fallback_used = True
            fallback_reason = "yfinance_returned_insufficient_history"
            df = _template_returns(symbols, days)
            sources = ["computed_return_model"]
        cov = df.cov().values * 252
        if method == "inverse_vol":
            w = naive_inverse_vol(cov)
            info = {"method": "inverse_vol"}
        else:
            tgt = None
            if target:
                tgt = np.asarray(target, dtype=float)
            w, info = equal_risk_contribution(
                cov,
                target=tgt,
                max_iter=int(params.get("max_iter", 500)),
            )
            info["method"] = "erc"
        rc = risk_contributions(w, cov)
        rows = [
            {
                "symbol": symbol,
                "weight": float(w[i]),
                "weight_pct": float(w[i] * 100),
                "risk_contribution_pct": float(rc["risk_contributions_pct"][i] * 100),
                "annualized_vol": float(np.sqrt(cov[i, i])),
                "method": info.get("method"),
            }
            for i, symbol in enumerate(df.columns)
        ]
        warnings: list[str] = []
        if fallback_used:
            warnings.append(
                f"RPAR live mode fell through to deterministic returns: {fallback_reason}"
            )
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "symbols": list(df.columns),
                "weights": dict(zip(df.columns, w.tolist())),
                "portfolio_vol": rc["portfolio_vol"],
                "risk_contributions_pct": dict(zip(df.columns, rc["risk_contributions_pct"])),
                "samples": int(df.shape[0]),
                "info": info,
                "rows": rows,
                "fallback": fallback_used,
                "fallback_reason": fallback_reason,
                "summary": {
                    "method": info.get("method"),
                    "symbols": len(rows),
                    "portfolio_vol": rc["portfolio_vol"],
                },
                "methodology": (
                    "Estimate the annualized covariance matrix from daily returns. ERC mode solves for "
                    "weights whose percentage risk contributions match the target; inverse-vol mode is "
                    "shown explicitly as a faster approximation, not true ERC."
                ),
                "field_dictionary": {
                    "weight_pct": "Portfolio allocation weight in percent.",
                    "risk_contribution_pct": "Share of total portfolio variance contribution.",
                    "annualized_vol": "Single-asset annualized volatility from the covariance diagonal.",
                    "portfolio_vol": "Annualized portfolio volatility sqrt(w' covariance w).",
                },
            },
            sources=sources,
            warnings=warnings,
            metadata={"live": bool(live and not fallback_used), "fallback": fallback_used, "fallback_reason": fallback_reason},
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _fast_template(symbols: list[str], days: int) -> dict[str, Any]:
    clean = list(dict.fromkeys(str(s) for s in symbols if str(s)))
    if not clean:
        clean = ["AAPL", "MSFT", "BTCUSDT", "EURUSD", "GC=F"]
    vol_by_symbol: dict[str, float] = {}
    for idx, symbol in enumerate(clean):
        upper = symbol.upper()
        if upper.endswith(("USDT", "USDC", "BTC", "ETH")):
            vol = 0.58
        elif upper.endswith("=F"):
            vol = 0.28
        elif upper.endswith(("USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD")) and len(upper) == 6:
            vol = 0.11
        else:
            vol = 0.32
        vol_by_symbol[symbol] = vol + idx * 0.015
    inv = {symbol: 1.0 / max(vol, 1e-6) for symbol, vol in vol_by_symbol.items()}
    total = sum(inv.values()) or 1.0
    weights = {symbol: value / total for symbol, value in inv.items()}
    risk_pct = {symbol: 1.0 / len(clean) for symbol in clean}
    portfolio_vol = sum(weights[symbol] * vol_by_symbol[symbol] for symbol in clean)
    return {
        "symbols": clean,
        "weights": weights,
        "portfolio_vol": portfolio_vol,
        "risk_contributions_pct": risk_pct,
        "samples": max(60, min(days, 504)),
        "info": {"method": "inverse_vol_model", "iterations": 0, "residual": 0.0},
        "rows": [
            {
                "symbol": symbol,
                "weight": weights[symbol],
                "weight_pct": weights[symbol] * 100,
                "risk_contribution_pct": risk_pct[symbol] * 100,
                "annualized_vol": vol_by_symbol[symbol],
                "method": "inverse_vol_model",
            }
            for symbol in clean
        ],
        "methodology": (
            "Fast reference allocation using inverse volatility. Live ERC mode can solve equal risk "
            "contribution from return covariance when method=erc is supplied."
        ),
        "field_dictionary": {
            "weight_pct": "Portfolio allocation weight in percent.",
            "risk_contribution_pct": "Share of total portfolio risk contribution.",
            "annualized_vol": "Model annualized volatility used by inverse-vol weighting.",
        },
    }
