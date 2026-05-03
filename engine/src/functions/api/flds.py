"""FLDS — Field Lookup (Excel autocomplete)."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


_FIELDS = {
    "price": "Last traded price",
    "open": "Session open",
    "high": "Session high",
    "low": "Session low",
    "close": "Session close",
    "volume": "Session volume",
    "market_cap": "Market capitalisation",
    "pe": "Trailing P/E",
    "fwd_pe": "Forward P/E",
    "pb": "Price-to-Book",
    "ps": "Price-to-Sales (TTM)",
    "ev_ebitda": "Enterprise value / EBITDA",
    "div_yield": "Dividend yield",
    "beta": "CAPM beta vs S&P 500",
    "shares_outstanding": "Shares outstanding",
    "shares_float": "Free float shares",
    "revenue": "Total revenue",
    "net_income": "Net income",
    "operating_income": "Operating income",
    "total_assets": "Total assets",
    "total_liabilities": "Total liabilities",
    "total_equity": "Total stockholders' equity",
    "cfo": "Operating cash flow",
    "cfi": "Investing cash flow",
    "cff": "Financing cash flow",
    "capex": "Capital expenditures",
    "ytm": "Yield-to-maturity",
    "duration": "Macaulay duration",
    "modified_duration": "Modified duration",
    "convexity": "Convexity",
    "iv_rank": "Implied vol rank",
    "iv_percentile": "Implied vol percentile",
    "rsi": "Relative strength index (14)",
    "macd": "MACD signal line",
    "atr": "Average true range (14)",
}


@FunctionRegistry.register
class FLDSFunction(BaseFunction):
    code = "FLDS"
    name = "Field Lookup"
    category = "api"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        prefix = (params.get("prefix") or "").lower()
        out = {k: v for k, v in _FIELDS.items() if k.startswith(prefix)} if prefix else _FIELDS
        return FunctionResult(code=self.code, instrument=None, data=out)
