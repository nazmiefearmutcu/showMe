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
    # Reference-only names added for FLDS#2. No provider is mapped to them.
    "eps_ttm": "Earnings per share, trailing twelve months",
    "eps_fwd": "Earnings per share, forward estimate",
    "book_value_per_share": "Book value per share",
    "ebitda": "EBITDA (earnings before interest, taxes, D&A)",
    "gross_profit": "Gross profit",
    "free_cash_flow": "Free cash flow",
    "dividend_per_share": "Dividends declared per share",
    "roe": "Return on equity",
    "gross_margin": "Gross margin",
    "debt_to_equity": "Total debt to total equity",
    "current_ratio": "Current assets to current liabilities",
    "coupon": "Annual coupon rate",
    "yield_to_worst": "Yield-to-worst",
    "implied_vol": "Implied volatility",
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
    "eps_ttm": "valuation",
    "eps_fwd": "valuation",
    "book_value_per_share": "valuation",
    "ebitda": "statement",
    "gross_profit": "statement",
    "free_cash_flow": "cash_flow",
    "dividend_per_share": "valuation",
    "roe": "statement",
    "gross_margin": "statement",
    "debt_to_equity": "statement",
    "current_ratio": "statement",
    "coupon": "fixed_income",
    "yield_to_worst": "fixed_income",
    "implied_vol": "options",
}

# Mnemonic: a ShowMe alias for recognition, typed like a terminal field code.
# It is NOT a vendor field identifier and implies no feed or coverage.
_MNEMONICS = {
    "price": "PX_LAST",
    "open": "PX_OPEN",
    "high": "PX_HIGH",
    "low": "PX_LOW",
    "close": "PX_CLOSE",
    "volume": "PX_VOLUME",
    "market_cap": "MKT_CAP",
    "pe": "PE_RATIO",
    "fwd_pe": "FWD_PE_RATIO",
    "pb": "PX_TO_BOOK",
    "ps": "PX_TO_SALES",
    "ev_ebitda": "EV_TO_EBITDA",
    "div_yield": "DIV_YIELD",
    "beta": "BETA",
    "shares_outstanding": "SHARES_OUT",
    "shares_float": "SHARES_FLOAT",
    "revenue": "REVENUE",
    "net_income": "NET_INCOME",
    "operating_income": "OPER_INCOME",
    "total_assets": "TOTAL_ASSETS",
    "total_liabilities": "TOTAL_LIABILITIES",
    "total_equity": "TOTAL_EQUITY",
    "cfo": "CFO",
    "cfi": "CFI",
    "cff": "CFF",
    "capex": "CAPEX",
    "ytm": "YTM",
    "duration": "DURATION",
    "modified_duration": "MOD_DURATION",
    "convexity": "CONVEXITY",
    "iv_rank": "IV_RANK",
    "iv_percentile": "IV_PERCENTILE",
    "rsi": "RSI_14",
    "macd": "MACD_LINE",
    "atr": "ATR_14",
    "eps_ttm": "EPS_TTM",
    "eps_fwd": "EPS_FWD",
    "book_value_per_share": "BVPS",
    "ebitda": "EBITDA",
    "gross_profit": "GROSS_PROFIT",
    "free_cash_flow": "FREE_CASH_FLOW",
    "dividend_per_share": "DPS",
    "roe": "ROE",
    "gross_margin": "GROSS_MARGIN",
    "debt_to_equity": "DEBT_TO_EQUITY",
    "current_ratio": "CURRENT_RATIO",
    "coupon": "COUPON",
    "yield_to_worst": "YTW",
    "implied_vol": "IMPLIED_VOL",
}

# Unit of the value a field carries, so a consumer never guesses scale.
# Percent fields are stated in percent units (4.2 means 4.2%), not fractions.
_UNITS = {
    "price": "currency",
    "open": "currency",
    "high": "currency",
    "low": "currency",
    "close": "currency",
    "volume": "shares",
    "market_cap": "currency",
    "pe": "ratio (x)",
    "fwd_pe": "ratio (x)",
    "pb": "ratio (x)",
    "ps": "ratio (x)",
    "ev_ebitda": "ratio (x)",
    "div_yield": "percent (%)",
    "beta": "ratio",
    "shares_outstanding": "shares",
    "shares_float": "shares",
    "revenue": "currency",
    "net_income": "currency",
    "operating_income": "currency",
    "total_assets": "currency",
    "total_liabilities": "currency",
    "total_equity": "currency",
    "cfo": "currency",
    "cfi": "currency",
    "cff": "currency",
    "capex": "currency",
    "ytm": "percent (%)",
    "duration": "years",
    "modified_duration": "years",
    "convexity": "years squared",
    "iv_rank": "rank (0-100)",
    "iv_percentile": "rank (0-100)",
    "rsi": "index (0-100)",
    "macd": "price units",
    "atr": "price units",
    "eps_ttm": "currency per share",
    "eps_fwd": "currency per share",
    "book_value_per_share": "currency per share",
    "ebitda": "currency",
    "gross_profit": "currency",
    "free_cash_flow": "currency",
    "dividend_per_share": "currency per share",
    "roe": "percent (%)",
    "gross_margin": "percent (%)",
    "debt_to_equity": "ratio (x)",
    "current_ratio": "ratio (x)",
    "coupon": "percent (%)",
    "yield_to_worst": "percent (%)",
    "implied_vol": "percent (%)",
}

