"""FLDS — Field Lookup (Excel autocomplete)."""

from __future__ import annotations

import re
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


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

# BQL get() returns only these fields: live mode fetches OHLCV rows from
# yfinance (bql.py). Every other catalog name is a reference entry with no
# provider mapping here, so it is flagged bql_get=False.
_BQL_GET_FIELDS = frozenset({"price", "open", "high", "low", "close", "volume"})

# Examples name only functions that exist in the function index (EQS, SRCH,
# MLSIG, BQL). MLSIG's model features are rsi_14 / macd_line / atr_14.
_EXAMPLES = {
    "market": "BQL get(close, volume) for(['AAPL']) by(date)",
    "valuation": "EQS query: pe < 30 AND market_cap > 50000000000",
    "fixed_income": "SRCH query: ytm >= 4 AND duration <= 10",
    "technical": "MLSIG model features: rsi_14, macd_line, atr_14 (MLSIG names, not rsi/macd/atr).",
}
_DEFAULT_EXAMPLE = "Catalog reference name; BQL get() does not return it (bql_get is false)."

_WORD_RE = re.compile(r"[a-z0-9]+")


def _match_rank(field: str, description: str, category: str, prefix: str) -> int | None:
    """0 = field name starts with the query, 1 = a name/description/category
    word starts with it (or a multi-word phrase occurs), None = no match.

    Plain substring matching is deliberately not used: "pe" must not match
    "open" or "operating_income" just because "pe" sits inside the word.
    """
    if not prefix:
        return 0
    if field.startswith(prefix):
        return 0
    if not prefix.isalnum():
        # Multi-word or punctuated query (for example "session open", "p/e"):
        # treat as a phrase, not a word prefix.
        return 1 if prefix in f"{field} {description} {category}".lower() else None
    words = _WORD_RE.findall(f"{field} {description} {category}".lower())
    return 1 if any(word.startswith(prefix) for word in words) else None


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
        ranked: list[tuple[int, dict[str, Any]]] = []
        for field, description in _FIELDS.items():
            category = _CATEGORIES.get(field, "general")
            rank = _match_rank(field, description, category, prefix)
            if rank is None:
                continue
            ranked.append((rank, {
                "field": field,
                "category": category,
                "description": description,
                "example": _EXAMPLES.get(category, _DEFAULT_EXAMPLE),
                "bql_get": field in _BQL_GET_FIELDS,
            }))
        # Name-prefix matches first; the stable sort keeps catalog order within a rank.
        ranked.sort(key=lambda pair: pair[0])
        matches = [row for _, row in ranked]
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
                    "FLDS searches the local ShowMe field catalog. A query matches a field whose name starts "
                    "with it, or a word in its name, description or category that starts with it; a multi-word "
                    "query is a phrase match. Name-prefix matches are listed first. The catalog is a reference "
                    "index of field names: BQL get() returns only the OHLCV fields flagged bql_get=true, and the "
                    "other names have no provider mapping here. It is not a live market-data request."
                ),
                "field_dictionary": {
                    "field": "Canonical catalog field name. Not every name is a BQL get() field; see bql_get.",
                    "category": "Market, valuation, statement, technical, option, risk, or fixed-income grouping.",
                    "description": "Plain-language meaning of the field.",
                    "bql_get": "True only when BQL get() returns this field (live mode: OHLCV only).",
                    "example": "One concrete place the field can be used, naming a function that exists in the index.",
                },
            },
            sources=["showme_field_catalog"],
        )
