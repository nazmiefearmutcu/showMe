"""SRCH, FSRC, CSRC, SECF, MOST, WEI — screen suite."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class SRCHFunction(BaseFunction):
    """SRCH — Bond Screener (alias of EQS pattern)."""
    code = "SRCH"
    name = "Bond Screener"
    asset_classes = (AssetClass.BOND,)
    category = "screen"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        query = str(params.get("query") or "yield >= 4 AND duration <= 10")
        universe = _symbol_filter(params.get("universe"))
        rows = _filter_universe(_bond_reference_rows(), universe)
        return _screen_result(
            self.code,
            rows,
            query=query,
            limit=_int_param(params, "limit", 50),
            sources=["showme_bond_reference_universe"],
            field_dictionary=_BOND_FIELDS,
        )


@FunctionRegistry.register
class FSRCFunction(BaseFunction):
    """FSRC — Fund Screener."""
    code = "FSRC"
    name = "Fund Screener"
    asset_classes = (AssetClass.FUND, AssetClass.ETF)
    category = "screen"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        query = str(params.get("query") or "expenseRatio < 0.01 AND aum_usd > 10000000000")
        universe = _symbol_filter(params.get("universe"))
        rows = _filter_universe(_fund_reference_rows(), universe)
        live = _truthy(params.get("live_screen") or params.get("live"))
        warnings: list[str] = []
        sources = ["showme_fund_reference_universe"]
        if live and self.deps.yfinance:
            quotes, warnings = await _quote_rows(
                self.deps.yfinance,
                [str(row["symbol"]) for row in rows],
                asset_class=AssetClass.ETF,
                timeout=_float_param(params, "quote_timeout", 3.0),
                screen_timeout=_float_param(params, "screen_timeout", 5.0),
            )
            if quotes:
                rows = _merge_quote_rows(rows, quotes)
                sources = ["yfinance", "showme_fund_reference_universe"]
        return _screen_result(
            self.code,
            rows,
            query=query,
            limit=_int_param(params, "limit", 50),
            sources=sources,
            field_dictionary=_FUND_FIELDS,
            warnings=warnings,
        )


@FunctionRegistry.register
class CSRCFunction(BaseFunction):
    """CSRC — Commodity Screener."""
    code = "CSRC"
    name = "Commodity Screener"
    asset_classes = (AssetClass.COMMODITY,)
    category = "screen"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        query = str(params.get("query") or 'sector = "Energy"')
        universe = _symbol_filter(params.get("universe"))
        rows = _filter_universe(_commodity_reference_rows(), universe)
        live = _truthy(params.get("live_screen") or params.get("live"))
        warnings: list[str] = []
        sources = ["showme_commodity_reference_universe"]
        if live and self.deps.yfinance:
            quotes, warnings = await _quote_rows(
                self.deps.yfinance,
                [str(row["symbol"]) for row in rows],
                asset_class=AssetClass.COMMODITY,
                timeout=_float_param(params, "quote_timeout", 3.0),
                screen_timeout=_float_param(params, "screen_timeout", 5.0),
            )
            if quotes:
                rows = _merge_quote_rows(rows, quotes)
                sources = ["yfinance", "showme_commodity_reference_universe"]
        return _screen_result(
            self.code,
            rows,
            query=query,
            limit=_int_param(params, "limit", 50),
            sources=sources,
            field_dictionary=_COMMODITY_FIELDS,
            warnings=warnings,
        )


@FunctionRegistry.register
class SECFFunction(BaseFunction):
    """SECF — Security Finder (NL → query)."""
    code = "SECF"
    name = "Security Finder"
    category = "screen"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        query = str(params.get("query") or "technology")
        universe = _symbol_filter(params.get("universe"))
        rows = _filter_universe(_security_reference_rows(), universe)
        if _looks_like_dsl(query):
            return _screen_result(
                self.code,
                rows,
                query=_rewrite_screen_query(query),
                limit=_int_param(params, "limit", 50),
                sources=["showme_security_master"],
                field_dictionary=_SECURITY_FIELDS,
            )
        filtered = _security_text_search(rows, query)
        limit = _int_param(params, "limit", 50)
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok" if filtered else "empty",
                "query": query,
                "match_mode": "text_search",
                "rows": filtered[:limit],
                "field_dictionary": _SECURITY_FIELDS,
                "scanned": len(rows),
                "matched": len(filtered),
                "next_actions": [] if filtered else [
                    "Try a broader symbol, company name, asset class, or tag.",
                    "Examples: technology, treasury, crude, bitcoin, SPY.",
                ],
            },
            metadata={"query": query, "matched": len(filtered), "scanned": len(rows), "limit": limit},
            sources=["showme_security_master"],
        )


@FunctionRegistry.register
class MOSTFunction(BaseFunction):
    """MOST — Most Active (volume + |return| + range)."""
    code = "MOST"
    name = "Most Active"
    category = "screen"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        universe_filter = _symbol_filter(params.get("universe"))
        rows = _filter_universe(_most_active_reference_rows(), universe_filter)
        asset_filter = _normalize_most_asset_class(params.get("asset_class"))
        if asset_filter:
            rows = [
                row for row in rows
                if _normalize_most_asset_class(row.get("asset_class")) == asset_filter
            ]
        limit = _int_param(params, "limit", 50)
        sort_key = str(params.get("sort") or "dollar_volume").strip().lower()
        live = _truthy(params.get("live_screen") or params.get("live"))
        universe = [str(row["symbol"]) for row in rows]
        if not rows:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_most_active_payload(
                    [],
                    universe,
                    limit=limit,
                    asset_class=asset_filter or "all",
                    sort=sort_key,
                    live=False,
                    status="empty",
                    reason="No reference symbols matched the selected asset class or universe.",
                ),
                metadata={"live": False, "universe_size": 0, "limit": limit, "asset_class": asset_filter or "all"},
                sources=["showme_most_active_universe"],
            )
        if live and self.deps.yfinance:
            quote_rows, warnings = await _quote_rows(
                self.deps.yfinance,
                universe,
                timeout=_float_param(params, "quote_timeout", 4.0),
                screen_timeout=_float_param(params, "screen_timeout", 6.0),
            )
            if quote_rows:
                live_rows = _merge_live_most_rows(rows, quote_rows)
                live_rows = _rank_most_active_rows(live_rows, sort_key)[:limit]
                missing = len(rows) - len(live_rows)
                if missing > 0:
                    warnings = [*warnings, f"{missing} reference symbol(s) had no usable live quote"]
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data=_most_active_payload(
                        live_rows,
                        universe,
                        limit=limit,
                        asset_class=asset_filter or "all",
                        sort=sort_key,
                        live=True,
                        status="ok",
                        reason=None,
                    ),
                    metadata={
                        "live": True,
                        "universe_size": len(universe),
                        "live_rows": len(live_rows),
                        "limit": limit,
                        "asset_class": asset_filter or "all",
                        "sort": sort_key,
                    },
                    sources=["yfinance", "showme_most_active_universe"],
                    warnings=warnings[:4],
                )
        if live:
            warnings = ["market data provider did not return a usable most-active snapshot within the latency budget"]
            reason = "Live quote provider returned no usable rows."
            status = "provider_unavailable"
            data_rows: list[dict[str, Any]] = []
        else:
            warnings = []
            reason = None
            status = "reference"
            data_rows = _rank_most_active_rows(rows, sort_key)[:limit]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=_most_active_payload(
                data_rows,
                universe,
                limit=limit,
                asset_class=asset_filter or "all",
                sort=sort_key,
                live=False,
                status=status,
                reason=reason,
            ),
            metadata={"live": False, "universe_size": len(universe), "limit": limit, "asset_class": asset_filter or "all", "sort": sort_key},
            sources=["showme_most_active_universe"],
            warnings=warnings,
        )


@FunctionRegistry.register
class WEIFunction(BaseFunction):
    """WEI — World Equity Indices."""
    code = "WEI"
    name = "World Equity Indices"
    category = "screen"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        indices = ["^GSPC", "^DJI", "^IXIC", "^RUT", "^FTSE", "^GDAXI", "^FCHI",
                   "^N225", "^HSI", "^STOXX50E", "XU100.IS"]
        live = _truthy(params.get("live_screen") or params.get("live"))
        if live and self.deps.yfinance:
            rows, warnings = await _quote_rows(
                self.deps.yfinance,
                indices,
                asset_class=AssetClass.INDEX,
                timeout=_float_param(params, "quote_timeout", 4.0),
                screen_timeout=_float_param(params, "screen_timeout", 5.0),
            )
            if rows:
                rows = [_enrich_world_index_row(row) for row in rows]
                # Session-14 contract fix: WEI used to return `data=rows`
                # (list) on the live path and `data={status, rows, ...}`
                # (dict) on every fallback. UI panes that expected a stable
                # shape silently broke. Wrap live rows in the same dict
                # envelope used everywhere else.
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        "status": "ok",
                        "rows": rows,
                        "universe_size": len(indices),
                        "source_mode": "yfinance_live",
                    },
                    metadata={"live": True, "universe_size": len(indices)},
                    sources=["yfinance"],
                    warnings=warnings,
                )
            fallback_rows = _world_index_template()
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "World index quote provider returned no usable live rows.",
                    "rows": fallback_rows,
                    "next_actions": [
                        "Retry WEI after the public quote provider recovers.",
                        "Rows shown are a deterministic world-index model, not live quotes.",
                    ],
                },
                metadata={
                    "live": True,
                    "fallback": True,
                    "degraded": True,
                    "universe_size": len(indices),
                    "provider_errors": warnings or ["yfinance world index quotes unavailable"],
                },
                sources=["yfinance", "world_index_model"],
                warnings=warnings,
            )
        warnings = [] if not live else ["market data provider did not return world-index quotes within the latency budget"]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok" if not live else "provider_unavailable",
                "rows": _world_index_template(),
                "universe_size": len(indices),
                "source_mode": "world_index_template",
            },
            metadata={"live": False, "universe_size": len(indices)},
            sources=["showme_local_baseline"],
            warnings=warnings,
        )


_COMMODITY_FIELDS = [
    {"field": "symbol", "meaning": "Yahoo futures ticker used for quote lookup."},
    {"field": "sector", "meaning": "Commodity complex such as Energy, Metals, or Agriculture."},
    {"field": "last", "meaning": "Latest available futures price when live quotes are available."},
    {"field": "change_pct", "meaning": "Percent move versus prior close when live quotes are available."},
    {"field": "volume", "meaning": "Latest session volume from the quote provider when available."},
    {"field": "contract_unit", "meaning": "Contract unit used to understand scale."},
]

_FUND_FIELDS = [
    {"field": "symbol", "meaning": "ETF or fund ticker."},
    {"field": "category", "meaning": "Fund exposure bucket."},
    {"field": "aum_usd", "meaning": "Assets under management in US dollars."},
    {"field": "expenseRatio", "meaning": "Annual expense ratio as a decimal."},
    {"field": "ytd_return_pct", "meaning": "Reference year-to-date return in percent."},
    {"field": "last", "meaning": "Latest available traded price when live quotes are available."},
]

_BOND_FIELDS = [
    {"field": "symbol", "meaning": "Curve or bond proxy identifier."},
    {"field": "issuer", "meaning": "Issuer or sovereign curve."},
    {"field": "yield", "meaning": "Yield to maturity or benchmark yield in percent."},
    {"field": "duration", "meaning": "Approximate interest-rate duration in years."},
    {"field": "rating", "meaning": "Reference credit rating."},
    {"field": "maturity", "meaning": "Maturity bucket or final maturity date."},
]

_SECURITY_FIELDS = [
    {"field": "symbol", "meaning": "Tradable or reference symbol."},
    {"field": "name", "meaning": "Human-readable security name."},
    {"field": "asset_class", "meaning": "Equity, ETF, crypto, FX, commodity, bond, or index."},
    {"field": "exchange", "meaning": "Primary venue or reference source."},
    {"field": "tags", "meaning": "Searchable descriptors used by the finder."},
]

_MOST_FIELDS = [
    {"field": "symbol", "meaning": "Ticker or pair returned by the live quote provider."},
    {"field": "name", "meaning": "Human-readable security or pair name from ShowMe's reference universe."},
    {"field": "asset_class", "meaning": "Market bucket used by the All/Equities/Crypto/FX tabs."},
    {"field": "last", "meaning": "Latest provider price."},
    {"field": "change_pct", "meaning": "Percent move versus previous close when available."},
    {"field": "volume", "meaning": "Latest session or 24-hour volume from the quote provider."},
    {"field": "dollar_volume", "meaning": "Approximate traded notional: latest price multiplied by volume."},
    {"field": "quote_state", "meaning": "live when provider data was returned; reference only in deterministic non-live mode."},
]


def _supported_screen_columns(
    field_dictionary: list[dict[str, str]],
    rows: list[dict[str, Any]],
) -> set[str]:
    supported = {str(entry.get("field") or "").strip() for entry in field_dictionary if entry.get("field")}
    for row in rows[:50]:
        supported.update(str(key) for key in row.keys())
    return {column for column in supported if column}


def _extract_predicate_columns(rewritten: str) -> list[str]:
    columns: list[str] = []
    for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:<=|>=|==|!=|<|>|=|\sin\s)", rewritten, flags=re.I):
        token = match.group(1)
        if token.upper() in {"AND", "OR", "NOT", "IN", "TRUE", "FALSE"}:
            continue
        columns.append(token)
    return columns


def _screen_result(
    code: str,
    rows: list[dict[str, Any]],
    *,
    query: str,
    limit: int,
    sources: list[str],
    field_dictionary: list[dict[str, str]],
    warnings: list[str] | None = None,
) -> FunctionResult:
    rewritten = _rewrite_screen_query(query)
    scanned = len(rows)
    parse_error: str | None = None
    unsupported: list[str] = []
    if rewritten.strip() and _looks_like_dsl(rewritten):
        supported = _supported_screen_columns(field_dictionary, rows)
        used_columns = _extract_predicate_columns(rewritten)
        if used_columns and not any(column in supported for column in used_columns):
            unsupported = used_columns
            parse_error = (
                f"Filter references unknown columns: {', '.join(sorted(set(used_columns)))}. "
                f"Supported: {', '.join(sorted(supported))[:200]}"
            )
    try:
        filtered = [] if parse_error else _apply_screen_query(rows, rewritten)
    except Exception as exc:  # noqa: BLE001
        filtered = []
        parse_error = parse_error or (str(exc) or type(exc).__name__)
    limited = filtered[:limit]
    if parse_error:
        status = "unsupported_predicate" if unsupported else "input_error"
    elif limited:
        status = "ok"
    else:
        status = "empty"
    reason = None
    next_actions: list[str] = []
    if parse_error:
        reason = f"Filter parse error: {parse_error}"
        next_actions = [
            "Use simple comparisons joined by AND/OR.",
            'Example: sector = "Energy" AND change_pct > 0.',
        ]
    elif not limited:
        reason = f"No rows matched filter `{query}`."
        next_actions = [
            "Broaden the filter or clear it.",
            "Use the field dictionary to choose supported columns.",
        ]
    return FunctionResult(
        code=code,
        instrument=None,
        data={
            "status": status,
            "query": query,
            "filter": rewritten,
            "rows": limited,
            "field_dictionary": field_dictionary,
            "scanned": scanned,
            "matched": len(filtered),
            "limit": limit,
            "reason": reason,
            "next_actions": next_actions,
            "unsupported_columns": unsupported,
        },
        metadata={
            "query": query,
            "filter": rewritten,
            "matched": len(filtered),
            "scanned": scanned,
            "limit": limit,
            "unsupported_columns": unsupported,
        },
        sources=sources,
        warnings=warnings or [],
    )


def _apply_screen_query(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    if not query.strip():
        return list(rows)
    from showme.engine.functions.equity.eqs import filter_dataframe

    df = pd.DataFrame(rows)
    if df.empty:
        return []
    filtered = filter_dataframe(df, query)
    return filtered.to_dict(orient="records")


def _looks_like_dsl(query: str) -> bool:
    return bool(re.search(r"\s(?:AND|OR)\s|[<>=!]=?|[A-Za-z_]\w*\s*[<>=!]", query, re.I))


def _rewrite_screen_query(query: str) -> str:
    rewritten = str(query or "").strip()
    aliases = {
        "market_cap": "marketCap",
        "marketcap": "marketCap",
        "expense_ratio": "expenseRatio",
        "expense": "expenseRatio",
        "aum": "aum_usd",
        "yield_to_maturity": "yield",
        "ytm": "yield",
        "change_percent": "change_pct",
        "percent_change": "change_pct",
        "assetclass": "asset_class",
    }
    for old, new in aliases.items():
        rewritten = re.sub(rf"\b{re.escape(old)}\b", new, rewritten, flags=re.I)
    return rewritten


def _symbol_filter(value: Any) -> set[str] | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        symbols = re.split(r"[\s,;]+", value)
    elif isinstance(value, (list, tuple, set)):
        symbols = [str(item) for item in value]
    else:
        symbols = [str(value)]
    cleaned = {symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()}
    return cleaned or None


def _filter_universe(rows: list[dict[str, Any]], universe: set[str] | None) -> list[dict[str, Any]]:
    if not universe:
        return list(rows)
    return [row for row in rows if str(row.get("symbol") or "").upper() in universe]


def _merge_quote_rows(
    reference_rows: list[dict[str, Any]],
    quote_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    quote_by_symbol = {str(row.get("symbol") or "").upper(): row for row in quote_rows}
    out: list[dict[str, Any]] = []
    for row in reference_rows:
        quote = quote_by_symbol.get(str(row.get("symbol") or "").upper())
        if quote:
            out.append({**row, **quote, "quote_state": "live"})
        else:
            out.append({**row, "quote_state": "reference"})
    return out


def _security_text_search(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    terms = [term.lower() for term in re.split(r"[\s,;]+", query or "") if term.strip()]
    if not terms:
        return rows
    matched: list[dict[str, Any]] = []
    for row in rows:
        haystack = " ".join(
            str(value)
            for value in row.values()
            if value is not None and not isinstance(value, (dict, list))
        ).lower()
        tags = " ".join(str(item) for item in row.get("tags", [])).lower() if isinstance(row.get("tags"), list) else ""
        combined = f"{haystack} {tags}"
        if all(term in combined for term in terms):
            matched.append({**row, "match": "all_terms"})
        elif any(term in combined for term in terms):
            matched.append({**row, "match": "partial"})
    return sorted(matched, key=lambda row: 0 if row.get("match") == "all_terms" else 1)


def _commodity_reference_rows() -> list[dict[str, Any]]:
    return [
        {"symbol": "CL=F", "name": "WTI Crude Oil", "sector": "Energy", "exchange": "NYMEX", "contract_unit": "1,000 barrels", "volume": 290_000, "open_interest": 310_000, "curve": "front_month"},
        {"symbol": "BZ=F", "name": "Brent Crude Oil", "sector": "Energy", "exchange": "ICE", "contract_unit": "1,000 barrels", "volume": 180_000, "open_interest": 225_000, "curve": "front_month"},
        {"symbol": "NG=F", "name": "Natural Gas", "sector": "Energy", "exchange": "NYMEX", "contract_unit": "10,000 MMBtu", "volume": 160_000, "open_interest": 420_000, "curve": "front_month"},
        {"symbol": "GC=F", "name": "Gold", "sector": "Metals", "exchange": "COMEX", "contract_unit": "100 troy ounces", "volume": 145_000, "open_interest": 480_000, "curve": "front_month"},
        {"symbol": "SI=F", "name": "Silver", "sector": "Metals", "exchange": "COMEX", "contract_unit": "5,000 troy ounces", "volume": 75_000, "open_interest": 150_000, "curve": "front_month"},
        {"symbol": "HG=F", "name": "Copper", "sector": "Metals", "exchange": "COMEX", "contract_unit": "25,000 pounds", "volume": 62_000, "open_interest": 95_000, "curve": "front_month"},
        {"symbol": "ZC=F", "name": "Corn", "sector": "Agriculture", "exchange": "CBOT", "contract_unit": "5,000 bushels", "volume": 205_000, "open_interest": 620_000, "curve": "front_month"},
        {"symbol": "ZW=F", "name": "Wheat", "sector": "Agriculture", "exchange": "CBOT", "contract_unit": "5,000 bushels", "volume": 92_000, "open_interest": 220_000, "curve": "front_month"},
        {"symbol": "ZS=F", "name": "Soybeans", "sector": "Agriculture", "exchange": "CBOT", "contract_unit": "5,000 bushels", "volume": 125_000, "open_interest": 360_000, "curve": "front_month"},
    ]


def _fund_reference_rows() -> list[dict[str, Any]]:
    return [
        {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "issuer": "State Street", "category": "US Large Blend", "aum_usd": 500_000_000_000, "expenseRatio": 0.000945, "ytd_return_pct": 8.6, "dividend_yield": 0.012, "holdings": 503},
        {"symbol": "VOO", "name": "Vanguard S&P 500 ETF", "issuer": "Vanguard", "category": "US Large Blend", "aum_usd": 470_000_000_000, "expenseRatio": 0.0003, "ytd_return_pct": 8.5, "dividend_yield": 0.013, "holdings": 505},
        {"symbol": "IVV", "name": "iShares Core S&P 500 ETF", "issuer": "BlackRock", "category": "US Large Blend", "aum_usd": 460_000_000_000, "expenseRatio": 0.0003, "ytd_return_pct": 8.5, "dividend_yield": 0.013, "holdings": 505},
        {"symbol": "QQQ", "name": "Invesco QQQ Trust", "issuer": "Invesco", "category": "US Large Growth", "aum_usd": 250_000_000_000, "expenseRatio": 0.002, "ytd_return_pct": 10.4, "dividend_yield": 0.006, "holdings": 101},
        {"symbol": "VTI", "name": "Vanguard Total Stock Market ETF", "issuer": "Vanguard", "category": "US Total Market", "aum_usd": 380_000_000_000, "expenseRatio": 0.0003, "ytd_return_pct": 7.9, "dividend_yield": 0.014, "holdings": 3700},
        {"symbol": "IWM", "name": "iShares Russell 2000 ETF", "issuer": "BlackRock", "category": "US Small Blend", "aum_usd": 70_000_000_000, "expenseRatio": 0.0019, "ytd_return_pct": 3.1, "dividend_yield": 0.012, "holdings": 1980},
        {"symbol": "EEM", "name": "iShares MSCI Emerging Markets ETF", "issuer": "BlackRock", "category": "Emerging Markets", "aum_usd": 20_000_000_000, "expenseRatio": 0.0068, "ytd_return_pct": 5.2, "dividend_yield": 0.021, "holdings": 1200},
        {"symbol": "GLD", "name": "SPDR Gold Shares", "issuer": "State Street", "category": "Commodity Precious Metals", "aum_usd": 58_000_000_000, "expenseRatio": 0.004, "ytd_return_pct": 12.4, "dividend_yield": 0.0, "holdings": 1},
        {"symbol": "TLT", "name": "iShares 20+ Year Treasury Bond ETF", "issuer": "BlackRock", "category": "Long Government", "aum_usd": 55_000_000_000, "expenseRatio": 0.0015, "ytd_return_pct": -2.8, "dividend_yield": 0.039, "holdings": 45},
        {"symbol": "HYG", "name": "iShares iBoxx High Yield Corporate Bond ETF", "issuer": "BlackRock", "category": "High Yield Bond", "aum_usd": 16_000_000_000, "expenseRatio": 0.0049, "ytd_return_pct": 3.7, "dividend_yield": 0.058, "holdings": 1200},
    ]


def _bond_reference_rows() -> list[dict[str, Any]]:
    return [
        {"symbol": "US3M", "issuer": "US Treasury", "type": "Bill", "country": "US", "currency": "USD", "maturity": "3M", "tenor_years": 0.25, "yield": 5.32, "duration": 0.24, "rating": "AA+"},
        {"symbol": "US2Y", "issuer": "US Treasury", "type": "Note", "country": "US", "currency": "USD", "maturity": "2Y", "tenor_years": 2.0, "yield": 4.62, "duration": 1.9, "rating": "AA+"},
        {"symbol": "US5Y", "issuer": "US Treasury", "type": "Note", "country": "US", "currency": "USD", "maturity": "5Y", "tenor_years": 5.0, "yield": 4.48, "duration": 4.5, "rating": "AA+"},
        {"symbol": "US10Y", "issuer": "US Treasury", "type": "Note", "country": "US", "currency": "USD", "maturity": "10Y", "tenor_years": 10.0, "yield": 4.45, "duration": 8.2, "rating": "AA+"},
        {"symbol": "US30Y", "issuer": "US Treasury", "type": "Bond", "country": "US", "currency": "USD", "maturity": "30Y", "tenor_years": 30.0, "yield": 4.58, "duration": 17.6, "rating": "AA+"},
        {"symbol": "DE10Y", "issuer": "Germany", "type": "Bund", "country": "DE", "currency": "EUR", "maturity": "10Y", "tenor_years": 10.0, "yield": 2.42, "duration": 8.8, "rating": "AAA"},
        {"symbol": "GB10Y", "issuer": "United Kingdom", "type": "Gilt", "country": "GB", "currency": "GBP", "maturity": "10Y", "tenor_years": 10.0, "yield": 4.12, "duration": 8.4, "rating": "AA"},
        {"symbol": "JP10Y", "issuer": "Japan", "type": "JGB", "country": "JP", "currency": "JPY", "maturity": "10Y", "tenor_years": 10.0, "yield": 0.88, "duration": 9.4, "rating": "A+"},
    ]


def _security_reference_rows() -> list[dict[str, Any]]:
    return [
        {"symbol": "AAPL", "name": "Apple Inc.", "asset_class": "EQUITY", "exchange": "NASDAQ", "country": "US", "sector": "Technology", "tags": ["mega cap", "hardware", "consumer electronics"]},
        {"symbol": "MSFT", "name": "Microsoft Corp.", "asset_class": "EQUITY", "exchange": "NASDAQ", "country": "US", "sector": "Technology", "tags": ["mega cap", "software", "cloud"]},
        {"symbol": "NVDA", "name": "NVIDIA Corp.", "asset_class": "EQUITY", "exchange": "NASDAQ", "country": "US", "sector": "Technology", "tags": ["semiconductor", "ai", "gpu"]},
        {"symbol": "JPM", "name": "JPMorgan Chase & Co.", "asset_class": "EQUITY", "exchange": "NYSE", "country": "US", "sector": "Financials", "tags": ["bank", "large cap"]},
        {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "asset_class": "ETF", "exchange": "NYSE Arca", "country": "US", "sector": "Broad Market", "tags": ["s&p 500", "large cap", "index fund"]},
        {"symbol": "TLT", "name": "iShares 20+ Year Treasury Bond ETF", "asset_class": "ETF", "exchange": "NASDAQ", "country": "US", "sector": "Fixed Income", "tags": ["treasury", "duration", "bond"]},
        {"symbol": "BTCUSDT", "name": "Bitcoin / Tether", "asset_class": "CRYPTO", "exchange": "Binance", "country": "Global", "sector": "Digital Assets", "tags": ["bitcoin", "crypto", "spot"]},
        {"symbol": "ETHUSDT", "name": "Ethereum / Tether", "asset_class": "CRYPTO", "exchange": "Binance", "country": "Global", "sector": "Digital Assets", "tags": ["ethereum", "crypto", "smart contracts"]},
        {"symbol": "EURUSD", "name": "Euro / US Dollar", "asset_class": "FX", "exchange": "FX", "country": "Global", "sector": "G10 FX", "tags": ["euro", "dollar", "foreign exchange"]},
        {"symbol": "GC=F", "name": "Gold Futures", "asset_class": "COMMODITY", "exchange": "COMEX", "country": "US", "sector": "Metals", "tags": ["gold", "precious metals", "futures"]},
        {"symbol": "CL=F", "name": "WTI Crude Oil Futures", "asset_class": "COMMODITY", "exchange": "NYMEX", "country": "US", "sector": "Energy", "tags": ["oil", "crude", "energy", "futures"]},
        {"symbol": "US10Y", "name": "US Treasury 10Y", "asset_class": "BOND", "exchange": "Treasury", "country": "US", "sector": "Rates", "tags": ["treasury", "yield", "duration"]},
        {"symbol": "^GSPC", "name": "S&P 500 Index", "asset_class": "INDEX", "exchange": "S&P Dow Jones", "country": "US", "sector": "Index", "tags": ["s&p 500", "benchmark", "equity index"]},
    ]


def _empty_result(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, pd.DataFrame):
        return value.empty
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


async def _quote_rows(
    provider: Any,
    symbols: list[str],
    *,
    asset_class: AssetClass | None = None,
    timeout: float,
    screen_timeout: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    tasks = [
        asyncio.create_task(_quote_row(provider, symbol, asset_class, timeout))
        for symbol in symbols
    ]
    done, pending = await asyncio.wait(tasks, timeout=screen_timeout)
    for task in pending:
        task.cancel()

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for task in done:
        try:
            row = task.result()
        except Exception as exc:
            warnings.append(str(exc) or type(exc).__name__)
            continue
        if row:
            rows.append(row)
    if pending:
        warnings.append(f"{len(pending)} quote request(s) exceeded {screen_timeout:.1f}s")
    return rows, [warning for warning in warnings if warning][:4]


async def _quote_row(
    provider: Any,
    symbol: str,
    asset_class: AssetClass | None,
    timeout: float,
) -> dict[str, Any] | None:
    inst = Instrument(symbol=symbol, asset_class=asset_class or _asset_for_screen_symbol(symbol))
    budget = max(1.0, min(timeout, 4.0))
    quote = await asyncio.wait_for(
        provider.fetch(
            DataRequest(
                kind=DataKind.QUOTE,
                instrument=inst,
                extra={"timeout": budget},
            )
        ),
        timeout=budget + 0.5,
    )
    if quote is None or quote.last is None:
        return None
    # B7: ``or 0`` / ``or 1`` short-circuits were turning a missing prev close
    # into a fake -100% drop. None ⇒ drop the field; only compute when we
    # actually have a non-zero baseline so the row stays honest.
    last = quote.last
    prev = quote.close_prev
    if prev is None or prev == 0 or last is None:
        change_pct = None
        change = None
    else:
        change = float(last) - float(prev)
        change_pct = (float(last) / float(prev) - 1.0) * 100.0
    high = quote.high_24h
    low = quote.low_24h
    if high is None or low is None or last is None or last == 0:
        range_pct = None
    else:
        range_pct = (float(high) - float(low)) / float(last) * 100.0
    if last is None or quote.volume_24h is None:
        dollar_volume = None
    else:
        dollar_volume = float(last) * float(quote.volume_24h)
    return {
        "symbol": symbol,
        "last": last,
        "prev_close": prev,
        "change": change,
        "volume": quote.volume_24h,
        "dollar_volume": dollar_volume,
        "change_pct": change_pct,
        "high": high,
        "low": low,
        "range_pct": range_pct,
    }


_KNOWN_INDEX_SYMBOLS = frozenset({"SPX", "NDX", "RUT", "DJI", "VIX"})
_KNOWN_ETF_SYMBOLS = frozenset({"SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "GLD", "TLT"})


def _asset_for_screen_symbol(symbol: str) -> AssetClass:
    s = symbol.upper()
    # B7: bare ``SPX`` / ``NDX`` etc. don't carry a ``^`` prefix on every
    # provider so they were silently being misclassified as EQUITY. Promote
    # the whitelist BEFORE the equity fallthrough.
    if s in _KNOWN_INDEX_SYMBOLS or s.startswith("^"):
        return AssetClass.INDEX
    if s in _KNOWN_ETF_SYMBOLS:
        return AssetClass.ETF
    if s.endswith("=X"):
        return AssetClass.FX
    # B7: original expression was
    #   s.endswith("USDT") or s.endswith("USDC") or s.endswith("USD") and len(s) > 3
    # which binds as
    #   USDT-or-USDC OR (USD AND len>3)
    # so e.g. "USDT" (len 4, ends in USDT) matched, but "USD" (len 3) didn't —
    # the length guard never blocked USDC/USDT. Parenthesize so the length
    # guard applies cleanly to plain-USD-suffix symbols.
    if (
        s.endswith("USDT")
        or s.endswith("USDC")
        or (s.endswith("USD") and len(s) > 3)
    ):
        return AssetClass.CRYPTO
    if "=" in s:
        return AssetClass.COMMODITY
    return AssetClass.EQUITY


def _float_param(params: dict[str, Any], name: str, default: float) -> float:
    try:
        return float(params.get(name, default))
    except Exception:
        return default


def _int_param(params: dict[str, Any], name: str, default: int) -> int:
    try:
        return max(1, min(int(params.get(name, default)), 500))
    except Exception:
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _most_active_reference_rows() -> list[dict[str, Any]]:
    return [
        {"symbol": "NVDA", "name": "NVIDIA", "asset_class": "equity", "exchange": "NASDAQ", "last": 198.45, "volume": 310_000_000, "change_pct": 2.1},
        {"symbol": "TSLA", "name": "Tesla", "asset_class": "equity", "exchange": "NASDAQ", "last": 390.82, "volume": 128_000_000, "change_pct": -1.3},
        {"symbol": "AAPL", "name": "Apple", "asset_class": "equity", "exchange": "NASDAQ", "last": 280.14, "volume": 64_000_000, "change_pct": 0.8},
        {"symbol": "MSFT", "name": "Microsoft", "asset_class": "equity", "exchange": "NASDAQ", "last": 414.44, "volume": 38_000_000, "change_pct": 1.0},
        {"symbol": "META", "name": "Meta Platforms", "asset_class": "equity", "exchange": "NASDAQ", "last": 608.75, "volume": 31_000_000, "change_pct": 1.9},
        {"symbol": "AMZN", "name": "Amazon", "asset_class": "equity", "exchange": "NASDAQ", "last": 268.26, "volume": 52_000_000, "change_pct": -0.4},
        {"symbol": "GOOGL", "name": "Alphabet", "asset_class": "equity", "exchange": "NASDAQ", "last": 385.69, "volume": 29_000_000, "change_pct": 0.7},
        {"symbol": "AMD", "name": "Advanced Micro Devices", "asset_class": "equity", "exchange": "NASDAQ", "last": 166.50, "volume": 79_000_000, "change_pct": 1.6},
        {"symbol": "PLTR", "name": "Palantir", "asset_class": "equity", "exchange": "NYSE", "last": 46.20, "volume": 92_000_000, "change_pct": 2.4},
        {"symbol": "JPM", "name": "JPMorgan Chase", "asset_class": "equity", "exchange": "NYSE", "last": 238.10, "volume": 18_000_000, "change_pct": 0.2},
        {"symbol": "BTCUSDT", "name": "Bitcoin / Tether", "asset_class": "crypto", "exchange": "BINANCE", "last": 79_240.75, "volume": 28_000, "change_pct": -0.2},
        {"symbol": "ETHUSDT", "name": "Ether / Tether", "asset_class": "crypto", "exchange": "BINANCE", "last": 2_343.10, "volume": 540_000, "change_pct": 0.5},
        {"symbol": "SOLUSDT", "name": "Solana / Tether", "asset_class": "crypto", "exchange": "BINANCE", "last": 84.67, "volume": 13_000_000, "change_pct": 1.1},
        {"symbol": "BNBUSDT", "name": "BNB / Tether", "asset_class": "crypto", "exchange": "BINANCE", "last": 602.0, "volume": 1_400_000, "change_pct": 0.4},
        {"symbol": "XRPUSDT", "name": "XRP / Tether", "asset_class": "crypto", "exchange": "BINANCE", "last": 0.62, "volume": 1_900_000_000, "change_pct": 1.7},
        {"symbol": "DOGEUSDT", "name": "Dogecoin / Tether", "asset_class": "crypto", "exchange": "BINANCE", "last": 0.12, "volume": 4_300_000_000, "change_pct": -0.6},
        {"symbol": "EURUSD=X", "name": "Euro / US Dollar", "asset_class": "fx", "exchange": "YFINANCE FX", "last": 1.08, "volume": 0, "change_pct": 0.1},
        {"symbol": "GBPUSD=X", "name": "British Pound / US Dollar", "asset_class": "fx", "exchange": "YFINANCE FX", "last": 1.25, "volume": 0, "change_pct": -0.1},
        {"symbol": "USDJPY=X", "name": "US Dollar / Japanese Yen", "asset_class": "fx", "exchange": "YFINANCE FX", "last": 153.0, "volume": 0, "change_pct": 0.2},
        {"symbol": "AUDUSD=X", "name": "Australian Dollar / US Dollar", "asset_class": "fx", "exchange": "YFINANCE FX", "last": 0.65, "volume": 0, "change_pct": 0.0},
    ]


def _normalize_most_asset_class(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text or text == "all":
        return None
    aliases = {
        "equities": "equity",
        "stocks": "equity",
        "stock": "equity",
        "equity": "equity",
        "crypto": "crypto",
        "cryptocurrency": "crypto",
        "fx": "fx",
        "forex": "fx",
        "currency": "fx",
    }
    return aliases.get(text, text)


def _merge_live_most_rows(reference_rows: list[dict[str, Any]], quote_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    quote_by_symbol = {str(row.get("symbol") or "").upper(): row for row in quote_rows}
    out: list[dict[str, Any]] = []
    for row in reference_rows:
        symbol = str(row.get("symbol") or "").upper()
        quote = quote_by_symbol.get(symbol)
        if not quote:
            continue
        merged = {**row, **quote, "quote_state": "live"}
        if merged.get("dollar_volume") is None:
            last = merged.get("last")
            volume = merged.get("volume")
            if last is not None and volume is not None:
                merged["dollar_volume"] = float(last) * float(volume)
        out.append(merged)
    return out


def _rank_most_active_rows(rows: list[dict[str, Any]], sort_key: str) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        merged = dict(row)
        if merged.get("dollar_volume") is None and merged.get("last") is not None and merged.get("volume") is not None:
            merged["dollar_volume"] = float(merged["last"]) * float(merged["volume"])
        merged["activity_score"] = (
            float(merged.get("dollar_volume") or 0) / 1_000_000
            + float(merged.get("volume") or 0) / 10_000_000
            + abs(float(merged.get("change_pct") or 0))
        )
        enriched.append(merged)
    if sort_key in {"volume", "vol"}:
        def key(row):
            return float(row.get("volume") or 0)
    elif sort_key in {"abs_change", "change", "mover"}:
        def key(row):
            return abs(float(row.get("change_pct") or 0))
    elif sort_key in {"activity", "score"}:
        def key(row):
            return float(row.get("activity_score") or 0)
    else:
        def key(row):
            return float(row.get("dollar_volume") or 0)
    return sorted(enriched, key=key, reverse=True)


def _most_active_payload(
    rows: list[dict[str, Any]],
    universe: list[str],
    *,
    limit: int,
    asset_class: str,
    sort: str,
    live: bool,
    status: str,
    reason: str | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "rows": rows,
        "universe": universe,
        "universe_size": len(universe),
        "limit": limit,
        "asset_class_filter": asset_class,
        "sort": sort,
        "live": live,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "methodology": (
            "Ranks a selected cross-asset universe by provider volume, absolute percent move, "
            "or approximate traded notional. Dollar volume is last price multiplied by session/24h volume."
        ),
        "field_dictionary": _MOST_FIELDS,
    }


_WORLD_INDEX_META = {
    "^GSPC": {"name": "S&P 500", "region": "americas"},
    "^DJI": {"name": "Dow Jones Industrial Average", "region": "americas"},
    "^IXIC": {"name": "Nasdaq Composite", "region": "americas"},
    "^RUT": {"name": "Russell 2000", "region": "americas"},
    "^FTSE": {"name": "FTSE 100", "region": "europe"},
    "^GDAXI": {"name": "DAX", "region": "europe"},
    "^FCHI": {"name": "CAC 40", "region": "europe"},
    "^N225": {"name": "Nikkei 225", "region": "asia"},
    "^HSI": {"name": "Hang Seng", "region": "asia"},
    "^STOXX50E": {"name": "Euro Stoxx 50", "region": "europe"},
    "XU100.IS": {"name": "BIST 100", "region": "mea"},
}


def _enrich_world_index_row(row: dict[str, Any]) -> dict[str, Any]:
    meta = _WORLD_INDEX_META.get(str(row.get("symbol") or "").upper(), {})
    return {
        **row,
        "name": row.get("name") or meta.get("name"),
        "region": row.get("region") or meta.get("region"),
        "market_state": row.get("market_state") or "live",
    }


def _world_index_template() -> list[dict[str, Any]]:
    return [
        {"symbol": "^GSPC", "name": "S&P 500", "region": "americas", "last": 5200.0, "change_pct": 0.18, "high": 5215.0, "low": 5178.0, "market_state": "model"},
        {"symbol": "^DJI", "name": "Dow Jones Industrial Average", "region": "americas", "last": 39000.0, "change_pct": -0.05, "high": 39120.0, "low": 38860.0, "market_state": "model"},
        {"symbol": "^IXIC", "name": "Nasdaq Composite", "region": "americas", "last": 16500.0, "change_pct": 0.31, "high": 16590.0, "low": 16380.0, "market_state": "model"},
        {"symbol": "^FTSE", "name": "FTSE 100", "region": "europe", "last": 8200.0, "change_pct": 0.12, "high": 8230.0, "low": 8160.0, "market_state": "model"},
        {"symbol": "^GDAXI", "name": "DAX", "region": "europe", "last": 18400.0, "change_pct": 0.21, "high": 18480.0, "low": 18260.0, "market_state": "model"},
        {"symbol": "^FCHI", "name": "CAC 40", "region": "europe", "last": 8100.0, "change_pct": -0.09, "high": 8155.0, "low": 8048.0, "market_state": "model"},
        {"symbol": "^N225", "name": "Nikkei 225", "region": "asia", "last": 39200.0, "change_pct": 0.27, "high": 39420.0, "low": 38980.0, "market_state": "model"},
        {"symbol": "^HSI", "name": "Hang Seng", "region": "asia", "last": 18100.0, "change_pct": -0.22, "high": 18240.0, "low": 17990.0, "market_state": "model"},
        {"symbol": "XU100.IS", "name": "BIST 100", "region": "mea", "last": 9800.0, "change_pct": 0.44, "high": 9860.0, "low": 9720.0, "market_state": "model"},
    ]
