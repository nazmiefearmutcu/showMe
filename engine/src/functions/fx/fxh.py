"""FXH — FX hedging (forward overlay) calculator."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.services.fx_hedge import FXExposure, forward_rate, hedge_book, hedge_one


@FunctionRegistry.register
class FXHFunction(BaseFunction):
    code = "FXH"
    name = "FX Hedge"
    asset_classes = (AssetClass.FX,)
    category = "fx"
    description = "Forward-rate overlay calculator for foreign-currency exposure."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = (params.get("action") or "calc").lower()
        home = (params.get("home_currency") or "USD").upper()
        days = int(params.get("days", 90))
        ratio = float(params.get("hedge_ratio", 1.0))
        shock = float(params.get("usd_shock_pct", 0.05))
        # explicit exposures override portfolio-derived
        exposures = params.get("exposures")
        if not exposures:
            exposures = await self._derive_exposures(home)
        # Resolve spot rates if missing
        await self._fill_spots(exposures, home)
        objs = [
            FXExposure(
                currency=e["currency"].upper(), home_currency=home,
                notional=float(e["notional"]),
                spot_rate=float(e.get("spot_rate") or 1.0),
                base_rate=float(e.get("base_rate", 0.04)),
                home_rate=float(e.get("home_rate", 0.045)),
            ) for e in exposures
        ]
        if action == "forward":
            return FunctionResult(
                code=self.code, instrument=None,
                data={"forwards": [{
                    "pair": f"{e.currency}/{home}",
                    "spot": e.spot_rate,
                    "forward": forward_rate(spot=e.spot_rate,
                                            home_rate=e.home_rate,
                                            base_rate=e.base_rate, days=days),
                    "days": days,
                } for e in objs]},
            )
        out = hedge_book(objs, hedge_ratio=ratio, days=days, usd_shock_pct=shock)
        return FunctionResult(code=self.code, instrument=instrument,
                              data=out, sources=["yfinance", "ecb"])

    async def _derive_exposures(self, home: str) -> list[dict[str, Any]]:
        """Group portfolio positions by foreign currency."""
        from src.portfolio.state import PortfolioState
        ps = PortfolioState()
        ps.import_legacy_crypto()
        by_ccy: dict[str, float] = {}
        for p in ps.positions:
            ccy = (p.currency or home).upper()
            if ccy == home:
                continue
            by_ccy[ccy] = by_ccy.get(ccy, 0.0) + p.quantity * p.avg_cost
        return [{"currency": c, "notional": n} for c, n in by_ccy.items()]

    async def _fill_spots(self, exposures: list[dict[str, Any]], home: str) -> None:
        if not self.deps.yfinance:
            return
        async def _q(e: dict[str, Any]) -> None:
            if e.get("spot_rate"):
                return
            pair = f"{e['currency']}{home}=X"
            try:
                inst = Instrument(symbol=pair, asset_class=AssetClass.FX)
                quote = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.QUOTE, instrument=inst))
                e["spot_rate"] = float(getattr(quote, "last", 0) or 0) or 1.0
            except Exception:
                e["spot_rate"] = 1.0
        await asyncio.gather(*(_q(e) for e in exposures))
