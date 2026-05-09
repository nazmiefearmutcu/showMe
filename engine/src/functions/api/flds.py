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

_CATEGORIES = {
    "price": "market",
    "open": "market",
    "high": "market",
    "low": "market",
    "close": "market",
    "volume": "market",
    "market_cap": "fundamental",
    "pe": "valuation",
    "fwd_pe": "valuation",
    "pb": "valuation",
    "ps": "valuation",
    "ev_ebitda": "valuation",
    "div_yield": "valuation",
    "beta": "risk",
    "shares_outstanding": "fundamental",
    "shares_float": "fundamental",
    "revenue": "statement",
    "net_income": "statement",
    "operating_income": "statement",
    "total_assets": "statement",
    "total_liabilities": "statement",
    "total_equity": "statement",
    "cfo": "cash_flow",
    "cfi": "cash_flow",
    "cff": "cash_flow",
    "capex": "cash_flow",
    "ytm": "fixed_income",
    "duration": "fixed_income",
    "modified_duration": "fixed_income",
    "convexity": "fixed_income",
    "iv_rank": "options",
    "iv_percentile": "options",
    "rsi": "technical",
    "macd": "technical",
    "atr": "technical",
}

_EXAMPLES = {
    "market": "get(close, volume) for(['AAPL']) by(date)",
    "valuation": "EQS query: pe < 30 AND market_cap > 50000000000",
    "fixed_income": "SRCH query: ytm >= 4 AND duration <= 10",
    "technical": "MLSIG and screen functions use rsi/macd/atr as model features.",
}


@FunctionRegistry.register
class FLDSFunction(BaseFunction):
    code = "FLDS"
    name = "Field Lookup"
    category = "api"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        prefix = str(params.get("prefix") or params.get("query") or "").strip().lower()
        try:
            limit = max(1, min(int(params.get("limit") or 50), 100))
        except Exception:
            limit = 50
        matches: list[dict[str, Any]] = []
        for field, description in _FIELDS.items():
            category = _CATEGORIES.get(field, "general")
            haystack = f"{field} {description} {category}".lower()
            if prefix and prefix not in haystack and not field.startswith(prefix):
                continue
            matches.append({
                "field": field,
                "category": category,
                "description": description,
                "example": _EXAMPLES.get(category, "Use in BQL get(...), screen DSL filters, or Advanced params."),
            })
        rows = matches[:limit]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "rows": rows,
                "summary": {
                    "query": prefix or "all",
                    "matched": len(matches),
                    "shown": len(rows),
                    "catalog_fields": len(_FIELDS),
                },
                "methodology": (
                    "FLDS searches the local ShowMe field catalog by field name, description, and category. "
                    "The catalog maps user-visible field names to supported function contexts; it is not a live market-data request."
                ),
                "field_dictionary": {
                    "field": "Canonical field name accepted by BQL, screeners, or analytics params.",
                    "category": "Market, valuation, statement, technical, option, risk, or fixed-income grouping.",
                    "description": "Plain-language meaning of the field.",
                    "example": "One concrete place the field can be used.",
                },
            },
            sources=["showme_field_catalog"],
        )
