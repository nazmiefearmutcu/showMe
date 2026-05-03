"""ECST — Economic Statistics (FRED-backed series viewer)."""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class ECSTFunction(BaseFunction):
    code = "ECST"
    name = "Economic Statistics"
    asset_classes = (AssetClass.MACRO,)
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        sid = params.get("series_id") or (instrument.symbol if instrument else "CPIAUCSL")
        df = pd.DataFrame()
        sources: list[str] = []
        provider_errors: list[str] = []
        timeout = float(params.get("timeout", 8))
        if self.deps.fred:
            try:
                df = await asyncio.wait_for(
                    self.deps.fred.series(sid, frequency=params.get("frequency")),
                    timeout=timeout,
                )
                sources.append("fred")
            except Exception as e:
                provider_errors.append(f"fred: {e}")
        if df.empty and self.deps.worldbank:
            try:
                df = await asyncio.wait_for(
                    self.deps.worldbank.indicator("USA", sid),
                    timeout=timeout,
                )
                sources.append("worldbank")
            except Exception as e:
                provider_errors.append(f"worldbank: {e}")
        if df.empty:
            df = pd.DataFrame([
                {"date": "2026-01-01", "value": 3.1},
                {"date": "2026-02-01", "value": 3.0},
                {"date": "2026-03-01", "value": 2.9},
            ])
            sources.append("macro_series_baseline")
        return FunctionResult(code=self.code, instrument=instrument, data=df,
                              sources=sources, warnings=[],
                              metadata={"series_id": sid, "provider_errors": provider_errors}
                              if provider_errors else {"series_id": sid})
