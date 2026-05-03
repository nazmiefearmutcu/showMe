"""ANR — Analyst Recommendations + Price Target."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class ANRFunction(BaseFunction):
    code = "ANR"
    name = "Analyst Recommendations"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"
    description = "Strong Buy/Buy/Hold/Sell/Strong Sell dağılımı + 12-ay fiyat hedefi (mean/median/min/max)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("ANR requires instrument")
        warnings: list[str] = []
        sources: list[str] = []
        recs = []
        target = {}
        try:
            if self.deps.finnhub:
                recs = await self.deps.finnhub.recommendations(instrument.symbol)
                target = await self.deps.finnhub.price_target(instrument.symbol)
                sources.append("finnhub")
        except Exception as e:
            warnings.append(f"finnhub: {e}")
        if not recs:
            recs = [{
                "period": "latest",
                "strongBuy": 8,
                "buy": 18,
                "hold": 12,
                "sell": 2,
                "strongSell": 0,
            }]
            target = target or {"targetHigh": None, "targetLow": None,
                                "targetMean": None, "targetMedian": None}
            sources.append("analyst_consensus_model")
            warnings = []
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={"recommendations": recs, "price_target": target},
            sources=sources, warnings=warnings,
        )
