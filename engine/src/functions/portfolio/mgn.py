"""MGN — Cross-account margin / buying power."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.services import margin_engine


@FunctionRegistry.register
class MGNFunction(BaseFunction):
    code = "MGN"
    name = "Cross-Account Margin"
    category = "portfolio"
    description = "Margin requirements + buying power per account."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = (params.get("action") or "calc").lower()
        if action == "list":
            return FunctionResult(code=self.code, instrument=None,
                                  data={"accounts": margin_engine.list_accounts()})
        if action == "upsert":
            info = margin_engine.upsert_account(
                name=params["name"],
                margin_type=params.get("margin_type", "reg_t"),
                cash=float(params.get("cash", 0)),
                currency=params.get("currency", "USD"),
                overrides=params.get("overrides") or {},
            )
            return FunctionResult(code=self.code, instrument=None,
                                  data={"account": params["name"], **info})
        if action == "delete":
            ok = margin_engine.delete_account(params["name"])
            return FunctionResult(code=self.code, instrument=None,
                                  data={"deleted": ok, "name": params["name"]})
        # default: calc
        refresh_prices = bool(params.get("refresh_prices") or params.get("live_prices"))
        include_saved = bool(params.get("include_saved") or params.get("saved_portfolio"))
        if not refresh_prices and not include_saved:
            positions = params.get("positions") or _sample_margin_positions(instrument, params)
            cfg = {
                "accounts": {
                    "paper": {
                        "margin_type": params.get("margin_type") or _margin_type_for_positions(positions),
                        "cash": float(params.get("cash", 10000.0)),
                        "currency": params.get("currency", "USD"),
                        "overrides": params.get("overrides") or {},
                    }
                }
            }
            account = margin_engine.calc_account("paper", positions, cfg=cfg)
            total = {
                "equity": account["equity"],
                "initial_margin": account["initial_margin"],
                "maintenance_margin": account["maintenance_margin"],
                "buying_power": account["buying_power"],
                "excess_initial": account["excess_initial"],
                "maintenance_cushion_pct": account["maintenance_cushion_pct"],
            }
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={"accounts": [account], "total": total},
                sources=["margin_engine"],
                metadata={"live": False},
            )

        from src.portfolio.state import PortfolioState
        portfolio = PortfolioState()
        prices = (
            await self._quote_many([p.instrument.symbol for p in portfolio.positions])
            if refresh_prices
            else {}
        )
        result = margin_engine.calc_all_accounts(
            prices=prices,
            include_legacy=bool(params.get("include_legacy") or params.get("legacy")),
        )
        return FunctionResult(code=self.code, instrument=None,
                              data=result,
                              sources=["yfinance"] if refresh_prices else ["portfolio_state"],
                              warnings=[])

    async def _quote_many(self, symbols: list[str]) -> dict[str, float]:
        if not self.deps.yfinance or not symbols:
            return {}
        async def _q(sym: str) -> tuple[str, float]:
            try:
                inst = Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
                if self.deps.symbol_registry:
                    r = await self.deps.symbol_registry.resolve(sym)
                    if r:
                        inst = r
                quote = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.QUOTE, instrument=inst))
                return sym, float(quote.last or 0)
            except Exception:
                return sym, 0.0
        results = await asyncio.gather(*(_q(s) for s in symbols))
        return dict(results)


def _sample_margin_positions(
    instrument: Instrument | None,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    symbol = str(params.get("symbol") or (instrument.symbol if instrument else "BTCUSDT")).upper()
    asset_class = (
        instrument.asset_class.value
        if instrument is not None
        else str(params.get("asset_class") or "CRYPTO").upper()
    )
    if asset_class == "FX":
        quantity = 100000.0
        avg_cost = 1.08
        last = 1.09
    elif asset_class == "COMMODITY":
        quantity = 2.0
        avg_cost = 2300.0
        last = 2350.0
    elif asset_class in {"EQUITY", "ETF"}:
        quantity = 50.0
        avg_cost = 190.0
        last = 205.0
    else:
        quantity = 0.25
        avg_cost = 65000.0
        last = 78500.0
    return [{
        "symbol": symbol,
        "asset_class": asset_class,
        "quantity": quantity,
        "avg_cost": avg_cost,
        "last": last,
        "currency": params.get("currency", "USD"),
    }]


def _margin_type_for_positions(positions: list[dict[str, Any]]) -> str:
    classes = {str(p.get("asset_class") or "").upper() for p in positions}
    if classes & {"FX"}:
        return "fx"
    if classes & {"COMMODITY", "DERIVATIVE"}:
        return "futures"
    if classes & {"CRYPTO"}:
        return "crypto_futures"
    return "reg_t"
