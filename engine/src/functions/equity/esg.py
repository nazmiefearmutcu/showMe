"""ESG — Environment / Social / Governance scoring."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class ESGFunction(BaseFunction):
    code = "ESG"
    name = "ESG Scores"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        warnings: list[str] = []
        scores = {}
        try:
            if self.deps.yfinance:
                import yfinance as yf
                timeout = float(params.get("timeout", 8))
                t = await asyncio.wait_for(asyncio.to_thread(yf.Ticker, instrument.symbol), timeout=timeout)
                sus = await asyncio.wait_for(
                    asyncio.to_thread(getattr, t, "sustainability", None),
                    timeout=timeout,
                )
                if sus is not None:
                    scores = sus.to_dict() if hasattr(sus, "to_dict") else dict(sus)
        except Exception as e:
            warnings.append(f"yfinance esg: {e}")
        if not scores:
            scores = {
                "totalEsg": None,
                "environmentScore": None,
                "socialScore": None,
                "governanceScore": None,
                "controversyLevel": None,
                "status": "no_vendor_score_available",
            }
            warnings = []
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=scores,
            sources=["yfinance"] if not warnings else ["esg_model"],
            metadata={"provider_errors": warnings} if warnings else {},
        )
