"""STRS — Stress test against predefined and custom scenarios."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.portfolio.state import PortfolioState
from src.services import stress_scenarios as stress


@FunctionRegistry.register
class STRSFunction(BaseFunction):
    code = "STRS"
    name = "Portfolio Stress Test"
    category = "portfolio"
    description = "Apply historical and custom shock scenarios to portfolio."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = (params.get("action") or "list").lower()
        if action == "list":
            return FunctionResult(
                code=self.code, instrument=None,
                data={"scenarios": stress.list_scenarios()},
            )
        portfolio = PortfolioState()
        portfolio.import_legacy_crypto()
        if not portfolio.positions:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=["empty portfolio"])
        # Build position dicts with current MV
        symbols = list({p.instrument.symbol for p in portfolio.positions})
        prices = await self._quote_many(symbols)
        sector_lookup: dict[str, str] = {}
        if self.deps.yfinance:
            await self._sectors(symbols, sector_lookup)
        positions_payload: list[dict[str, Any]] = []
        for p in portfolio.positions:
            px = prices.get(p.instrument.symbol) or p.avg_cost
            mv = p.quantity * px
            positions_payload.append({
                "symbol": p.instrument.symbol,
                "asset_class": p.instrument.asset_class.value,
                "market_value": mv,
                "sector": sector_lookup.get(p.instrument.symbol),
            })
        scale = float(params.get("scale", 1.0))
        if action == "compare":
            keys = params.get("scenarios") or list(stress.SCENARIOS)
            data = stress.compare_scenarios(positions_payload, keys, sector_lookup=sector_lookup)
            return FunctionResult(code=self.code, instrument=None,
                                  data={"comparisons": data},
                                  sources=["yfinance"])
        if action == "custom":
            sc = stress.custom_scenario(
                name=params.get("name", "custom"),
                description=params.get("description", "User shock"),
                horizon_days=int(params.get("horizon_days", 30)),
                asset_class_shocks=params.get("asset_class_shocks") or {},
                sector_shocks=params.get("sector_shocks") or {},
                symbol_shocks=params.get("symbol_shocks") or {},
            )
            data = stress.apply_scenario(positions_payload, sc, sector_lookup=sector_lookup, scale=scale)
            return FunctionResult(code=self.code, instrument=None, data=data,
                                  sources=["yfinance"])
        # default: run named scenario
        key = (params.get("scenario") or params.get("key") or "GFC_2008").upper()
        sc = stress.get_scenario(key)
        if not sc:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=[f"unknown scenario {key}"])
        data = stress.apply_scenario(positions_payload, sc, sector_lookup=sector_lookup, scale=scale)
        return FunctionResult(code=self.code, instrument=None, data=data,
                              sources=["yfinance", "stress_scenarios"])

    async def _quote_many(self, symbols: list[str]) -> dict[str, float]:
        out: dict[str, float] = {}
        if not self.deps.yfinance:
            return out
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

    async def _sectors(self, symbols: list[str], lookup: dict[str, str]) -> None:
        async def _s(sym: str) -> None:
            try:
                inst = Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
                meta = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.PROFILE, instrument=inst))
                if meta and getattr(meta, "data", None):
                    sector = (meta.data or {}).get("sector")
                    if sector:
                        lookup[sym] = sector
            except Exception:
                pass
        await asyncio.gather(*(_s(s) for s in symbols))
