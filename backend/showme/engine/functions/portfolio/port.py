"""PORT — Comprehensive Portfolio Analytics."""

from __future__ import annotations

import asyncio
import math
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.portfolio.state import PortfolioState

# Mirror of ``portfolio_aggregate._STABLE_TO_USD``: only stable-USD cash may be
# summed into the USD ``totals.cash`` figure. Anything else stays in the
# per-currency map so the terminal never converts by assumption.
_STABLE_USD_CURRENCIES = {"USD", "USDT", "USDC", "DAI", "BUSD", "TUSD"}


def _cash_totals(cash: Any) -> tuple[float | None, dict[str, float]]:
    """Return ``(stable_usd_cash | None, per_currency_cash)``.

    ``None`` means the book does not track cash at all — the pane renders the
    shared em-dash instead of a confident $0.00 (audit A5 PORT H).
    """
    if not isinstance(cash, dict):
        return None, {}
    per_currency: dict[str, float] = {}
    for ccy, amount in cash.items():
        if isinstance(amount, bool):
            continue
        try:
            value = float(amount)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        per_currency[str(ccy).upper()] = value
    if not per_currency:
        return None, {}
    stable = sum(v for k, v in per_currency.items() if k in _STABLE_USD_CURRENCIES)
    return stable, per_currency


def _cash_fields(cash_usd: float | None, cash_by_currency: dict[str, float]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if cash_usd is not None:
        out["cash"] = cash_usd
    if cash_by_currency:
        out["cash_by_currency"] = cash_by_currency
    return out


def _finite_positive(value: Any) -> float | None:
    """A usable price: finite and strictly positive, otherwise ``None``."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


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
    description = (
        "Local portfolio book: positions, cost basis, unrealized P&L, cash and "
        "weights, with live quote marks when a quote source answers."
    )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        portfolio: PortfolioState = params.get("_portfolio_override") or PortfolioState()
        if params.get("_portfolio_override") is None:
            portfolio.import_legacy_crypto()
        cash_usd, cash_by_currency = _cash_totals(getattr(portfolio, "cash", None))
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
                            "cost_basis": 0.0,
                            "n_positions": 0,
                            "unrealized_pnl": 0.0,
                            **_cash_fields(cash_usd, cash_by_currency),
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
            total_cost = 0.0
            out_rows = []
            for row in rows:
                cost = float(row["avg_cost"])
                mv = float(row["quantity"]) * float(row.get("last", row["avg_cost"]))
                total_mv += mv
                total_cost += cost * float(row["quantity"])
                out_rows.append({**row, "market_value": mv,
                                 "unrealized_pnl": (float(row.get("last", row["avg_cost"])) -
                                                    float(row["avg_cost"])) * float(row["quantity"])})
            for row in out_rows:
                row["weight_pct"] = row["market_value"] / total_mv * 100 if total_mv else 0
            return FunctionResult(code=self.code, instrument=None,
                                  data={"positions": out_rows,
                                        "totals": {"market_value": total_mv,
                                                   "cost_basis": total_cost,
                                                   "n_positions": len(out_rows),
                                                   "unrealized_pnl": sum(r["unrealized_pnl"] for r in out_rows),
                                                   **_cash_fields(cash_usd, cash_by_currency)}},
                                  sources=["user_positions"])

        # Live marks come from the quote adapter. A position with no live quote
        # falls back to a recorded legacy snapshot price (reported as such); a
        # position with neither is reported as unpriced and is never marked at
        # its cost basis.
        used_sources = {"portfolio_state"}

        async def _quote(pos: Any) -> tuple[float | None, str, float | None]:
            if self.deps.yfinance:
                try:
                    from showme.engine.core.base_data_source import DataKind, DataRequest
                    q = await self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.QUOTE, instrument=pos.instrument
                    ))
                    last = _finite_positive(getattr(q, "last", None))
                    if last is not None:
                        return last, "yfinance", _finite_positive(getattr(q, "close_prev", None))
                except Exception:
                    pass
            legacy = _legacy_last_price(pos)
            if legacy is not None:
                return legacy, "legacy_snapshot", None
            return None, "missing", None

        # HNT-05: fetch quotes concurrently (ACCT's `_q` pattern). A
        # sequential per-position fetch easily blew the 14 s worker budget
        # on mid-sized books with a slow network.
        quotes = await asyncio.gather(*(_quote(pos) for pos in portfolio.positions))

        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        price_sources = {"yfinance": 0, "legacy_snapshot": 0, "missing": 0}
        priced_mv = 0.0
        priced_unrl = 0.0
        # Cost basis is qty * avg_cost, a fact of the book that needs no price,
        # so it covers every position (unpriced ones included).
        total_cost = 0.0
        by_class: dict[str, float] = {}
        for pos, (last, price_source, _prev_close) in zip(portfolio.positions, quotes):
            sym = pos.instrument.symbol
            qty = float(pos.quantity)
            avg = float(pos.avg_cost)
            price_sources[price_source] += 1
            total_cost += avg * qty
            if price_source == "yfinance":
                used_sources.add("yfinance")
            row: dict[str, Any] = {
                "symbol": sym,
                "asset_class": pos.instrument.asset_class.value,
                "currency": pos.currency,
                "quantity": qty,
                "avg_cost": avg,
                "last": last,
                "price_source": price_source,
                "quote_missing": last is None,
                "market_value": None,
                "unrealized_pnl": None,
                "weight_pct": None,
            }
            if last is None:
                warnings.append(f"{sym}: no live quote and no recorded price; excluded from market value and P&L")
            else:
                mv = qty * last
                unrl = (last - avg) * qty
                row["market_value"] = mv
                row["unrealized_pnl"] = unrl
                priced_mv += mv
                priced_unrl += unrl
                cls = pos.instrument.asset_class.value
                by_class[cls] = by_class.get(cls, 0.0) + mv
                if price_source == "legacy_snapshot":
                    warnings.append(f"{sym}: no live quote; using the recorded legacy snapshot price")
            rows.append(row)
        for row in rows:
            if row["market_value"] is not None and priced_mv:
                row["weight_pct"] = row["market_value"] / priced_mv * 100

        n_rows = len(rows)
        if n_rows and price_sources["yfinance"] == n_rows:
            price_state = "live"
        elif price_sources["yfinance"] == 0 and price_sources["missing"] == 0 and price_sources["legacy_snapshot"]:
            price_state = "legacy_snapshot"
        elif price_sources["missing"] == n_rows:
            price_state = "unavailable"
        else:
            price_state = "partial"

        # VaR / ETL on (legacy) returns from state.json trade_history if available
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "positions": rows,
                "totals": {
                    "market_value": priced_mv,
                    "cost_basis": total_cost,
                    "unrealized_pnl": priced_unrl,
                    "n_positions": n_rows,
                    "n_unpriced": price_sources["missing"],
                    **_cash_fields(cash_usd, cash_by_currency),
                },
                "by_asset_class": by_class,
            },
            metadata={"price_state": price_state, "price_sources": dict(price_sources)},
            sources=sorted(used_sources),
            warnings=warnings,
        )


def _legacy_last_price(pos: Any) -> float | None:
    """The recorded ``current_price`` from the legacy book, or ``None``.

    This is a snapshot taken when the book was written, not a live quote; the
    caller labels it ``legacy_snapshot``. There is deliberately no fallback to
    ``avg_cost``: a missing price must stay missing.
    """
    metadata = getattr(getattr(pos, "instrument", None), "metadata", {}) or {}
    return _finite_positive(metadata.get("current_price"))
