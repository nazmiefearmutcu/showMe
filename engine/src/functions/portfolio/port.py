"""PORT — Comprehensive Portfolio Analytics."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument
from src.portfolio.state import PortfolioState


def historical_var(returns: pd.Series, alpha: float = 0.05) -> float:
    if returns.empty:
        return 0.0
    return float(np.percentile(returns, alpha * 100))


def parametric_var(returns: pd.Series, alpha: float = 0.05) -> float:
    if returns.empty:
        return 0.0
    from scipy.stats import norm  # type: ignore
    mu = returns.mean(); sigma = returns.std()
    return float(mu + sigma * norm.ppf(alpha))


def expected_tail_loss(returns: pd.Series, alpha: float = 0.05) -> float:
    if returns.empty:
        return 0.0
    var = historical_var(returns, alpha)
    tail = returns[returns <= var]
    return float(tail.mean()) if not tail.empty else var


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
        # Best-effort: get last prices via yfinance for non-crypto, last close from runtime for crypto.
        prices: dict[str, float] = {}
        rows: list[dict[str, Any]] = []
        used_sources = {"portfolio_state"}
        for pos in portfolio.positions:
            sym = pos.instrument.symbol
            last = _position_last_price(pos)
            try:
                if self.deps.yfinance and pos.instrument.asset_class.value not in ("CRYPTO",):
                    from src.core.base_data_source import DataKind, DataRequest
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
