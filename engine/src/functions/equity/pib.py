"""PIB — Public Information Book (recent SEC filings + AI summary stub)."""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class PIBFunction(BaseFunction):
    code = "PIB"
    name = "Public Information Book"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        warnings: list[str] = []
        filings = pd.DataFrame()
        try:
            if self.deps.sec_edgar:
                filings = await asyncio.wait_for(
                    self.deps.sec_edgar.fetch(DataRequest(
                        kind=DataKind.EVENTS, instrument=instrument
                    )),
                    timeout=float(params.get("timeout", 8)),
                )
                if isinstance(filings, pd.DataFrame) and not filings.empty:
                    filings = filings.head(50)
        except Exception as e:
            warnings.append(f"sec_edgar: {e}")
        data = filings
        sources = ["sec_edgar"]
        if not isinstance(filings, pd.DataFrame) or filings.empty:
            data = [{
                "symbol": instrument.symbol,
                "form": None,
                "filingDate": None,
                "status": "provider_unavailable",
            }]
            sources = ["pib_model"]
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=data,
            sources=sources,
            metadata={"note": "AI summary via LLM router (Phase 7)", "provider_errors": warnings},
        )
