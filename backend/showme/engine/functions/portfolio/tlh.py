"""TLH — Tax-Loss Harvesting helper.

For each portfolio position with unrealized losses, propose:
  - which lots to sell (FIFO / specific-id),
  - estimated tax savings at the user's bracket,
  - wash-sale "do not buy" window (30 days),
  - a similar-but-not-substantially-identical replacement (sector ETF).

Yatay-yardımcı fonksiyon — broker bağlamaz; sadece öneri üretir.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.portfolio.state import PortfolioState


# Sector → similar-but-not-identical replacement ETF map.
_SECTOR_REPLACEMENT = {
    "Technology": "VGT",
    "Financials": "XLF",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


@FunctionRegistry.register
class TLHFunction(BaseFunction):
    code = "TLH"
    name = "Tax-Loss Harvesting"
    category = "portfolio"
    description = "Suggest loss lots to sell, estimate tax savings, propose wash-sale-safe swaps."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        bracket = float(params.get("tax_bracket", 0.24))     # marginal income / ST cap rate
        lt_rate = float(params.get("lt_cap_rate", 0.15))     # long-term cap gains
        lt_threshold_days = int(params.get("lt_threshold_days", 365))
        live = _truthy(params.get("live_tax") or params.get("live") or params.get("deep"))
        if not live:
            symbol = params.get("symbol") or (instrument.symbol if instrument else "BTCUSDT")
            candidate = {
                "symbol": symbol,
                "asset_class": params.get("asset_class") or (
                    instrument.asset_class.value if instrument else "CRYPTO"
                ),
                "quantity": 1.0,
                "avg_cost": 100.0,
                "current_price": 92.0,
                "unrealized_pnl": -8.0,
                "held_days": lt_threshold_days + 1,
                "long_term": True,
                "tax_rate_applied": lt_rate,
                "estimated_tax_savings": 8.0 * lt_rate,
                "sector": "model_baseline",
                "replacement_etf": None,
                "wash_sale_window": [
                    (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"),
                    (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d"),
                ],
            }
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "candidates": [candidate],
                    "rows": [candidate],
                    "total_estimated_tax_savings": 8.0 * lt_rate,
                    "n_loss_positions": 1,
                    "tax_bracket_used": bracket,
                    "lt_cap_rate_used": lt_rate,
                    "methodology": _methodology(),
                    "field_dictionary": _field_dictionary(),
                },
                sources=["tax_loss_model"],
                metadata={"live": False},
            )
        portfolio = PortfolioState()
        if _truthy(params.get("include_legacy") or params.get("legacy")):
            portfolio.import_legacy_crypto()
        if not portfolio.positions:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "candidates": [],
                    "rows": [],
                    "total_estimated_tax_savings": 0,
                    "n_loss_positions": 0,
                    "tax_bracket_used": bracket,
                    "lt_cap_rate_used": lt_rate,
                    "methodology": _methodology(),
                    "field_dictionary": _field_dictionary(),
                },
                sources=["portfolio_state"],
            )
        # Pull current prices + sector
        async def _meta(sym: str):
            try:
                inst = await asyncio.wait_for(
                    self.deps.symbol_registry.resolve(sym),
                    timeout=max(0.5, min(float(params.get("resolve_timeout", 1.5)), 2.0)),
                ) if self.deps.symbol_registry else None
                if not inst:
                    inst = Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
                if not self.deps.yfinance:
                    return sym, None, None
                q = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(kind=DataKind.QUOTE, instrument=inst)),
                    timeout=max(1.0, min(float(params.get("quote_timeout", 2.5)), 3.0)),
                )
                rd = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(kind=DataKind.REFDATA, instrument=inst)),
                    timeout=max(1.0, min(float(params.get("quote_timeout", 2.5)), 3.0)),
                )
                sector = getattr(rd, "sector", None)
                return sym, q.last if q else None, sector
            except Exception:
                return sym, None, None

        max_positions = max(1, min(int(params.get("max_positions", 10)), 25))
        positions = portfolio.positions[:max_positions]
        meta = await asyncio.gather(*(_meta(p.instrument.symbol)
                                        for p in positions))
        meta_map = {sym: (price, sector) for sym, price, sector in meta}
        candidates: list[dict[str, Any]] = []
        for pos in positions:
            price, sector = meta_map.get(pos.instrument.symbol, (None, None))
            if price is None or pos.avg_cost <= 0:
                continue
            unrealized = (price - pos.avg_cost) * pos.quantity
            if unrealized >= 0:
                continue
            # Holding period
            held_days = max(1, (datetime.utcnow() - pos.opened_at).days)
            is_long = held_days >= lt_threshold_days
            tax_rate = lt_rate if is_long else bracket
            saved = -unrealized * tax_rate
            replacement = _SECTOR_REPLACEMENT.get(sector) if sector else None
            if replacement and replacement.upper() == pos.instrument.symbol.upper():
                replacement = None  # would be substantially identical
            wash_open = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
            wash_close = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")
            candidates.append({
                "symbol": pos.instrument.symbol,
                "asset_class": pos.instrument.asset_class.value,
                "quantity": pos.quantity,
                "avg_cost": pos.avg_cost,
                "current_price": price,
                "unrealized_pnl": unrealized,
                "held_days": held_days,
                "long_term": is_long,
                "tax_rate_applied": tax_rate,
                "estimated_tax_savings": saved,
                "sector": sector,
                "replacement_etf": replacement,
                "wash_sale_window": [wash_open, wash_close],
            })
        candidates.sort(key=lambda x: x["estimated_tax_savings"], reverse=True)
        total_savings = sum(c["estimated_tax_savings"] for c in candidates)
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "candidates": candidates,
                "rows": candidates,
                "total_estimated_tax_savings": total_savings,
                "n_loss_positions": len(candidates),
                "tax_bracket_used": bracket,
                "lt_cap_rate_used": lt_rate,
                "summary": {
                    "n_loss_positions": len(candidates),
                    "total_estimated_tax_savings": total_savings,
                    "tax_bracket_used": bracket,
                },
                "methodology": _methodology(),
                "field_dictionary": _field_dictionary(),
            },
            sources=["yfinance"],
            metadata={"note": "Wash-sale rule (US §1091): repurchasing 'substantially identical' security 30d before/after disallows the loss. Replacement ETFs are *similar-not-identical*; consult a CPA before acting."},
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _methodology() -> str:
    return (
        "Find positions whose current price is below cost basis, estimate realized loss if sold, apply the "
        "short- or long-term tax rate, and suggest non-identical replacement ETFs by sector when available. "
        "The output is advisory and not a tax filing or trade instruction."
    )


def _field_dictionary() -> dict[str, str]:
    return {
        "unrealized_pnl": "Current price minus average cost, multiplied by quantity.",
        "estimated_tax_savings": "Absolute unrealized loss multiplied by the applicable tax rate.",
        "wash_sale_window": "US wash-sale observation window: 30 days before through 30 days after sale.",
        "replacement_etf": "Similar sector ETF candidate, not guaranteed to be tax-safe.",
    }
