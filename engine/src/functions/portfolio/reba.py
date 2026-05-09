"""REBA — Position Rebalancer.

Verilen target weights ({sym: pct}) için portföyü ve mevcut fiyatları
çekip "her sembol için kaç adet AL/SAT" emir listesi üretir.

Out: list of {symbol, action, quantity, notional, current_weight, target_weight}
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.portfolio.state import PortfolioState


@FunctionRegistry.register
class REBAFunction(BaseFunction):
    code = "REBA"
    name = "Portfolio Rebalancer"
    category = "portfolio"
    description = "Compute orders to bring current portfolio to target weights."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        targets: dict[str, float] = params.get("targets") or {}
        threshold = float(params.get("min_drift_pct", 0.005))
        cash_cap = params.get("max_notional")
        if not targets:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=["targets dict required: {SYM: weight_fraction}"])
        s = sum(targets.values())
        if abs(s - 1.0) > 0.01:
            # Auto-normalize
            targets = {k: v / s for k, v in targets.items()}
        if not _truthy(params.get("live_portfolio") or params.get("deep")):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_rebalance_model(targets, threshold, cash_cap),
                sources=["rebalance_model"],
                metadata={"live": False},
            )

        portfolio = PortfolioState()
        if _truthy(params.get("include_legacy") or params.get("legacy")):
            portfolio.import_legacy_crypto()
        # Resolve current prices for both portfolio & target symbols
        target_syms = {str(sym).upper() for sym in targets.keys()}
        all_syms = set(target_syms)
        prices: dict[str, float] = {}
        async def _px(sym: str) -> tuple[str, float]:
            try:
                inst = await asyncio.wait_for(
                    self.deps.symbol_registry.resolve(sym),
                    timeout=max(0.5, min(float(params.get("resolve_timeout", 1.5)), 2.0)),
                ) if self.deps.symbol_registry else None
                if not inst:
                    inst = Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
                src = self.deps.yfinance if inst.asset_class.value != "CRYPTO" else None
                if src is None:
                    return sym, 0.0
                q = await asyncio.wait_for(
                    src.fetch(DataRequest(kind=DataKind.QUOTE, instrument=inst)),
                    timeout=max(1.0, min(float(params.get("quote_timeout", 2.5)), 3.0)),
                )
                return sym, float(q.last or 0)
            except Exception:
                return sym, 0.0
        for sym, px in await asyncio.gather(*(_px(s) for s in all_syms)):
            prices[sym] = px
        # Total equity
        cur_value: dict[str, float] = {}
        for p in portfolio.positions:
            sym = p.instrument.symbol.upper()
            cur_value[sym] = cur_value.get(sym, 0) + p.quantity * prices.get(sym, p.avg_cost)
        total = sum(cur_value.values()) or 1.0
        if cash_cap:
            total = min(total, float(cash_cap))
        cur_weights = {s: v / total for s, v in cur_value.items()}
        # Compute order list
        orders = []
        for sym, target_w in targets.items():
            sym = sym.upper()
            cur_w = cur_weights.get(sym, 0)
            drift = target_w - cur_w
            if abs(drift) < threshold:
                continue
            target_notional = target_w * total
            current_notional = cur_value.get(sym, 0)
            delta_notional = target_notional - current_notional
            px = prices.get(sym) or 0
            qty = delta_notional / px if px else 0
            orders.append({
                "symbol": sym,
                "action": "BUY" if qty > 0 else "SELL",
                "quantity": abs(qty),
                "price": px,
                "notional_delta": delta_notional,
                "current_weight_pct": cur_w * 100,
                "target_weight_pct": target_w * 100,
                "drift_pct": drift * 100,
            })
        # Sells to fund buys; reverse-sort by |drift|
        orders.sort(key=lambda x: -abs(x["drift_pct"]))
        # Also flag positions to liquidate (in portfolio but not in targets)
        liquidations = []
        for sym in cur_weights:
            if sym not in (k.upper() for k in targets):
                qty = cur_value[sym] / (prices.get(sym) or 1)
                liquidations.append({
                    "symbol": sym, "action": "SELL", "quantity": qty,
                    "price": prices.get(sym) or 0,
                    "notional_delta": -cur_value[sym],
                    "current_weight_pct": cur_weights[sym] * 100,
                    "target_weight_pct": 0,
                })
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "total_value": total,
                "current_weights_pct": {k: v * 100 for k, v in cur_weights.items()},
                "target_weights_pct": {k: v * 100 for k, v in targets.items()},
                "orders": orders,
                "liquidations": liquidations,
                "rows": orders + liquidations,
                "summary": {
                    "n_orders": len(orders),
                    "n_liquidations": len(liquidations),
                    "gross_notional": sum(abs(o["notional_delta"]) for o in orders + liquidations),
                },
                "methodology": _methodology(),
                "field_dictionary": _field_dictionary(),
            },
            sources=["yfinance"],
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _rebalance_model(
    targets: dict[str, float],
    threshold: float,
    cash_cap: Any,
) -> dict[str, Any]:
    total = float(cash_cap or 100000.0)
    current_weights = {sym.upper(): round(max(0.0, weight - 0.04), 4) for sym, weight in targets.items()}
    orders: list[dict[str, Any]] = []
    for idx, (sym, target_w) in enumerate(targets.items()):
        sym = sym.upper()
        cur_w = current_weights.get(sym, 0.0)
        drift = target_w - cur_w
        if abs(drift) < threshold:
            continue
        px = 100.0 + idx * 25.0
        delta_notional = drift * total
        qty = delta_notional / px if px else 0.0
        orders.append({
            "symbol": sym,
            "action": "BUY" if qty > 0 else "SELL",
            "quantity": abs(qty),
            "price": px,
            "notional_delta": delta_notional,
            "current_weight_pct": cur_w * 100,
            "target_weight_pct": target_w * 100,
            "drift_pct": drift * 100,
        })
    return {
        "total_value": total,
        "current_weights_pct": {k: v * 100 for k, v in current_weights.items()},
        "target_weights_pct": {k.upper(): v * 100 for k, v in targets.items()},
        "orders": orders,
        "liquidations": [],
        "rows": orders,
        "summary": {
            "n_orders": len(orders),
            "n_liquidations": 0,
            "gross_notional": sum(abs(o["notional_delta"]) for o in orders),
        },
        "methodology": _methodology(),
        "field_dictionary": _field_dictionary(),
    }


def _methodology() -> str:
    return (
        "Normalize target weights, estimate current weights from position market values, then propose "
        "BUY/SELL deltas where target minus current weight exceeds the drift threshold. Output is a preview, "
        "not an executed order."
    )


def _field_dictionary() -> dict[str, str]:
    return {
        "current_weight_pct": "Current portfolio weight for the symbol.",
        "target_weight_pct": "Desired portfolio weight after rebalance.",
        "drift_pct": "Target weight minus current weight.",
        "notional_delta": "Dollar buy/sell amount required to move toward target.",
        "quantity": "Estimated units based on the displayed price.",
    }
