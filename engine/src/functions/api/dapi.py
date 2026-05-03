"""DAPI — Data API for Excel/external clients (REST surface specification).

This file declares the field contract; FastAPI routes in dashboard/app.py
mount the actual /api/v1/* endpoints. xlwings UDFs in excel/showme_addin.py
hit those endpoints.
"""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


@FunctionRegistry.register
class DAPIFunction(BaseFunction):
    code = "DAPI"
    name = "ShowMe Data API"
    category = "api"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        return FunctionResult(
            code=self.code, instrument=None,
            data={"endpoints": [
                "GET  /api/v1/quote/{symbol}",
                "GET  /api/v1/history/{symbol}?interval=1d&start=...&end=...",
                "GET  /api/v1/fundamentals/{symbol}?period=quarterly",
                "GET  /api/v1/news?topic=…",
                "POST /api/v1/bql  (body: { query: '…' })",
                "GET  /api/v1/portfolio",
                "POST /api/v1/order  (body: { symbol, side, qty, type, … })",
                "GET  /api/v1/calendar?country=US",
            ]},
        )
