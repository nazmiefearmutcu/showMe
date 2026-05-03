"""ACCT — Multi-account portfolio aggregator.

Hesap (account) bazlı pozisyon dağılımı + per-account PORT view.
Hesaplar: 'main', 'paper', 'ibkr', 'alpaca', 'oanda', 'binance' vb.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.portfolio.state import PortfolioState


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
            accounts: dict[str, dict[str, Any]] = {}
            for p in positions:
                acct = p.get("account", "paper")
                mv = float(p.get("quantity", 0)) * float(p.get("last", p.get("avg_cost", 0)))
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
            return FunctionResult(code=self.code, instrument=None,
                                  data={"accounts": list(accounts.values()), "cross": cross},
                                  sources=["user_positions"])
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
            data={"accounts": list(by_account.values()), "cross": cross},
            sources=["yfinance"],
        )
