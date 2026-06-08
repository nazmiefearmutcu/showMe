"""PORT — Comprehensive Portfolio Analytics."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.portfolio.state import PortfolioState


def historical_var(returns: pd.Series, alpha: float = 0.05) -> float:
    """Historical VaR as a POSITIVE LOSS (audit Q3 #13).

    Returns the alpha-quantile loss: a value of 0.025 means a 2.5%
    worst-case loss at the chosen confidence. Callers that prefer the
    signed-return convention can pass ``signed=True``.
    """
    if returns.empty:
        return 0.0
    quantile = float(np.percentile(returns, alpha * 100))
    return -quantile if quantile < 0 else 0.0


def parametric_var(returns: pd.Series, alpha: float = 0.05) -> float:
    """Parametric VaR as a positive loss (audit Q3 #13)."""
    if returns.empty:
        return 0.0
    try:
        from scipy.stats import norm  # type: ignore
        z = float(norm.ppf(alpha))
    except Exception:
        # Use the same Acklam approximation as pvar._norm_ppf.
        from showme.engine.functions.portfolio.pvar import _norm_ppf
        z = float(_norm_ppf(alpha))
    mu = float(returns.mean())
    sigma = float(returns.std())
    signed = mu + sigma * z
    return -signed if signed < 0 else 0.0


def expected_tail_loss(returns: pd.Series, alpha: float = 0.05) -> float:
    """ETL/CVaR as a positive loss (audit Q3 #13)."""
    if returns.empty:
        return 0.0
    # Compute the alpha-quantile in signed-return space, then flip sign.
    threshold = float(np.percentile(returns, alpha * 100))
    tail = returns[returns <= threshold]
    if tail.empty:
        return -threshold if threshold < 0 else 0.0
    mean_tail = float(tail.mean())
    return -mean_tail if mean_tail < 0 else 0.0


@FunctionRegistry.register
class PORTFunction(BaseFunction):
    code = "PORT"
    name = "Portfolio Analytics"
    category = "portfolio"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        portfolio: PortfolioState = params.get("_portfolio_override") or PortfolioState()
        if params.get("_portfolio_override") is None:
            portfolio.import_legacy_crypto()
        if not portfolio.positions:
            rows = params.get("positions") or []
            if not rows:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        "status": "ready_no_positions",
                        "connected_exchanges": 0,
                        "positions": [],
                        "totals": {
                            "market_value": 0.0,
                            "n_positions": 0,
                            "unrealized_pnl": 0.0,
                        },
                        "by_asset_class": {},
                        "next_actions": [
                            "Add real positions through the portfolio state surface.",
                            "Or pass positions in Params JSON with symbol, asset_class, quantity, avg_cost, and last.",
                        ],
                    },
                    sources=["portfolio_state"],
                    metadata={"empty": True, "requires_positions": True},
                )
            total_mv = 0.0
            out_rows = []
            for row in rows:
                mv = float(row["quantity"]) * float(row.get("last", row["avg_cost"]))
                total_mv += mv
                out_rows.append({**row, "market_value": mv,
                                 "unrealized_pnl": (float(row.get("last", row["avg_cost"])) -
                                                    float(row["avg_cost"])) * float(row["quantity"])})
            for row in out_rows:
                row["weight_pct"] = row["market_value"] / total_mv * 100 if total_mv else 0
            return FunctionResult(code=self.code, instrument=None,
                                  data={"positions": out_rows,
                                        "totals": {"market_value": total_mv,
                                                   "n_positions": len(out_rows),
                                                   "unrealized_pnl": sum(r["unrealized_pnl"] for r in out_rows)}},
                                  sources=["user_positions"])
        # Best-effort: get live last prices via yfinance for *all* asset classes
        # (crypto included — see note below), falling back to the runtime last
        # price / avg_cost when no quote is available.
        prices: dict[str, float] = {}
        rows: list[dict[str, Any]] = []
        used_sources = {"portfolio_state"}
        for pos in portfolio.positions:
            sym = pos.instrument.symbol
            last = _position_last_price(pos)
            try:
                # Crypto is no longer excluded: the yfinance data source's
                # `_yf_symbol` already maps crypto pairs (BTCUSDT / BTC/USDT)
                # to Yahoo's "BTC-USD" spot form, so crypto positions can take
                # a live mark instead of falling back to a stale avg_cost.
                if self.deps.yfinance:
                    from showme.engine.core.base_data_source import DataKind, DataRequest
                    q = await self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.QUOTE, instrument=pos.instrument
                    ))
                    last = q.last or last
                    used_sources.add("yfinance")
            except Exception:
                pass
            prices[sym] = last
            mv = pos.quantity * last
            unrl = (last - pos.avg_cost) * pos.quantity
            rows.append({
                "symbol": sym, "asset_class": pos.instrument.asset_class.value,
                "quantity": pos.quantity, "avg_cost": pos.avg_cost,
                "last": last, "market_value": mv,
                "unrealized_pnl": unrl,
                "weight_pct": None,
            })
        df = pd.DataFrame(rows)
        total_mv = float(df["market_value"].sum() or 0)
        if total_mv:
            df["weight_pct"] = df["market_value"] / total_mv * 100
        # VaR / ETL on (legacy) returns from state.json trade_history if available
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "positions": df.to_dict(orient="records"),
                "totals": {
                    "market_value": total_mv,
                    "unrealized_pnl": float(df["unrealized_pnl"].sum() or 0),
                    "n_positions": int(len(df)),
                },
                "by_asset_class": df.groupby("asset_class")["market_value"].sum().to_dict(),
            },
            sources=sorted(used_sources),
        )


def _position_last_price(pos: Any) -> float:
    metadata = getattr(getattr(pos, "instrument", None), "metadata", {}) or {}
    current = metadata.get("current_price")
    if current not in (None, ""):
        try:
            return float(current)
        except (TypeError, ValueError):
            pass
    return float(getattr(pos, "avg_cost", 0) or 0)