# BQL get() returns only these fields: live mode fetches OHLCV rows from
# yfinance (bql.py). Every other catalog name is a reference entry with no
# provider mapping here, so it is flagged bql_get=False.
_BQL_GET_FIELDS = frozenset({"price", "open", "high", "low", "close", "volume"})

# Provider mapping per catalog field. Only the OHLCV fields have a provider in
# ShowMe (yfinance, through BQL live mode). Every other name has no provider
# here and is reference-only: no value is returned for it anywhere in FLDS.
_LIVE_PROVIDER = "yfinance"
_AVAILABILITY_LIVE = "bql_live_ohlcv"
_AVAILABILITY_REFERENCE = "reference_only"


def _provider_for(field: str) -> tuple[str | None, str]:
    if field in _BQL_GET_FIELDS:
        return _LIVE_PROVIDER, _AVAILABILITY_LIVE
    return None, _AVAILABILITY_REFERENCE

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


def _match_rank(field: str, mnemonic: str, description: str, category: str, prefix: str) -> int | None:
    """0 = field name or mnemonic starts with the query, 1 = a name, mnemonic,
    description or category word starts with it (or a multi-word phrase
    occurs), None = no match.

    Plain substring matching is deliberately not used: "pe" must not match
    "open" or "operating_income" just because "pe" sits inside the word.
    """
    if not prefix:
        return 0
    if field.startswith(prefix) or mnemonic.lower().startswith(prefix):
        return 0
    if not prefix.isalnum():
        # Multi-word or punctuated query (for example "session open", "p/e"):
        # treat as a phrase, not a word prefix.
        return 1 if prefix in f"{field} {mnemonic} {description} {category}".lower() else None
    words = _WORD_RE.findall(f"{field} {mnemonic} {description} {category}".lower())
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
            mnemonic = _MNEMONICS[field]
            rank = _match_rank(field, mnemonic, description, category, prefix)
            if rank is None:
                continue
            provider, availability = _provider_for(field)
            ranked.append((rank, {
                "field": field,
                "mnemonic": mnemonic,
                "category": category,
                "description": description,
                "unit": _UNITS[field],
                "example": _EXAMPLES.get(category, _DEFAULT_EXAMPLE),
                "bql_get": field in _BQL_GET_FIELDS,
                "provider": provider,
                "availability": availability,
            }))
        # Name or mnemonic prefix matches first; the stable sort keeps catalog order within a rank.
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
                    "FLDS searches the local ShowMe field catalog. A query matches a field whose name or "
                    "mnemonic starts with it, or a word in its name, mnemonic, description or category that "
                    "starts with it; a multi-word query is a phrase match. Name-prefix matches are listed first. "
                    "Each row gives the field, a ShowMe mnemonic alias (not a vendor field ID), the unit of its "
                    "value, and its availability. The catalog is a reference index of field names: BQL get() "
                    "returns only the OHLCV fields flagged bql_get=true, and the other names have no provider "
                    "mapping here and carry no value. It is not a live market-data request."
                ),
                "field_dictionary": {
                    "field": "Canonical catalog field name. Not every name is a BQL get() field; see bql_get.",
                    "mnemonic": "Terminal-style ShowMe alias for the field (for example PX_LAST). An alias for lookup, not a vendor field ID.",
                    "category": "Market, valuation, statement, technical, option, risk, or fixed-income grouping.",
                    "description": "Plain-language meaning of the field.",
                    "unit": "Unit of the value (currency, shares, ratio (x), percent (%), years, index (0-100), and so on). Percent is in percent units, not fractions.",
                    "bql_get": "True only when BQL get() returns this field (live mode: OHLCV only).",
                    "provider": "Data provider that returns this field in ShowMe (yfinance for OHLCV); null when none is mapped.",
                    "availability": "bql_live_ohlcv when BQL live mode returns it; reference_only when no provider here returns it.",
                    "example": "One concrete place the field can be used, naming a function that exists in the index.",
                },
            },
            sources=["showme_field_catalog"],
        )
