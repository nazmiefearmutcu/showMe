"""ACCT — Multi-account portfolio aggregator.

Hesap (account) bazlı pozisyon dağılımı + per-account PORT view.
Hesaplar: 'main', 'paper', 'ibkr', 'alpaca', 'oanda', 'binance' vb.
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.portfolio.state import PortfolioState


@FunctionRegistry.register
class ACCTFunction(BaseFunction):
    code = "ACCT"
    name = "Multi-Account Aggregation"
    category = "portfolio"
    description = "Per-account position roll-up + cross-account exposure totals."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        portfolio = PortfolioState()
        portfolio.import_legacy_crypto()
        if not portfolio.positions:
            positions = params.get("positions") or []
            if not positions:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        "status": "ready_no_positions",
                        "accounts": [],
                        "cross": {"total_mv": 0.0, "by_asset_class": {}, "by_symbol": {}},
                        "rows": [],
                        "next_actions": [
                            "Add real positions through the portfolio state surface.",
                            "Or pass positions in Params JSON with symbol, asset_class, quantity, avg_cost, last, and account.",
                        ],
                    },
                    sources=["portfolio_state"],
                    metadata={"empty": True, "requires_positions": True},
                )
            # BUG-HUNT S01: previously user-supplied `positions` were
            # blindly cast through float(); a non-numeric quantity or
            # avg_cost bubbled as a 500 with no actionable error. Validate
            # each row + collect skipped entries into a warning so the
            # user can fix their Params JSON.
            accounts: dict[str, dict[str, Any]] = {}
            skipped: list[dict[str, Any]] = []
            if not isinstance(positions, list):
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        "status": "input_error",
                        "reason": "positions must be a JSON array of position objects.",
                        "rows": [],
                        "next_actions": [
                            "Pass positions=[{symbol, asset_class, quantity, avg_cost, last, account}, ...].",
                        ],
                    },
                    sources=[],
                )
            for idx, p in enumerate(positions):
                if not isinstance(p, dict) or not p.get("symbol"):
                    skipped.append({"index": idx, "reason": "missing dict or symbol"})
                    continue
                try:
                    qty = float(p.get("quantity", 0))
                    price = float(p.get("last", p.get("avg_cost", 0)))
                except (TypeError, ValueError):
                    skipped.append({"index": idx, "symbol": p.get("symbol"),
                                    "reason": "quantity/last/avg_cost not numeric"})
                    continue
                acct = p.get("account", "paper")
                mv = qty * price
                slot = accounts.setdefault(acct, {"account": acct, "positions": [],
                                                   "total_mv": 0.0, "n_positions": 0,
                                                   "by_asset_class": {}})
                slot["positions"].append({**p, "market_value": mv})
                slot["total_mv"] += mv
                slot["n_positions"] += 1
                ac = p.get("asset_class", "OTHER")
                slot["by_asset_class"][ac] = slot["by_asset_class"].get(ac, 0) + mv
            cross = {"total_mv": sum(a["total_mv"] for a in accounts.values()),
                     "by_asset_class": {}, "by_symbol": {}}
            for slot in accounts.values():
                for ac, mv in slot["by_asset_class"].items():
                    cross["by_asset_class"][ac] = cross["by_asset_class"].get(ac, 0) + mv
                for p in slot["positions"]:
                    cross["by_symbol"][p["symbol"]] = cross["by_symbol"].get(p["symbol"], 0) + p["market_value"]
            metadata: dict[str, Any] = {}
            if skipped:
                metadata["provider_errors"] = [
                    f"ACCT: skipped {len(skipped)} invalid position row(s)"
                ]
                metadata["skipped_positions"] = skipped
            return FunctionResult(code=self.code, instrument=None,
                                  data={"accounts": list(accounts.values()),
                                        "rows": [_account_row(slot) for slot in accounts.values()],
                                        "cross": cross,
                                        "methodology": _methodology(),
                                        "field_dictionary": _field_dictionary()},
                                  sources=["user_positions"],
                                  metadata=metadata)
        # Resolve last prices per symbol (single fetch each).
        symbols = {p.instrument.symbol: p for p in portfolio.positions}
        async def _q(sym: str) -> tuple[str, float]:
            pos = symbols[sym]
            if pos.instrument.asset_class == AssetClass.CRYPTO:
                return sym, float(pos.avg_cost or 0)
            try:
                inst = await self.deps.symbol_registry.resolve(sym) if self.deps.symbol_registry else None
                if not inst:
                    inst = Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
                if not self.deps.yfinance:
                    return sym, float(pos.avg_cost or 0)
                quote = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(kind=DataKind.QUOTE, instrument=inst)),
                    timeout=float(params.get("quote_timeout", 5)),
                )
                return sym, float(quote.last or pos.avg_cost or 0)
            except Exception:
                return sym, float(pos.avg_cost or 0)
        prices = dict(await asyncio.gather(*(_q(s) for s in symbols.keys())))
        # Group by account
        by_account: dict[str, dict[str, Any]] = {}
        for p in portfolio.positions:
            acct = p.account or "main"
            slot = by_account.setdefault(acct, {
                "account": acct, "positions": [], "total_mv": 0.0,
                "total_unrealized_pnl": 0.0, "n_positions": 0,
                "by_asset_class": {},
            })
            sym = p.instrument.symbol
            px = prices.get(sym) or p.avg_cost
            mv = p.quantity * px
            unrl = (px - p.avg_cost) * p.quantity
            ac = p.instrument.asset_class.value
            slot["positions"].append({
                "symbol": sym, "asset_class": ac,
                "quantity": p.quantity, "avg_cost": p.avg_cost,
                "last": px, "market_value": mv, "unrealized_pnl": unrl,
                "currency": p.currency,
            })
            slot["total_mv"] += mv
            slot["total_unrealized_pnl"] += unrl
            slot["n_positions"] += 1
            slot["by_asset_class"][ac] = slot["by_asset_class"].get(ac, 0) + mv
        # Cross-account exposure
        cross = {"by_asset_class": {}, "by_symbol": {}, "total_mv": 0.0}
        for slot in by_account.values():
            for ac, mv in slot["by_asset_class"].items():
                cross["by_asset_class"][ac] = cross["by_asset_class"].get(ac, 0) + mv
            for pos in slot["positions"]:
                cross["by_symbol"][pos["symbol"]] = (
                    cross["by_symbol"].get(pos["symbol"], 0) + pos["market_value"]
                )
            cross["total_mv"] += slot["total_mv"]
        return FunctionResult(
            code=self.code, instrument=None,
            data={"accounts": list(by_account.values()),
                  "rows": [_account_row(slot) for slot in by_account.values()],
                  "cross": cross,
                  "summary": {
                      "accounts": len(by_account),
                      "positions": sum(slot["n_positions"] for slot in by_account.values()),
                      "total_market_value": cross["total_mv"],
                  },
                  "methodology": _methodology(),
                  "field_dictionary": _field_dictionary()},
            sources=["yfinance"],
        )


def _account_row(slot: dict[str, Any]) -> dict[str, Any]:
    return {
        "account": slot.get("account"),
        "positions": slot.get("n_positions"),
        "market_value": slot.get("total_mv"),
        "unrealized_pnl": slot.get("total_unrealized_pnl"),
        "top_asset_class": _top_key(slot.get("by_asset_class") or {}),
    }


def _top_key(values: dict[str, float]) -> str | None:
    if not values:
        return None
    return max(values.items(), key=lambda item: abs(float(item[1] or 0)))[0]


def _methodology() -> str:
    return (
        "Group saved or supplied positions by account, mark each position with the latest available price, "
        "then aggregate market value, unrealized P&L, asset-class exposure, and symbol exposure across accounts."
    )


def _field_dictionary() -> dict[str, str]:
    return {
        "market_value": "Position quantity multiplied by latest price or cost fallback.",
        "unrealized_pnl": "(latest price - average cost) * quantity.",
        "top_asset_class": "Largest asset-class exposure for the account.",
        "cross": "Cross-account aggregate exposure by asset class and symbol.",
    }
