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
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.portfolio.state import PortfolioState
from showme.engine.utils.helpers import datetime_now


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
        # 2026-11-07 (strict truth audit): the former non-live "model" path
        # returned an invented candidate (cost 100, price 92, qty 1). TLH now
        # only ever works on the real local portfolio.
        bracket = float(params.get("tax_bracket", 0.24))     # marginal income / ST cap rate
        lt_rate = float(params.get("lt_cap_rate", 0.15))     # long-term cap gains
        lt_threshold_days = int(params.get("lt_threshold_days", 365))
        min_loss = abs(float(params.get("min_loss_threshold", 0) or 0))
        raw_wash = params.get("wash_sale_window_days")
        wash_days = 30 if raw_wash in (None, "") else max(0, int(raw_wash))
        suggest_replacement = _truthy(params.get("suggest_replacement", True))
        base = {
            "tax_bracket_used": bracket,
            "lt_cap_rate_used": lt_rate,
            "min_loss_threshold": min_loss,
            "wash_sale_window_days": wash_days,
            "methodology": _methodology(),
            "field_dictionary": _field_dictionary(),
        }
        portfolio = PortfolioState()
        if _truthy(params.get("include_legacy") or params.get("legacy")):
            portfolio.import_legacy_crypto()
        if not portfolio.positions:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    **base,
                    "status": "empty",
                    "reason": "The local portfolio has no positions, so there are no losses to harvest.",
                    "next_actions": ["Add positions with their cost basis and open date in PORT, then re-run TLH."],
                    "candidates": [],
                    "rows": [],
                    "total_estimated_tax_savings": 0,
                    "n_loss_positions": 0,
                },
                sources=["portfolio_state"],
            )

        async def _meta(sym: str, quote_timeout: float):
            try:
                inst = await asyncio.wait_for(
                    self.deps.symbol_registry.resolve(sym),
                    timeout=max(0.5, min(float(params.get("resolve_timeout", 1.5)), 2.0)),
                ) if getattr(self.deps, "symbol_registry", None) else None
                if not inst:
                    inst = Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
                if not getattr(self.deps, "yfinance", None):
                    return sym, None, None
                q = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(kind=DataKind.QUOTE, instrument=inst)),
                    timeout=quote_timeout,
                )
                sector = None
                if suggest_replacement:
                    try:
                        rd = await asyncio.wait_for(
                            self.deps.yfinance.fetch(DataRequest(kind=DataKind.REFDATA, instrument=inst)),
                            timeout=quote_timeout,
                        )
                        sector = getattr(rd, "sector", None)
                    except Exception:  # noqa: BLE001 - sector is optional
                        sector = None
                return sym, (q.last if q else None), sector
            except Exception:  # noqa: BLE001 - reported as unpriced below
                return sym, None, None

        quote_timeout = max(1.0, min(float(params.get("quote_timeout", 2.5)), 3.0))
        retry_timeout = max(quote_timeout, min(float(params.get("retry_quote_timeout", 6.0)), 8.0))
        max_positions = max(1, min(int(params.get("max_positions", 25)), 100))
        positions = portfolio.positions[:max_positions]
        meta = await asyncio.gather(*(_meta(p.instrument.symbol, quote_timeout) for p in positions))
        meta_map = {sym: (price, sector) for sym, price, sector in meta}
        # One slow quote must not silently drop a loss lot: retry the unpriced
        # symbols once with a longer timeout before reporting them as unpriced.
        missing = list(dict.fromkeys(
            p.instrument.symbol for p in positions
            if meta_map.get(p.instrument.symbol, (None, None))[0] is None
        ))
        if missing:
            retried = await asyncio.gather(*(_meta(sym, retry_timeout) for sym in missing))
            for sym, price, sector in retried:
                if price is not None:
                    meta_map[sym] = (price, sector)
        candidates: list[dict[str, Any]] = []
        unpriced: list[str] = []
        now = datetime_now()
        for pos in positions:
            price, sector = meta_map.get(pos.instrument.symbol, (None, None))
            if price is None:
                unpriced.append(pos.instrument.symbol)
                continue
            if pos.avg_cost <= 0:
                continue
            unrealized = (price - pos.avg_cost) * pos.quantity
            if unrealized >= 0 or -unrealized < min_loss:
                continue
            opened = pos.opened_at if pos.opened_at.tzinfo else pos.opened_at.replace(tzinfo=timezone.utc)
            held_days = max(1, (now - opened).days)
            # US rule: long-term means held MORE than one year (366+ days).
            is_long = held_days > lt_threshold_days
            tax_rate = lt_rate if is_long else bracket
            replacement = _SECTOR_REPLACEMENT.get(sector) if (sector and suggest_replacement) else None
            if replacement and replacement.upper() == pos.instrument.symbol.upper():
                replacement = None  # would be substantially identical
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
                "estimated_tax_savings": -unrealized * tax_rate,
                "sector": sector,
                "replacement_etf": replacement,
                "wash_sale_window": [
                    (now - timedelta(days=wash_days)).strftime("%Y-%m-%d"),
                    (now + timedelta(days=wash_days)).strftime("%Y-%m-%d"),
                ],
            })
        candidates.sort(key=lambda x: x["estimated_tax_savings"], reverse=True)
        total_savings = sum(c["estimated_tax_savings"] for c in candidates)
        warnings = []
        unpriced_symbols = sorted(set(unpriced))
        if unpriced_symbols:
            warnings.append(f"No current quote for {', '.join(unpriced_symbols)}; those positions were not evaluated.")
        if len(portfolio.positions) > max_positions:
            warnings.append(f"Only the first {max_positions} of {len(portfolio.positions)} positions were evaluated.")
        priced = len(positions) - len(unpriced)
        if priced == 0:
            return FunctionResult(
                code=self.code, instrument=None,
                data={**base, "status": "provider_unavailable",
                      "reason": "No current quotes were available for any portfolio position.",
                      "next_actions": ["Retry when the quote provider is reachable."],
                      "candidates": [], "rows": [], "total_estimated_tax_savings": 0, "n_loss_positions": 0,
                      "unpriced_symbols": unpriced_symbols},
                sources=["portfolio_state"], warnings=warnings,
            )
        # Any unpriced position means the result is incomplete: never "ok" with
        # zero candidates while a position could be at a loss.
        status = "partial" if unpriced_symbols else "ok"
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                **base,
                "status": status,
                "candidates": candidates,
                "rows": candidates,
                "total_estimated_tax_savings": total_savings,
                "n_loss_positions": len(candidates),
                "unpriced_symbols": unpriced_symbols,
                "summary": {
                    "positions_evaluated": priced,
                    "positions_unpriced": len(unpriced_symbols),
                    "n_loss_positions": len(candidates),
                    "total_estimated_tax_savings": total_savings,
                    "tax_bracket_used": bracket,
                },
            },
            sources=["portfolio_state", "yfinance"],
            warnings=warnings,
            metadata={"note": "Wash-sale rule (US 1091): repurchasing a substantially identical security within the window before/after the sale disallows the loss. Replacement ETFs are similar-not-identical; consult a CPA before acting."},
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
