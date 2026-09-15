"""SRCH, FSRC, CSRC, SECF, MOST, WEI — screen suite."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
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
        # Default polarity (2026-09-11, L5): the keyless US Treasury par-yield
        # curve (``deps.ustreasury``) refreshes the US tenor yields by default;
        # an explicit falsy live / ``reference=true`` serves the static table.
        reference = _truthy(params.get("reference"))
        live_param_present = (
            params.get("live_screen") is not None or params.get("live") is not None
        )
        live = (
            _truthy(params.get("live_screen") or params.get("live"))
            if live_param_present
            else not reference
        )
        sources = ["showme_bond_reference_universe"]
        warnings: list[str] = []
        reference_note: str | None = None
        if live:
            live_yields, yield_source = await _treasury_curve_yields(
                getattr(self.deps, "ustreasury", None)
            )
            if live_yields:
                rows = _merge_yield_rows(rows, live_yields, yield_source)
                sources = [yield_source, "showme_bond_reference_universe"]
                reference_note = (
                    "US Treasury yields are live via the keyless Treasury curve; "
                    "durations, ratings, and non-US rows are curated reference values."
                )
            else:
                warnings = [
                    "US Treasury curve unavailable; yields are curated reference values."
                ]
        # H-6 honesty fix (2026-09-08): the bond universe is a STATIC
        # reference table (2024-era yields) with no live path yet, so a
        # matched filter must never report status "ok" as if these were
        # current market levels. The payload is labelled "reference".
        return _screen_result(
            self.code,
            rows,
            query=query,
            limit=_int_param(params, "limit", 50),
            sources=sources,
            field_dictionary=_BOND_FIELDS,
            warnings=warnings,
            reference=True,
            reference_note=reference_note,
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
        # Default polarity (2026-09-11, L9): attempt keyless yfinance quotes by
        # default; an explicit falsy ``live``/``live_screen`` or
        # ``reference=true`` serves the curated reference universe only.
        reference = _truthy(params.get("reference"))
        live_param_present = (
            params.get("live_screen") is not None or params.get("live") is not None
        )
        live = (
            _truthy(params.get("live_screen") or params.get("live"))
            if live_param_present
            else not reference
        )
        warnings: list[str] = []
        sources = ["showme_fund_reference_universe"]
        if live and self.deps.yfinance:
            symbols = [str(row["symbol"]) for row in rows]
            # One batched Yahoo call covers the whole fund universe; the
            # per-symbol fan-out can only complete ~11 inside the screen
            # budget because of the provider's shared 2 rps token bucket.
            quotes, warnings = await _batch_quote_rows(self.deps.yfinance, symbols)
            if not quotes:
                quotes, fallback_warnings = await _quote_rows(
                    self.deps.yfinance,
                    symbols,
                    asset_class=AssetClass.ETF,
                    timeout=_float_param(params, "quote_timeout", 3.0),
                    screen_timeout=_float_param(params, "screen_timeout", 8.0),
                    concurrency=int(_float_param(params, "quote_concurrency", 8.0)),
                    burst=True,
                )
                warnings = [*warnings, *fallback_warnings]
            if quotes:
                rows = _merge_quote_rows(rows, quotes)
                sources = ["yfinance", "showme_fund_reference_universe"]
            else:
                warnings = [*warnings, "quote provider returned no usable rows"]
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
        # Default polarity (2026-09-11, L5): attempt live yfinance quotes by
        # default; an explicit falsy ``live``/``live_screen`` or
        # ``reference=true`` serves the curated reference universe only.
        reference = _truthy(params.get("reference"))
        live_param_present = (
            params.get("live_screen") is not None or params.get("live") is not None
        )
        live = (
            _truthy(params.get("live_screen") or params.get("live"))
            if live_param_present
            else not reference
        )
        warnings: list[str] = []
        sources = ["showme_commodity_reference_universe"]
        if live and self.deps.yfinance:
            # Bounded fan-out over the full futures complex (~28 contracts):
            # semaphore-capped concurrency + the provider bucket bypass so the
            # whole board resolves inside the latency budget (WEI pattern).
            # Symbols the provider does not return are kept in the payload as
            # explicit quote_state="reference" rows — never silently dropped.
            quotes, warnings = await _screen_quote_rows(
                self.deps.yfinance,
                [str(row["symbol"]) for row in rows],
                timeout=_float_param(params, "quote_timeout", 4.0),
                screen_timeout=_float_param(params, "screen_timeout", 8.0),
                concurrency=int(_float_param(params, "quote_concurrency", 8.0)),
            )
            if quotes:
                rows = _merge_quote_rows(rows, quotes)
                sources = ["yfinance", "showme_commodity_reference_universe"]
                unresolved = sum(1 for row in rows if row.get("quote_state") != "live")
                if unresolved:
                    warnings = [
                        *warnings,
                        f"{unresolved} commodity quote(s) unavailable this cycle",
                    ]
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
        # Default polarity (2026-09-11, L5): enrich matches with live yfinance
        # quotes by default; the curated identity fields keep a per-row
        # reference label. An explicit falsy live / ``reference=true`` serves
        # the reference master only.
        reference = _truthy(params.get("reference"))
        live_param_present = (
            params.get("live_screen") is not None or params.get("live") is not None
        )
        live = (
            _truthy(params.get("live_screen") or params.get("live"))
            if live_param_present
            else not reference
        )
        limit = _int_param(params, "limit", 50)
        sources = ["showme_security_master_reference"]
        warnings: list[str] = []
        quote_timeout = _float_param(params, "quote_timeout", 3.0)
        screen_timeout = _float_param(params, "screen_timeout", 5.0)
        # The master is S&P 500 scale; the quote provider must only ever see
        # the page that will be returned (one fetch per returned row, never
        # per scanned row).
        if _looks_like_dsl(query):
            result = _screen_result(
                self.code,
                rows,
                query=_rewrite_screen_query(query),
                limit=limit,
                sources=sources,
                field_dictionary=_SECURITY_FIELDS,
                warnings=warnings,
                reference=True,
                reference_note=(
                    "Live quotes attached where available; identity fields, "
                    "exchanges and tags are the curated reference master."
                ),
            )
            page = result.data.get("rows") or []
            if live and self.deps.yfinance and page:
                quotes, quote_warnings = await _quote_rows(
                    self.deps.yfinance,
                    [str(row["symbol"]) for row in page],
                    timeout=quote_timeout,
                    screen_timeout=screen_timeout,
                )
                if quotes:
                    result.data["rows"] = _merge_quote_rows(page, quotes)
                    result.sources = ["yfinance", "showme_security_master_reference"]
                    missing = sum(
                        1 for row in result.data["rows"] if row.get("quote_state") != "live"
                    )
                    if missing:
                        quote_warnings = [*quote_warnings, f"{missing} symbol(s) had no live quote"]
                else:
                    quote_warnings = [*quote_warnings, "quote provider returned no usable rows"]
                result.warnings = [*result.warnings, *quote_warnings]
            return result

        filtered = _security_text_search(rows, query)
        page = filtered[:limit]
        live_quotes = False
        if live and self.deps.yfinance and page:
            quotes, warnings = await _quote_rows(
                self.deps.yfinance,
                [str(row["symbol"]) for row in page],
                timeout=quote_timeout,
                screen_timeout=screen_timeout,
            )
            if quotes:
                page = _merge_quote_rows(page, quotes)
                sources = ["yfinance", "showme_security_master_reference"]
                live_quotes = True
                missing = sum(1 for row in page if row.get("quote_state") != "live")
                if missing:
                    warnings = [*warnings, f"{missing} symbol(s) had no live quote"]
            else:
                warnings = [*warnings, "quote provider returned no usable rows"]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok" if filtered else "empty",
                "query": query,
                "match_mode": "text_search",
                "rows": page,
                "field_dictionary": _SECURITY_FIELDS,
                "scanned": len(rows),
                "matched": len(filtered),
                "next_actions": [] if filtered else [
                    "Try a broader symbol, company name, asset class, or tag.",
                    "Examples: technology, treasury, crude, bitcoin, SPY.",
                ],
            },
            metadata={
                "query": query,
                "matched": len(filtered),
                "scanned": len(rows),
                "limit": limit,
                "live_quotes": live_quotes,
            },
            warnings=warnings,
            sources=sources,
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
        # Default polarity (2026-09-11, L9): attempt keyless yfinance quotes by
        # default; an explicit falsy ``live``/``live_screen`` or
        # ``reference=true`` serves the labelled reference universe only.
        reference = _truthy(params.get("reference"))
        live_param_present = (
            params.get("live_screen") is not None or params.get("live") is not None
        )
        live = (
            _truthy(params.get("live_screen") or params.get("live"))
            if live_param_present
            else not reference
        )
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
            # Cross-asset scan. Crypto comes from ONE batched Binance call
            # (top USDT pairs by 24h quote volume); equities/ETFs/FX fan out
            # per symbol under a semaphore + screen deadline with the provider
            # rate-limit bucket bypassed (bounded concurrency replaces it).
            # Symbols the providers do not return inside the budget stay in
            # the payload as explicit quote_state="unavailable" rows — the
            # pane never silently collapses to the few names that answered.
            def _is_crypto(row: dict[str, Any]) -> bool:
                return _normalize_most_asset_class(row.get("asset_class")) == "crypto"

            crypto_rows = [row for row in rows if _is_crypto(row)]
            other_rows = [row for row in rows if not _is_crypto(row)]
            warnings: list[str] = []
            provider_sources: list[str] = []
            merged: list[dict[str, Any]] = []
            if crypto_rows:
                batch_rows = await _binance_top_crypto_rows()
                if batch_rows:
                    merged.extend(batch_rows)
                    provider_sources.append("binance")
                else:
                    fallback_quotes, fallback_warnings = await _screen_quote_rows(
                        self.deps.yfinance,
                        [str(row["symbol"]) for row in crypto_rows],
                        timeout=_float_param(params, "quote_timeout", 4.0),
                        screen_timeout=_float_param(params, "screen_timeout", 6.0),
                        concurrency=int(_float_param(params, "quote_concurrency", 8.0)),
                    )
                    merged.extend(
                        _merge_live_most_rows(crypto_rows, fallback_quotes, keep_unresolved=True)
                    )
                    warnings.extend(fallback_warnings)
                    provider_sources.append("yfinance")
                    warnings.append(
                        "Binance batch ticker unavailable; crypto quotes fell back per symbol"
                    )
            if other_rows:
                quote_rows, quote_warnings = await _screen_quote_rows(
                    self.deps.yfinance,
                    [str(row["symbol"]) for row in other_rows],
                    timeout=_float_param(params, "quote_timeout", 4.0),
                    screen_timeout=_float_param(params, "screen_timeout", 9.0),
                    concurrency=int(_float_param(params, "quote_concurrency", 12.0)),
                )
                merged.extend(_merge_live_most_rows(other_rows, quote_rows, keep_unresolved=True))
                warnings.extend(quote_warnings)
                provider_sources.append("yfinance")
            resolved = sum(1 for row in merged if row.get("quote_state") == "live")
            unavailable = len(merged) - resolved
            if unavailable:
                warnings.append(
                    f"{unavailable} scanned symbol(s) had no usable live quote this cycle"
                )
            ranked = _rank_most_active_rows(merged, sort_key)[:limit]
            scan_universe = [str(row.get("symbol") or "") for row in merged]
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_most_active_payload(
                    ranked,
                    scan_universe,
                    limit=limit,
                    asset_class=asset_filter or "all",
                    sort=sort_key,
                    live=True,
                    status="ok" if resolved else "provider_unavailable",
                    reason=(
                        None
                        if resolved
                        else "Quote providers returned no usable rows within the latency budget."
                    ),
                    scanned=len(merged),
                    resolved=resolved,
                    unavailable=unavailable,
                ),
                metadata={
                    "live": True,
                    "universe_size": len(scan_universe),
                    "scanned": len(merged),
                    "live_rows": resolved,
                    "unavailable": unavailable,
                    "limit": limit,
                    "asset_class": asset_filter or "all",
                    "sort": sort_key,
                },
                sources=[*provider_sources, "showme_most_active_universe"],
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
        # Single source of truth: the curated, provider-verified world set.
        indices = _world_index_symbols()
        # Default polarity (2026-09-11, L9): attempt keyless yfinance quotes by
        # default; an explicit falsy ``live``/``live_screen`` or
        # ``reference=true`` serves the labelled deterministic template only.
        reference = _truthy(params.get("reference"))
        live_param_present = (
            params.get("live_screen") is not None or params.get("live") is not None
        )
        live = (
            _truthy(params.get("live_screen") or params.get("live"))
            if live_param_present
            else not reference
        )
        if live and self.deps.yfinance:
            rows, warnings = await _quote_rows(
                self.deps.yfinance,
                indices,
                asset_class=AssetClass.INDEX,
                # Global universe (~38 symbols, every timezone). The fan-out
                # runs as a BOUNDED BURST (concurrency 8, adapter rate-limit
                # bypass): the yfinance adapter's shared 2 req/s token bucket
                # used to serialize this queue inside each call's latency
                # budget, so everything past the first ~11 symbols timed out
                # and silently vanished from the pane. The screen budget
                # gives the slowest regional exchanges (NZX, SET, BIST)
                # headroom; unresolved symbols are still returned as
                # explicit no-quote rows — never dropped.
                timeout=_float_param(params, "quote_timeout", 6.0),
                screen_timeout=_float_param(params, "screen_timeout", 12.0),
                concurrency=int(_float_param(params, "quote_concurrency", 8.0)),
                burst=True,
            )
            if rows:
                complete = _complete_world_index_rows(rows)
                resolved = sum(1 for row in complete if row.get("last") is not None)
                unresolved = len(complete) - resolved
                if unresolved:
                    warnings = [
                        *warnings,
                        f"{unresolved} index quote(s) unavailable this cycle",
                    ]
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
                        "rows": complete,
                        "universe_size": len(indices),
                        "resolved": resolved,
                        "unresolved": unresolved,
                        "source_mode": "yfinance_live",
                        "as_of": _utc_now_iso(),
                    },
                    metadata={
                        "live": True,
                        "universe_size": len(indices),
                        "resolved": resolved,
                        "unresolved": unresolved,
                    },
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
                    "source_mode": "world_index_template",
                    "as_of": _utc_now_iso(),
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
        # No live provider wired ⇒ deterministic model. Mark it degraded so
        # the UI never paints model rows as live market data.
        degraded = True
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok" if not live else "provider_unavailable",
                "rows": _world_index_template(),
                "universe_size": len(indices),
                "source_mode": "world_index_template",
                "as_of": _utc_now_iso(),
            },
            metadata={"live": False, "fallback": True, "degraded": degraded, "universe_size": len(indices)},
            sources=["showme_local_baseline"],
            warnings=warnings,
        )


_COMMODITY_FIELDS = [
    {"field": "symbol", "meaning": "Yahoo futures ticker used for quote lookup."},
    {"field": "sector", "meaning": "Commodity complex such as Energy, Metals, or Agriculture."},
    {"field": "last", "meaning": "Latest available futures price when live quotes are available."},
    {"field": "change_pct", "meaning": "Percent move versus prior close when live quotes are available."},
    {"field": "volume", "meaning": "Latest session volume from the quote provider when available."},
    {"field": "open_interest", "meaning": "Curated reference open interest — the quote provider does not publish OI."},
    {"field": "open_interest_state", "meaning": "\"reference\" — open interest comes from the curated universe, never the live quote."},
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
    reference: bool = False,
    reference_note: str | None = None,
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
        status = "reference" if reference else "ok"
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
            **({"data_mode": "reference"} if reference else {}),
        },
        sources=sources,
        warnings=(
            (warnings or [])
            + ([
                reference_note
                or (
                    "Static reference bond universe: yields and durations are curated "
                    "reference values, not live market quotes."
                )
            ] if reference and limited else [])
        ),
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
        # Session-17: the EQS pane presets spell the yield ``dividendYield``;
        # fold it here too so the screen suite's supported-column check does
        # not reject a predicate that ``filter_dataframe`` can serve.
        "dividendyield": "dividend_yield",
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
        # The quote provider never fills open interest, so a row that carries
        # a curated ``open_interest`` must stay flagged as reference even when
        # the rest of the row is quote_state="live" (CSRC honesty fix).
        oi_state = (
            {"open_interest_state": "reference"}
            if row.get("open_interest") is not None
            else {}
        )
        if quote:
            out.append({**row, **quote, **oi_state, "quote_state": "live"})
        else:
            out.append({**row, **oi_state, "quote_state": "reference"})
    return out


# Tenors refreshed from the keyless US Treasury daily par-yield curve CSV.
# The full nominal curve (1 Mo … 30 Yr) is published; only tenors that have a
# matching reference row are mapped here.
_US_TREASURY_CURVE_COLUMNS = {
    "US3M": "3 Mo",
    "US6M": "6 Mo",
    "US1Y": "1 Yr",
    "US2Y": "2 Yr",
    "US3Y": "3 Yr",
    "US5Y": "5 Yr",
    "US7Y": "7 Yr",
    "US10Y": "10 Yr",
    "US20Y": "20 Yr",
    "US30Y": "30 Yr",
}


async def _treasury_curve_yields(provider: Any) -> tuple[dict[str, float], str]:
    """Latest keyless US Treasury par-yield per tenor; ``({}, "")`` on failure.

    ``provider`` is the ``ustreasury`` adapter (``yield_curve()`` returns a
    date-indexed DataFrame). Any failure degrades to an empty map so callers
    keep their curated reference rows instead of fabricating yields.
    """
    if provider is None:
        return {}, ""
    try:
        curve = await provider.yield_curve()
    except Exception:  # noqa: BLE001 — outage degrades to reference rows
        return {}, ""
    try:
        if hasattr(curve, "empty") and curve.empty:
            return {}, ""
        latest = curve.dropna(how="all").iloc[-1] if hasattr(curve, "dropna") else curve.iloc[-1]
    except Exception:  # noqa: BLE001
        return {}, ""
    yields: dict[str, float] = {}
    for symbol, column in _US_TREASURY_CURVE_COLUMNS.items():
        value = latest.get(column) if hasattr(latest, "get") else None
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            yields[symbol] = number
    return (yields, "ustreasury") if yields else ({}, "")


def _merge_yield_rows(
    rows: list[dict[str, Any]],
    live_yields: dict[str, float],
    source: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        if symbol in live_yields:
            out.append({
                **row,
                "yield": round(live_yields[symbol], 3),
                "yield_state": "live",
                "yield_source": source,
            })
        else:
            out.append({**row, "yield_state": "reference"})
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
    """Full liquid futures complex (energy, metals, grains, softs, livestock).

    Every Yahoo futures ticker below was probed live via
    ``GET /api/quote/<TICKER>`` from this machine (2026-09-15) and returned a
    finite last price. Verified-rejected (do NOT re-add without a fresh
    probe): ``SRU=F`` (404 on the public provider) and ``LIT=F`` (resolves —
    but to the 2-Year Eris Swap Futures contract, NOT lithium; the lithium
    hydroxide contract is ``LTH=F`` and is included below).

    ``volume``/``open_interest`` on newly added rows are deliberately null:
    the quote provider never publishes them and ShowMe will not fabricate
    reference numbers for contracts the curated table never carried. The
    legacy rows keep their curated reference values (flagged per row by
    ``open_interest_state="reference"`` after a live merge).
    """
    return [
        # Energy
        {"symbol": "CL=F", "name": "WTI Crude Oil", "sector": "Energy", "exchange": "NYMEX", "contract_unit": "1,000 barrels", "volume": 290_000, "open_interest": 310_000, "curve": "front_month"},
        {"symbol": "BZ=F", "name": "Brent Crude Oil", "sector": "Energy", "exchange": "ICE", "contract_unit": "1,000 barrels", "volume": 180_000, "open_interest": 225_000, "curve": "front_month"},
        {"symbol": "NG=F", "name": "Natural Gas", "sector": "Energy", "exchange": "NYMEX", "contract_unit": "10,000 MMBtu", "volume": 160_000, "open_interest": 420_000, "curve": "front_month"},
        {"symbol": "RB=F", "name": "RBOB Gasoline", "sector": "Energy", "exchange": "NYMEX", "contract_unit": "42,000 gallons", "curve": "front_month"},
        {"symbol": "HO=F", "name": "NY Harbor ULSD (Heating Oil)", "sector": "Energy", "exchange": "NYMEX", "contract_unit": "42,000 gallons", "curve": "front_month"},
        # Metals
        {"symbol": "GC=F", "name": "Gold", "sector": "Metals", "exchange": "COMEX", "contract_unit": "100 troy ounces", "volume": 145_000, "open_interest": 480_000, "curve": "front_month"},
        {"symbol": "SI=F", "name": "Silver", "sector": "Metals", "exchange": "COMEX", "contract_unit": "5,000 troy ounces", "volume": 75_000, "open_interest": 150_000, "curve": "front_month"},
        {"symbol": "HG=F", "name": "Copper", "sector": "Metals", "exchange": "COMEX", "contract_unit": "25,000 pounds", "volume": 62_000, "open_interest": 95_000, "curve": "front_month"},
        {"symbol": "PL=F", "name": "Platinum", "sector": "Metals", "exchange": "NYMEX", "contract_unit": "50 troy ounces", "curve": "front_month"},
        {"symbol": "PA=F", "name": "Palladium", "sector": "Metals", "exchange": "NYMEX", "contract_unit": "100 troy ounces", "curve": "front_month"},
        {"symbol": "ALI=F", "name": "Aluminum", "sector": "Metals", "exchange": "COMEX", "contract_unit": "25 metric tons", "curve": "front_month"},
        {"symbol": "LTH=F", "name": "Lithium Hydroxide (CIF CJK)", "sector": "Metals", "exchange": "COMEX", "contract_unit": "1 metric ton", "curve": "front_month"},
        {"symbol": "UX=F", "name": "Uranium U3O8", "sector": "Metals", "exchange": "COMEX", "contract_unit": "250 lbs U3O8", "curve": "front_month"},
        # Grains
        {"symbol": "ZC=F", "name": "Corn", "sector": "Grains", "exchange": "CBOT", "contract_unit": "5,000 bushels", "volume": 205_000, "open_interest": 620_000, "curve": "front_month"},
        {"symbol": "ZW=F", "name": "Chicago SRW Wheat", "sector": "Grains", "exchange": "CBOT", "contract_unit": "5,000 bushels", "volume": 92_000, "open_interest": 220_000, "curve": "front_month"},
        {"symbol": "KE=F", "name": "KC HRW Wheat", "sector": "Grains", "exchange": "CBOT", "contract_unit": "5,000 bushels", "curve": "front_month"},
        {"symbol": "ZS=F", "name": "Soybeans", "sector": "Grains", "exchange": "CBOT", "contract_unit": "5,000 bushels", "volume": 125_000, "open_interest": 360_000, "curve": "front_month"},
        {"symbol": "ZM=F", "name": "Soybean Meal", "sector": "Grains", "exchange": "CBOT", "contract_unit": "100 short tons", "curve": "front_month"},
        {"symbol": "ZL=F", "name": "Soybean Oil", "sector": "Grains", "exchange": "CBOT", "contract_unit": "60,000 pounds", "curve": "front_month"},
        {"symbol": "ZO=F", "name": "Oats", "sector": "Grains", "exchange": "CBOT", "contract_unit": "5,000 bushels", "curve": "front_month"},
        # Softs
        {"symbol": "KC=F", "name": "Coffee C", "sector": "Softs", "exchange": "ICE", "contract_unit": "37,500 pounds", "curve": "front_month"},
        {"symbol": "SB=F", "name": "Sugar No. 11", "sector": "Softs", "exchange": "ICE", "contract_unit": "112,000 pounds", "curve": "front_month"},
        {"symbol": "CC=F", "name": "Cocoa", "sector": "Softs", "exchange": "ICE", "contract_unit": "10 metric tons", "curve": "front_month"},
        {"symbol": "CT=F", "name": "Cotton No. 2", "sector": "Softs", "exchange": "ICE", "contract_unit": "50,000 pounds", "curve": "front_month"},
        {"symbol": "OJ=F", "name": "Frozen Concentrated Orange Juice", "sector": "Softs", "exchange": "ICE", "contract_unit": "15,000 pounds", "curve": "front_month"},
        # Livestock & dairy
        {"symbol": "LE=F", "name": "Live Cattle", "sector": "Livestock", "exchange": "CME", "contract_unit": "40,000 pounds", "curve": "front_month"},
        {"symbol": "HE=F", "name": "Lean Hogs", "sector": "Livestock", "exchange": "CME", "contract_unit": "40,000 pounds", "curve": "front_month"},
        {"symbol": "GF=F", "name": "Feeder Cattle", "sector": "Livestock", "exchange": "CME", "contract_unit": "50,000 pounds", "curve": "front_month"},
        {"symbol": "DY=F", "name": "Dry Whey", "sector": "Livestock", "exchange": "CME", "contract_unit": "44,000 pounds", "curve": "front_month"},
    ]


def _commodity_reference_symbols() -> list[str]:
    """Yahoo tickers of the curated commodity complex (route-default helper)."""
    return [str(row["symbol"]) for row in _commodity_reference_rows()]


def _fund_reference_rows() -> list[dict[str, Any]]:
    """Curated fund/ETF reference universe (60+ liquid US vehicles).

    AUM/expense/return fields are curated reference values (the same
    legitimacy class as the original 10-row table); the live quote overlay
    attaches real prices per row when the provider answers. Categories are
    the values the FSRC pane composes into ``category = "…"`` predicates.
    """
    # Verified live on 2026-09-15: batch quote probe over this exact list
    # returned 68/68 symbols with a last price (0 rejects). The probe was run
    # through the production batch path (``fetch_refdata_batch``); the
    # sidecar's per-symbol ``/api/quote`` route was not used because its
    # long-running process could not resolve the Yahoo host at probe time.
    return [
        # US Large Blend
        {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "issuer": "State Street", "category": "US Large Blend", "aum_usd": 500_000_000_000, "expenseRatio": 0.000945, "ytd_return_pct": 8.6, "dividend_yield": 0.012, "holdings": 503},
        {"symbol": "VOO", "name": "Vanguard S&P 500 ETF", "issuer": "Vanguard", "category": "US Large Blend", "aum_usd": 470_000_000_000, "expenseRatio": 0.0003, "ytd_return_pct": 8.5, "dividend_yield": 0.013, "holdings": 505},
        {"symbol": "IVV", "name": "iShares Core S&P 500 ETF", "issuer": "BlackRock", "category": "US Large Blend", "aum_usd": 460_000_000_000, "expenseRatio": 0.0003, "ytd_return_pct": 8.5, "dividend_yield": 0.013, "holdings": 505},
        {"symbol": "SPLG", "name": "SPDR Portfolio S&P 500 ETF", "issuer": "State Street", "category": "US Large Blend", "aum_usd": 45_000_000_000, "expenseRatio": 0.0002, "ytd_return_pct": 8.5, "dividend_yield": 0.012, "holdings": 503},
        {"symbol": "RSP", "name": "Invesco S&P 500 Equal Weight ETF", "issuer": "Invesco", "category": "US Large Blend", "aum_usd": 55_000_000_000, "expenseRatio": 0.002, "ytd_return_pct": 6.1, "dividend_yield": 0.017, "holdings": 503},
        {"symbol": "SCHX", "name": "Schwab U.S. Large-Cap ETF", "issuer": "Charles Schwab", "category": "US Large Blend", "aum_usd": 42_000_000_000, "expenseRatio": 0.0003, "ytd_return_pct": 8.4, "dividend_yield": 0.013, "holdings": 750},
        # US Large Growth
        {"symbol": "QQQ", "name": "Invesco QQQ Trust", "issuer": "Invesco", "category": "US Large Growth", "aum_usd": 250_000_000_000, "expenseRatio": 0.002, "ytd_return_pct": 10.4, "dividend_yield": 0.006, "holdings": 101},
        {"symbol": "VUG", "name": "Vanguard Growth ETF", "issuer": "Vanguard", "category": "US Large Growth", "aum_usd": 120_000_000_000, "expenseRatio": 0.0004, "ytd_return_pct": 10.1, "dividend_yield": 0.005, "holdings": 220},
        {"symbol": "IWF", "name": "iShares Russell 1000 Growth ETF", "issuer": "BlackRock", "category": "US Large Growth", "aum_usd": 85_000_000_000, "expenseRatio": 0.0019, "ytd_return_pct": 10.3, "dividend_yield": 0.005, "holdings": 450},
        {"symbol": "SCHG", "name": "Schwab U.S. Large-Cap Growth ETF", "issuer": "Charles Schwab", "category": "US Large Growth", "aum_usd": 28_000_000_000, "expenseRatio": 0.0004, "ytd_return_pct": 10.2, "dividend_yield": 0.004, "holdings": 250},
        {"symbol": "MGK", "name": "Vanguard Mega Cap Growth ETF", "issuer": "Vanguard", "category": "US Large Growth", "aum_usd": 18_000_000_000, "expenseRatio": 0.0007, "ytd_return_pct": 11.0, "dividend_yield": 0.004, "holdings": 70},
        # US Large Value
        {"symbol": "VTV", "name": "Vanguard Value ETF", "issuer": "Vanguard", "category": "US Large Value", "aum_usd": 130_000_000_000, "expenseRatio": 0.0004, "ytd_return_pct": 5.2, "dividend_yield": 0.023, "holdings": 340},
        {"symbol": "IWD", "name": "iShares Russell 1000 Value ETF", "issuer": "BlackRock", "category": "US Large Value", "aum_usd": 55_000_000_000, "expenseRatio": 0.0019, "ytd_return_pct": 5.4, "dividend_yield": 0.021, "holdings": 850},
        {"symbol": "SCHD", "name": "Schwab U.S. Dividend Equity ETF", "issuer": "Charles Schwab", "category": "US Large Value", "aum_usd": 65_000_000_000, "expenseRatio": 0.0006, "ytd_return_pct": 4.8, "dividend_yield": 0.037, "holdings": 100},
        {"symbol": "VYM", "name": "Vanguard High Dividend Yield ETF", "issuer": "Vanguard", "category": "US Large Value", "aum_usd": 60_000_000_000, "expenseRatio": 0.0006, "ytd_return_pct": 5.6, "dividend_yield": 0.026, "holdings": 550},
        {"symbol": "DVY", "name": "iShares Select Dividend ETF", "issuer": "BlackRock", "category": "US Large Value", "aum_usd": 20_000_000_000, "expenseRatio": 0.0038, "ytd_return_pct": 4.2, "dividend_yield": 0.039, "holdings": 100},
        # US Total Market
        {"symbol": "VTI", "name": "Vanguard Total Stock Market ETF", "issuer": "Vanguard", "category": "US Total Market", "aum_usd": 380_000_000_000, "expenseRatio": 0.0003, "ytd_return_pct": 7.9, "dividend_yield": 0.014, "holdings": 3700},
        {"symbol": "ITOT", "name": "iShares Core S&P Total U.S. Stock Market ETF", "issuer": "BlackRock", "category": "US Total Market", "aum_usd": 55_000_000_000, "expenseRatio": 0.0003, "ytd_return_pct": 7.8, "dividend_yield": 0.014, "holdings": 3600},
        {"symbol": "SCHB", "name": "Schwab U.S. Broad Market ETF", "issuer": "Charles Schwab", "category": "US Total Market", "aum_usd": 30_000_000_000, "expenseRatio": 0.0003, "ytd_return_pct": 7.8, "dividend_yield": 0.013, "holdings": 2400},
        # US Mid Blend
        {"symbol": "IJH", "name": "iShares Core S&P Mid-Cap ETF", "issuer": "BlackRock", "category": "US Mid Blend", "aum_usd": 90_000_000_000, "expenseRatio": 0.0005, "ytd_return_pct": 4.9, "dividend_yield": 0.015, "holdings": 400},
        {"symbol": "VO", "name": "Vanguard Mid-Cap ETF", "issuer": "Vanguard", "category": "US Mid Blend", "aum_usd": 75_000_000_000, "expenseRatio": 0.0004, "ytd_return_pct": 5.1, "dividend_yield": 0.015, "holdings": 340},
        {"symbol": "SCHM", "name": "Schwab U.S. Mid-Cap ETF", "issuer": "Charles Schwab", "category": "US Mid Blend", "aum_usd": 12_000_000_000, "expenseRatio": 0.0004, "ytd_return_pct": 4.7, "dividend_yield": 0.013, "holdings": 500},
        # US Small Blend
        {"symbol": "IWM", "name": "iShares Russell 2000 ETF", "issuer": "BlackRock", "category": "US Small Blend", "aum_usd": 70_000_000_000, "expenseRatio": 0.0019, "ytd_return_pct": 3.1, "dividend_yield": 0.012, "holdings": 1980},
        {"symbol": "VB", "name": "Vanguard Small-Cap ETF", "issuer": "Vanguard", "category": "US Small Blend", "aum_usd": 65_000_000_000, "expenseRatio": 0.0005, "ytd_return_pct": 3.6, "dividend_yield": 0.014, "holdings": 1400},
        {"symbol": "IJR", "name": "iShares Core S&P Small-Cap ETF", "issuer": "BlackRock", "category": "US Small Blend", "aum_usd": 85_000_000_000, "expenseRatio": 0.0006, "ytd_return_pct": 2.4, "dividend_yield": 0.013, "holdings": 600},
        {"symbol": "SPSM", "name": "SPDR Portfolio S&P 600 Small Cap ETF", "issuer": "State Street", "category": "US Small Blend", "aum_usd": 12_000_000_000, "expenseRatio": 0.0003, "ytd_return_pct": 2.5, "dividend_yield": 0.013, "holdings": 600},
        # US Small Value
        {"symbol": "VBR", "name": "Vanguard Small-Cap Value ETF", "issuer": "Vanguard", "category": "US Small Value", "aum_usd": 30_000_000_000, "expenseRatio": 0.0007, "ytd_return_pct": 2.9, "dividend_yield": 0.021, "holdings": 850},
        {"symbol": "AVUV", "name": "Avantis U.S. Small Cap Value ETF", "issuer": "Avantis", "category": "US Small Value", "aum_usd": 14_000_000_000, "expenseRatio": 0.0025, "ytd_return_pct": 1.8, "dividend_yield": 0.017, "holdings": 750},
        # Emerging Markets
        {"symbol": "EEM", "name": "iShares MSCI Emerging Markets ETF", "issuer": "BlackRock", "category": "Emerging Markets", "aum_usd": 20_000_000_000, "expenseRatio": 0.0068, "ytd_return_pct": 5.2, "dividend_yield": 0.021, "holdings": 1200},
        {"symbol": "VWO", "name": "Vanguard FTSE Emerging Markets ETF", "issuer": "Vanguard", "category": "Emerging Markets", "aum_usd": 85_000_000_000, "expenseRatio": 0.0008, "ytd_return_pct": 5.5, "dividend_yield": 0.027, "holdings": 4500},
        {"symbol": "IEMG", "name": "iShares Core MSCI Emerging Markets ETF", "issuer": "BlackRock", "category": "Emerging Markets", "aum_usd": 80_000_000_000, "expenseRatio": 0.0009, "ytd_return_pct": 5.4, "dividend_yield": 0.025, "holdings": 2500},
        {"symbol": "SCHE", "name": "Schwab Emerging Markets Equity ETF", "issuer": "Charles Schwab", "category": "Emerging Markets", "aum_usd": 9_000_000_000, "expenseRatio": 0.0011, "ytd_return_pct": 5.3, "dividend_yield": 0.027, "holdings": 1600},
        # International Developed
        {"symbol": "EFA", "name": "iShares MSCI EAFE ETF", "issuer": "BlackRock", "category": "International Developed", "aum_usd": 55_000_000_000, "expenseRatio": 0.0033, "ytd_return_pct": 6.8, "dividend_yield": 0.028, "holdings": 750},
        {"symbol": "VEA", "name": "Vanguard FTSE Developed Markets ETF", "issuer": "Vanguard", "category": "International Developed", "aum_usd": 140_000_000_000, "expenseRatio": 0.0005, "ytd_return_pct": 6.9, "dividend_yield": 0.03, "holdings": 4000},
        {"symbol": "IEFA", "name": "iShares Core MSCI EAFE ETF", "issuer": "BlackRock", "category": "International Developed", "aum_usd": 120_000_000_000, "expenseRatio": 0.0007, "ytd_return_pct": 6.9, "dividend_yield": 0.028, "holdings": 2900},
        {"symbol": "SCHF", "name": "Schwab International Equity ETF", "issuer": "Charles Schwab", "category": "International Developed", "aum_usd": 40_000_000_000, "expenseRatio": 0.0006, "ytd_return_pct": 6.9, "dividend_yield": 0.028, "holdings": 1500},
        # Commodity Precious Metals
        {"symbol": "GLD", "name": "SPDR Gold Shares", "issuer": "State Street", "category": "Commodity Precious Metals", "aum_usd": 58_000_000_000, "expenseRatio": 0.004, "ytd_return_pct": 12.4, "dividend_yield": 0.0, "holdings": 1},
        {"symbol": "IAU", "name": "iShares Gold Trust", "issuer": "BlackRock", "category": "Commodity Precious Metals", "aum_usd": 32_000_000_000, "expenseRatio": 0.0025, "ytd_return_pct": 12.5, "dividend_yield": 0.0, "holdings": 1},
        {"symbol": "SLV", "name": "iShares Silver Trust", "issuer": "BlackRock", "category": "Commodity Precious Metals", "aum_usd": 13_000_000_000, "expenseRatio": 0.005, "ytd_return_pct": 14.8, "dividend_yield": 0.0, "holdings": 1},
        {"symbol": "PPLT", "name": "abrdn Physical Platinum Shares ETF", "issuer": "abrdn", "category": "Commodity Precious Metals", "aum_usd": 1_200_000_000, "expenseRatio": 0.006, "ytd_return_pct": 9.1, "dividend_yield": 0.0, "holdings": 1},
        # Long Government
        {"symbol": "TLT", "name": "iShares 20+ Year Treasury Bond ETF", "issuer": "BlackRock", "category": "Long Government", "aum_usd": 55_000_000_000, "expenseRatio": 0.0015, "ytd_return_pct": -2.8, "dividend_yield": 0.039, "holdings": 45},
        {"symbol": "TLH", "name": "iShares 10-20 Year Treasury Bond ETF", "issuer": "BlackRock", "category": "Long Government", "aum_usd": 7_000_000_000, "expenseRatio": 0.0015, "ytd_return_pct": -1.9, "dividend_yield": 0.04, "holdings": 30},
        {"symbol": "VGLT", "name": "Vanguard Long-Term Treasury ETF", "issuer": "Vanguard", "category": "Long Government", "aum_usd": 15_000_000_000, "expenseRatio": 0.0004, "ytd_return_pct": -2.6, "dividend_yield": 0.045, "holdings": 90},
        {"symbol": "EDV", "name": "Vanguard Extended Duration Treasury ETF", "issuer": "Vanguard", "category": "Long Government", "aum_usd": 4_000_000_000, "expenseRatio": 0.0006, "ytd_return_pct": -4.1, "dividend_yield": 0.047, "holdings": 80},
        {"symbol": "GOVT", "name": "iShares U.S. Treasury Bond ETF", "issuer": "BlackRock", "category": "Long Government", "aum_usd": 30_000_000_000, "expenseRatio": 0.0005, "ytd_return_pct": 1.2, "dividend_yield": 0.041, "holdings": 160},
        # Intermediate Government
        {"symbol": "IEF", "name": "iShares 7-10 Year Treasury Bond ETF", "issuer": "BlackRock", "category": "Intermediate Government", "aum_usd": 35_000_000_000, "expenseRatio": 0.0015, "ytd_return_pct": 0.9, "dividend_yield": 0.04, "holdings": 15},
        {"symbol": "IEI", "name": "iShares 3-7 Year Treasury Bond ETF", "issuer": "BlackRock", "category": "Intermediate Government", "aum_usd": 14_000_000_000, "expenseRatio": 0.0015, "ytd_return_pct": 1.6, "dividend_yield": 0.041, "holdings": 15},
        {"symbol": "VGIT", "name": "Vanguard Intermediate-Term Treasury ETF", "issuer": "Vanguard", "category": "Intermediate Government", "aum_usd": 25_000_000_000, "expenseRatio": 0.0004, "ytd_return_pct": 1.5, "dividend_yield": 0.04, "holdings": 120},
        # Short Government
        {"symbol": "SHY", "name": "iShares 1-3 Year Treasury Bond ETF", "issuer": "BlackRock", "category": "Short Government", "aum_usd": 25_000_000_000, "expenseRatio": 0.0015, "ytd_return_pct": 2.4, "dividend_yield": 0.043, "holdings": 40},
        {"symbol": "VGSH", "name": "Vanguard Short-Term Treasury ETF", "issuer": "Vanguard", "category": "Short Government", "aum_usd": 20_000_000_000, "expenseRatio": 0.0004, "ytd_return_pct": 2.5, "dividend_yield": 0.043, "holdings": 100},
        {"symbol": "BIL", "name": "SPDR Bloomberg 1-3 Month T-Bill ETF", "issuer": "State Street", "category": "Short Government", "aum_usd": 40_000_000_000, "expenseRatio": 0.001359, "ytd_return_pct": 2.9, "dividend_yield": 0.046, "holdings": 20},
        # High Yield Bond
        {"symbol": "HYG", "name": "iShares iBoxx High Yield Corporate Bond ETF", "issuer": "BlackRock", "category": "High Yield Bond", "aum_usd": 16_000_000_000, "expenseRatio": 0.0049, "ytd_return_pct": 3.7, "dividend_yield": 0.058, "holdings": 1200},
        {"symbol": "JNK", "name": "SPDR Bloomberg High Yield Bond ETF", "issuer": "State Street", "category": "High Yield Bond", "aum_usd": 8_000_000_000, "expenseRatio": 0.004, "ytd_return_pct": 3.6, "dividend_yield": 0.06, "holdings": 1000},
        {"symbol": "USHY", "name": "iShares Broad USD High Yield Corporate Bond ETF", "issuer": "BlackRock", "category": "High Yield Bond", "aum_usd": 15_000_000_000, "expenseRatio": 0.0022, "ytd_return_pct": 3.8, "dividend_yield": 0.06, "holdings": 1900},
        {"symbol": "SJNK", "name": "SPDR Bloomberg Short Term High Yield Bond ETF", "issuer": "State Street", "category": "High Yield Bond", "aum_usd": 4_000_000_000, "expenseRatio": 0.004, "ytd_return_pct": 3.4, "dividend_yield": 0.062, "holdings": 800},
        # Aggregate Bond
        {"symbol": "AGG", "name": "iShares Core U.S. Aggregate Bond ETF", "issuer": "BlackRock", "category": "Aggregate Bond", "aum_usd": 110_000_000_000, "expenseRatio": 0.0003, "ytd_return_pct": 2.1, "dividend_yield": 0.038, "holdings": 12000},
        {"symbol": "BND", "name": "Vanguard Total Bond Market ETF", "issuer": "Vanguard", "category": "Aggregate Bond", "aum_usd": 130_000_000_000, "expenseRatio": 0.0003, "ytd_return_pct": 2.0, "dividend_yield": 0.038, "holdings": 11000},
        # International Bond
        {"symbol": "BNDX", "name": "Vanguard Total International Bond ETF", "issuer": "Vanguard", "category": "International Bond", "aum_usd": 60_000_000_000, "expenseRatio": 0.0007, "ytd_return_pct": 1.4, "dividend_yield": 0.03, "holdings": 8000},
        {"symbol": "IAGG", "name": "iShares Core International Aggregate Bond ETF", "issuer": "BlackRock", "category": "International Bond", "aum_usd": 5_000_000_000, "expenseRatio": 0.0007, "ytd_return_pct": 1.3, "dividend_yield": 0.031, "holdings": 4000},
        # TIPS
        {"symbol": "SCHP", "name": "Schwab U.S. TIPS ETF", "issuer": "Charles Schwab", "category": "TIPS", "aum_usd": 14_000_000_000, "expenseRatio": 0.0003, "ytd_return_pct": 3.2, "dividend_yield": 0.029, "holdings": 50},
        {"symbol": "TIP", "name": "iShares TIPS Bond ETF", "issuer": "BlackRock", "category": "TIPS", "aum_usd": 20_000_000_000, "expenseRatio": 0.0018, "ytd_return_pct": 3.1, "dividend_yield": 0.032, "holdings": 50},
        {"symbol": "VTIP", "name": "Vanguard Short-Term Inflation-Protected Securities ETF", "issuer": "Vanguard", "category": "TIPS", "aum_usd": 15_000_000_000, "expenseRatio": 0.0004, "ytd_return_pct": 2.8, "dividend_yield": 0.03, "holdings": 30},
        # Municipal Bond
        {"symbol": "MUB", "name": "iShares National Muni Bond ETF", "issuer": "BlackRock", "category": "Municipal Bond", "aum_usd": 38_000_000_000, "expenseRatio": 0.0007, "ytd_return_pct": 1.8, "dividend_yield": 0.028, "holdings": 6000},
        {"symbol": "VTEB", "name": "Vanguard Tax-Exempt Bond ETF", "issuer": "Vanguard", "category": "Municipal Bond", "aum_usd": 35_000_000_000, "expenseRatio": 0.0005, "ytd_return_pct": 1.7, "dividend_yield": 0.03, "holdings": 5500},
        # Closed-End Fund
        {"symbol": "ADX", "name": "Adams Diversified Equity Fund", "issuer": "Adams Funds", "category": "Closed-End Fund", "aum_usd": 2_700_000_000, "expenseRatio": 0.0057, "ytd_return_pct": 9.2, "dividend_yield": 0.062, "holdings": 100},
        {"symbol": "GAB", "name": "Gabelli Equity Trust", "issuer": "GAMCO", "category": "Closed-End Fund", "aum_usd": 1_700_000_000, "expenseRatio": 0.0062, "ytd_return_pct": 7.8, "dividend_yield": 0.09, "holdings": 250},
        {"symbol": "CET", "name": "Central Securities Corporation", "issuer": "Central Securities", "category": "Closed-End Fund", "aum_usd": 1_400_000_000, "expenseRatio": 0.0071, "ytd_return_pct": 8.1, "dividend_yield": 0.02, "holdings": 70},
        {"symbol": "RVT", "name": "Royce Value Trust", "issuer": "Royce & Associates", "category": "Closed-End Fund", "aum_usd": 1_800_000_000, "expenseRatio": 0.011, "ytd_return_pct": 6.4, "dividend_yield": 0.08, "holdings": 350},
    ]


def _bond_reference_rows() -> list[dict[str, Any]]:
    """Curated global sovereign / TIPS curve universe (25 rows).

    Yields and durations are curated reference values; the keyless US
    Treasury daily par-yield curve refreshes the US tenor yields on the live
    path (see ``_US_TREASURY_CURVE_COLUMNS``). No breakeven rows are shipped:
    the wired provider exposes a nominal curve only, so a breakeven column
    would be fabricated rather than measured.
    """
    return [
        # US nominal curve (live-refreshable tenors)
        {"symbol": "US3M", "issuer": "US Treasury", "type": "Bill", "country": "US", "currency": "USD", "maturity": "3M", "tenor_years": 0.25, "yield": 5.32, "duration": 0.24, "rating": "AA+"},
        {"symbol": "US6M", "issuer": "US Treasury", "type": "Bill", "country": "US", "currency": "USD", "maturity": "6M", "tenor_years": 0.5, "yield": 5.15, "duration": 0.49, "rating": "AA+"},
        {"symbol": "US1Y", "issuer": "US Treasury", "type": "Note", "country": "US", "currency": "USD", "maturity": "1Y", "tenor_years": 1.0, "yield": 4.95, "duration": 0.96, "rating": "AA+"},
        {"symbol": "US2Y", "issuer": "US Treasury", "type": "Note", "country": "US", "currency": "USD", "maturity": "2Y", "tenor_years": 2.0, "yield": 4.62, "duration": 1.9, "rating": "AA+"},
        {"symbol": "US3Y", "issuer": "US Treasury", "type": "Note", "country": "US", "currency": "USD", "maturity": "3Y", "tenor_years": 3.0, "yield": 4.52, "duration": 2.8, "rating": "AA+"},
        {"symbol": "US5Y", "issuer": "US Treasury", "type": "Note", "country": "US", "currency": "USD", "maturity": "5Y", "tenor_years": 5.0, "yield": 4.48, "duration": 4.5, "rating": "AA+"},
        {"symbol": "US7Y", "issuer": "US Treasury", "type": "Note", "country": "US", "currency": "USD", "maturity": "7Y", "tenor_years": 7.0, "yield": 4.46, "duration": 6.1, "rating": "AA+"},
        {"symbol": "US10Y", "issuer": "US Treasury", "type": "Note", "country": "US", "currency": "USD", "maturity": "10Y", "tenor_years": 10.0, "yield": 4.45, "duration": 8.2, "rating": "AA+"},
        {"symbol": "US20Y", "issuer": "US Treasury", "type": "Bond", "country": "US", "currency": "USD", "maturity": "20Y", "tenor_years": 20.0, "yield": 4.66, "duration": 13.5, "rating": "AA+"},
        {"symbol": "US30Y", "issuer": "US Treasury", "type": "Bond", "country": "US", "currency": "USD", "maturity": "30Y", "tenor_years": 30.0, "yield": 4.58, "duration": 17.6, "rating": "AA+"},
        # US TIPS (real yields; reference — no keyless real-yield provider wired)
        {"symbol": "USTIPS5Y", "issuer": "US Treasury", "type": "TIPS", "country": "US", "currency": "USD", "maturity": "5Y", "tenor_years": 5.0, "yield": 1.95, "duration": 4.6, "rating": "AA+"},
        {"symbol": "USTIPS10Y", "issuer": "US Treasury", "type": "TIPS", "country": "US", "currency": "USD", "maturity": "10Y", "tenor_years": 10.0, "yield": 2.05, "duration": 8.4, "rating": "AA+"},
        {"symbol": "USTIPS30Y", "issuer": "US Treasury", "type": "TIPS", "country": "US", "currency": "USD", "maturity": "30Y", "tenor_years": 30.0, "yield": 2.25, "duration": 17.0, "rating": "AA+"},
        # Euro area
        {"symbol": "DE2Y", "issuer": "Germany", "type": "Bund", "country": "DE", "currency": "EUR", "maturity": "2Y", "tenor_years": 2.0, "yield": 2.85, "duration": 1.9, "rating": "AAA"},
        {"symbol": "DE10Y", "issuer": "Germany", "type": "Bund", "country": "DE", "currency": "EUR", "maturity": "10Y", "tenor_years": 10.0, "yield": 2.42, "duration": 8.8, "rating": "AAA"},
        {"symbol": "FR2Y", "issuer": "France", "type": "OAT", "country": "FR", "currency": "EUR", "maturity": "2Y", "tenor_years": 2.0, "yield": 2.95, "duration": 1.9, "rating": "AA"},
        {"symbol": "FR10Y", "issuer": "France", "type": "OAT", "country": "FR", "currency": "EUR", "maturity": "10Y", "tenor_years": 10.0, "yield": 3.05, "duration": 8.3, "rating": "AA"},
        {"symbol": "IT2Y", "issuer": "Italy", "type": "BTP", "country": "IT", "currency": "EUR", "maturity": "2Y", "tenor_years": 2.0, "yield": 3.25, "duration": 1.9, "rating": "BBB"},
        {"symbol": "IT10Y", "issuer": "Italy", "type": "BTP", "country": "IT", "currency": "EUR", "maturity": "10Y", "tenor_years": 10.0, "yield": 3.85, "duration": 8.2, "rating": "BBB"},
        {"symbol": "ES2Y", "issuer": "Spain", "type": "Bono", "country": "ES", "currency": "EUR", "maturity": "2Y", "tenor_years": 2.0, "yield": 3.05, "duration": 1.9, "rating": "A"},
        {"symbol": "ES10Y", "issuer": "Spain", "type": "Bono", "country": "ES", "currency": "EUR", "maturity": "10Y", "tenor_years": 10.0, "yield": 3.35, "duration": 8.3, "rating": "A"},
        # United Kingdom
        {"symbol": "GB2Y", "issuer": "United Kingdom", "type": "Gilt", "country": "GB", "currency": "GBP", "maturity": "2Y", "tenor_years": 2.0, "yield": 4.35, "duration": 1.9, "rating": "AA"},
        {"symbol": "GB10Y", "issuer": "United Kingdom", "type": "Gilt", "country": "GB", "currency": "GBP", "maturity": "10Y", "tenor_years": 10.0, "yield": 4.12, "duration": 8.4, "rating": "AA"},
        # Japan
        {"symbol": "JP2Y", "issuer": "Japan", "type": "JGB", "country": "JP", "currency": "JPY", "maturity": "2Y", "tenor_years": 2.0, "yield": 0.35, "duration": 1.95, "rating": "A+"},
        {"symbol": "JP10Y", "issuer": "Japan", "type": "JGB", "country": "JP", "currency": "JPY", "maturity": "10Y", "tenor_years": 10.0, "yield": 0.88, "duration": 9.4, "rating": "A+"},
    ]


_SECURITY_MASTER_CACHE: list[dict[str, Any]] | None = None
_SECURITY_MASTER_PATH = (
    Path(__file__).resolve().parents[2] / "reference" / "data" / "security_master.json"
)


def _load_security_master() -> list[dict[str, Any]]:
    """Bundled SECF master (S&P 500 scale) with a memoized read.

    Falls back to the curated reference list when the generated
    ``security_master.json`` is missing or unreadable.
    """
    global _SECURITY_MASTER_CACHE
    if _SECURITY_MASTER_CACHE is None:
        _SECURITY_MASTER_CACHE = _read_security_master()
    return [dict(row) for row in _SECURITY_MASTER_CACHE]


def _read_security_master() -> list[dict[str, Any]]:
    try:
        payload = json.loads(_SECURITY_MASTER_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _security_fallback_rows()
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return _security_fallback_rows()
    master = [dict(row) for row in rows if isinstance(row, dict) and row.get("symbol")]
    return master or _security_fallback_rows()


def _security_fallback_rows() -> list[dict[str, Any]]:
    return [dict(row) for row in _SECURITY_FALLBACK_ROWS]


def _security_reference_rows() -> list[dict[str, Any]]:
    return _load_security_master()


_SECURITY_FALLBACK_ROWS = [
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


async def _batch_quote_rows(
    provider: Any,
    symbols: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """One batched quote call when the provider supports it.

    Yahoo's batch quote endpoint returns last/change for hundreds of symbols
    in a handful of calls (``fetch_refdata_batch`` on the yfinance adapter);
    the per-symbol fan-out (``_quote_rows``) only completes ~11 within a
    screen budget because of the provider's shared 2 rps token bucket.
    Returns ``([], [])`` when the provider has no batch support so callers
    fall back to ``_quote_rows`` unchanged.
    """
    batch = getattr(provider, "fetch_refdata_batch", None)
    if not callable(batch):
        return [], []
    try:
        payload = await batch(symbols)
    except Exception as exc:  # noqa: BLE001 — caller falls back per symbol
        return [], [str(exc) or type(exc).__name__]
    rows: list[dict[str, Any]] = []
    for symbol, raw in (payload or {}).items():
        if not isinstance(raw, dict):
            continue
        last = _batch_number(raw.get("regularMarketPrice"))
        if last is None:
            continue
        prev = _batch_number(raw.get("regularMarketPreviousClose"))
        change_pct = _batch_number(raw.get("regularMarketChangePercent"))
        if change_pct is None and prev not in (None, 0):
            change_pct = (last / prev - 1.0) * 100.0
        volume = _batch_number(raw.get("regularMarketVolume"))
        rows.append({
            "symbol": str(symbol).upper(),
            "last": last,
            "prev_close": prev,
            "change": (last - prev) if prev is not None else None,
            "volume": volume,
            "dollar_volume": (last * volume) if volume is not None else None,
            "change_pct": change_pct,
            "high": None,
            "low": None,
            "range_pct": None,
        })
    return rows, []


def _batch_number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


async def _quote_rows(
    provider: Any,
    symbols: list[str],
    *,
    asset_class: AssetClass | None = None,
    timeout: float,
    screen_timeout: float,
    concurrency: int | None = None,
    burst: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fan out one QUOTE request per symbol under a screen-level budget.

    ``concurrency`` bounds how many requests are in flight at once;
    ``burst`` lets the provider skip its own token bucket for this
    bounded fan-out (see :func:`_quote_row`). Both default to the legacy
    unbounded/rate-limited behaviour so existing callers are unchanged.
    """
    semaphore = (
        asyncio.Semaphore(concurrency)
        if concurrency is not None and concurrency > 0
        else None
    )

    async def _run(symbol: str) -> dict[str, Any] | None:
        if semaphore is None:
            return await _quote_row(provider, symbol, asset_class, timeout, burst=burst)
        async with semaphore:
            return await _quote_row(provider, symbol, asset_class, timeout, burst=burst)

    tasks = [asyncio.create_task(_run(symbol)) for symbol in symbols]
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
    *,
    burst: bool = False,
) -> dict[str, Any] | None:
    inst = Instrument(symbol=symbol, asset_class=asset_class or _asset_for_screen_symbol(symbol))
    budget = max(1.0, min(timeout, 4.0))
    extra: dict[str, Any] = {"timeout": budget}
    if burst:
        # Bounded fan-out callers (WEI world indices) opt out of the
        # provider's shared token bucket: the bucket wait used to sit
        # inside this call's latency budget, so symbols queued past the
        # first few timed out before their turn. Concurrency is capped
        # caller-side instead; the average request rate stays well under
        # the bucket's nominal rate.
        extra["bypass_rate_limit"] = True
    quote = await asyncio.wait_for(
        provider.fetch(
            DataRequest(
                kind=DataKind.QUOTE,
                instrument=inst,
                extra=extra,
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


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _snapshot_to_quote_row(symbol: str, snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Map a ``showme.quotes`` snapshot into the screen quote-row schema.

    The snapshot service does not publish intraday high/low for every
    provider, so those fields stay ``None`` (the pane prints em-dashes)
    instead of being back-filled from a different window.
    """
    last = _finite_number(snapshot.get("last"))
    if last is None:
        return None
    prev = _finite_number(snapshot.get("previous_close"))
    if prev in (None, 0):
        change = None
        change_pct = _finite_number(snapshot.get("change_pct"))
    else:
        change = last - prev
        change_pct = (last / prev - 1.0) * 100.0
    volume = _finite_number(snapshot.get("volume"))
    dollar_volume = float(last) * volume if volume is not None else None
    return {
        "symbol": symbol,
        "last": last,
        "prev_close": prev,
        "change": change,
        "volume": volume,
        "dollar_volume": dollar_volume,
        "change_pct": change_pct,
        "high": None,
        "low": None,
        "range_pct": None,
    }


def _screen_uses_live_quote_service(provider: Any) -> bool:
    """True when the wired provider is the bundled yfinance adapter.

    Production wires ``YFinanceAdapter`` (or its OHLCV-wrapper proxy, which
    forwards ``.name``) — its per-symbol QUOTE path races a heavyweight
    1-minute Yahoo chart against Stooq, which does not scale to a 60+ symbol
    screen. In that case the fan-out uses the fast keyless
    ``showme.quotes.fetch_quote_snapshot`` service (one lightweight Yahoo
    chart call per symbol + process-wide TTL cache). Injected fakes keep the
    legacy adapter path untouched.
    """
    return getattr(provider, "name", None) == "yfinance"


async def _quote_snapshot_rows(
    symbols: list[str],
    *,
    screen_timeout: float,
    concurrency: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Bounded fan-out of the fast keyless quote service (WEI pattern)."""
    from showme.quotes import fetch_quote_snapshot, quote_cache_get, quote_cache_set

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _run(symbol: str) -> dict[str, Any] | None:
        async with semaphore:
            snapshot = quote_cache_get(symbol)
            if snapshot is None:
                try:
                    snapshot = await fetch_quote_snapshot(symbol)
                except Exception:  # noqa: BLE001 — unresolved symbols are labelled upstream
                    return None
                quote_cache_set(symbol, snapshot)
            return _snapshot_to_quote_row(symbol, snapshot)

    tasks = [asyncio.create_task(_run(symbol)) for symbol in symbols]
    done, pending = await asyncio.wait(tasks, timeout=screen_timeout)
    for task in pending:
        task.cancel()
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for task in done:
        try:
            row = task.result()
        except Exception as exc:  # noqa: BLE001
            warnings.append(str(exc) or type(exc).__name__)
            continue
        if row:
            rows.append(row)
    if pending:
        warnings.append(f"{len(pending)} quote request(s) exceeded {screen_timeout:.1f}s")
    return rows, [warning for warning in warnings if warning][:4]


async def _screen_quote_rows(
    provider: Any,
    symbols: list[str],
    *,
    timeout: float,
    screen_timeout: float,
    concurrency: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Quote fan-out for a screen universe (live service or injected provider)."""
    if _screen_uses_live_quote_service(provider):
        return await _quote_snapshot_rows(
            symbols,
            screen_timeout=screen_timeout,
            concurrency=concurrency,
        )
    return await _quote_rows(
        provider,
        symbols,
        timeout=timeout,
        screen_timeout=screen_timeout,
        concurrency=concurrency,
        burst=True,
    )


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


def _utc_now_iso() -> str:
    """Server-side data-fetch timestamp (UTC, ISO-8601).

    Gives the UI a *real* data-freshness anchor instead of the client
    wall clock, which can drift from when the snapshot was actually built.
    """
    return datetime.now(timezone.utc).isoformat()


# ── MOST — expanded cross-asset universes ─────────────────────────────────
# Every generated symbol below was probed live via GET /api/quote/<SYMBOL>
# on the public Yahoo chart provider from this machine (2026-09-15) and
# returned a finite last price. Verified-rejected (do NOT re-add without a
# fresh probe): BRK.B (404 — the provider serves the class share as BRK-B).
_MOST_ACTIVE_LEGACY_ROWS: tuple[dict[str, Any], ...] = (
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
)

# Liquid S&P 500 subset scanned by the live equities tab (bounded: the pane
# polls every 30s and the public quote provider has no batched Yahoo quote
# path in this repo — 61 names at bounded concurrency stays inside the
# function latency budget). Name/exchange come from the bundled security
# master at call time.
_MOST_EQUITY_SYMBOLS: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM",
    "LLY", "V", "UNH", "XOM", "MA", "COST", "HD", "PG", "JNJ", "WMT", "ABBV",
    "NFLX", "BAC", "KO", "CRM", "ORCL", "MRK", "CVX", "AMD", "PEP", "TMO",
    "ADBE", "LIN", "MCD", "CSCO", "ACN", "ABT", "WFC", "QCOM", "INTU", "TXN",
    "DHR", "VZ", "AMGN", "CAT", "IBM", "NOW", "GE", "PM", "ISRG", "SPGI",
    "UBER", "GS", "RTX", "T", "NEE", "PFE", "BLK", "MS", "HON", "UNP", "BKNG",
)

# G10 + major EM pairs (Yahoo "=X" form). All probed live 2026-09-15.
_MOST_FX_PAIRS: tuple[str, ...] = (
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "USDTRY", "USDCNH", "USDMXN",
    "USDZAR", "USDSEK", "USDNOK", "USDPLN", "USDHUF", "USDILS", "USDINR",
    "USDSGD", "USDHKD", "USDKRW", "USDBRL", "USDARS", "EURTRY", "GBPTRY",
    "GBPCHF", "EURCHF",
)
_MOST_FX_SYMBOLS: tuple[str, ...] = tuple(f"{pair}=X" for pair in _MOST_FX_PAIRS)

_CURRENCY_NAMES: dict[str, str] = {
    "USD": "US Dollar", "EUR": "Euro", "GBP": "British Pound",
    "JPY": "Japanese Yen", "CHF": "Swiss Franc", "CAD": "Canadian Dollar",
    "AUD": "Australian Dollar", "NZD": "New Zealand Dollar",
    "TRY": "Turkish Lira", "CNH": "Offshore Yuan", "MXN": "Mexican Peso",
    "ZAR": "South African Rand", "SEK": "Swedish Krona",
    "NOK": "Norwegian Krone", "PLN": "Polish Zloty", "HUF": "Hungarian Forint",
    "ILS": "Israeli Shekel", "INR": "Indian Rupee", "SGD": "Singapore Dollar",
    "HKD": "Hong Kong Dollar", "KRW": "South Korean Won",
    "BRL": "Brazilian Real", "ARS": "Argentine Peso",
}


def _most_active_equity_rows() -> list[dict[str, Any]]:
    master = {str(row.get("symbol") or "").upper(): row for row in _security_reference_rows()}
    rows: list[dict[str, Any]] = []
    for symbol in _MOST_EQUITY_SYMBOLS:
        ref = master.get(symbol.upper(), {})
        rows.append({
            "symbol": symbol,
            "name": ref.get("name") or symbol,
            "asset_class": "equity",
            "exchange": ref.get("exchange") or "US",
        })
    return rows


def _most_active_etf_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ref in _security_reference_rows():
        if str(ref.get("asset_class") or "").upper() != "ETF":
            continue
        symbol = str(ref.get("symbol") or "")
        if not symbol:
            continue
        rows.append({
            "symbol": symbol,
            "name": ref.get("name") or symbol,
            "asset_class": "etf",
            "exchange": ref.get("exchange") or "US",
        })
    return rows


def _most_active_fx_rows() -> list[dict[str, Any]]:
    master = {str(row.get("symbol") or "").upper(): row for row in _security_reference_rows()}
    rows: list[dict[str, Any]] = []
    for symbol in _MOST_FX_SYMBOLS:
        pair = symbol[: -len("=X")]
        base, quote = pair[:3], pair[3:]
        ref = master.get(pair, {})
        name = ref.get("name") or (
            f"{_CURRENCY_NAMES.get(base, base)} / {_CURRENCY_NAMES.get(quote, quote)}"
        )
        rows.append({
            "symbol": symbol,
            "name": name,
            "asset_class": "fx",
            "exchange": ref.get("exchange") or "FX",
        })
    return rows


def _most_active_crypto_rows() -> list[dict[str, Any]]:
    """Static USDT fallback board — replaced by the live Binance batch when it answers."""
    rows: list[dict[str, Any]] = []
    for ref in _security_reference_rows():
        if str(ref.get("asset_class") or "").upper() != "CRYPTO":
            continue
        symbol = str(ref.get("symbol") or "").upper()
        if not symbol:
            continue
        rows.append({
            "symbol": symbol,
            "name": ref.get("name") or symbol,
            "asset_class": "crypto",
            "exchange": ref.get("exchange") or "BINANCE",
        })
    return rows


def _most_active_reference_rows() -> list[dict[str, Any]]:
    """Full MOST universe: curated legacy rows + security-master expansion.

    Deduped by symbol with the legacy rows winning so their curated values
    (where present) survive; generated rows carry identity fields only and
    receive market data from the live scan or read as explicit unavailable
    rows — never fabricated.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in (
        *_MOST_ACTIVE_LEGACY_ROWS,
        *_most_active_equity_rows(),
        *_most_active_etf_rows(),
        *_most_active_fx_rows(),
        *_most_active_crypto_rows(),
    ):
        symbol = str(row.get("symbol") or "").upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(dict(row))
    return out


# ── MOST — live crypto board via ONE batched Binance call ─────────────────
_BINANCE_TICKER_24H_URL = "https://api.binance.com/api/v3/ticker/24hr"
_MOST_CRYPTO_SCAN_LIMIT = 60
_MOST_CRYPTO_CACHE_TTL_S = 60.0
_MOST_CRYPTO_HTTP_TIMEOUT_S = 5.0
_MOST_CRYPTO_CACHE: dict[str, Any] = {"at": 0.0, "rows": []}
_MOST_CRYPTO_BASE_NAMES: dict[str, str] = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "BNB": "BNB",
    "XRP": "XRP", "DOGE": "Dogecoin", "ADA": "Cardano", "AVAX": "Avalanche",
    "LINK": "Chainlink", "LTC": "Litecoin", "DOT": "Polkadot", "UNI": "Uniswap",
    "TRX": "TRON", "SHIB": "Shiba Inu", "PEPE": "Pepe", "TON": "Toncoin",
    "SUI": "Sui", "APT": "Aptos", "NEAR": "NEAR Protocol", "BCH": "Bitcoin Cash",
    "ETC": "Ethereum Classic", "FIL": "Filecoin", "ATOM": "Cosmos",
    "ICP": "Internet Computer", "ARB": "Arbitrum", "OP": "Optimism",
    "INJ": "Injective", "TIA": "Celestia", "SEI": "Sei", "STX": "Stacks",
}
# Quote-fiat bases are not crypto movers: strip them from the board.
_MOST_CRYPTO_QUOTE_BASES = frozenset({"USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "USD1", "USDE", "XUSD", "EUR"})


def _most_active_crypto_row_from_ticker(item: dict[str, Any]) -> dict[str, Any] | None:
    symbol = str(item.get("symbol") or "").upper()
    if not symbol.endswith("USDT"):
        return None
    base = symbol[: -len("USDT")]
    if not base or base in _MOST_CRYPTO_QUOTE_BASES or base.endswith(("UP", "DOWN", "BULL", "BEAR")):
        return None
    try:
        last = float(item.get("lastPrice"))
        prev_close = float(item.get("openPrice"))
        volume = float(item.get("volume"))
        quote_volume = float(item.get("quoteVolume"))
        change_pct = float(item.get("priceChangePercent"))
        high = float(item.get("highPrice"))
        low = float(item.get("lowPrice"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(last) or last <= 0:
        return None
    name = _MOST_CRYPTO_BASE_NAMES.get(base, base)
    return {
        "symbol": symbol,
        "name": f"{name} / USDT",
        "asset_class": "crypto",
        "exchange": "BINANCE",
        "last": last,
        "prev_close": prev_close,
        "change": last - prev_close,
        "volume": volume,
        "dollar_volume": quote_volume,
        "change_pct": change_pct,
        "high": high,
        "low": low,
        "range_pct": ((high - low) / last * 100.0) if last else None,
        "quote_state": "live",
        "source": "binance",
    }


async def _binance_top_crypto_rows(limit: int = _MOST_CRYPTO_SCAN_LIMIT) -> list[dict[str, Any]]:
    """Top USDT spot pairs by 24h quote volume from ONE batched Binance call.

    ``GET /api/v3/ticker/24hr`` without a symbol returns every spot ticker in
    a single response, so ranking the crypto tab costs one HTTP round-trip.
    A 60s process-local cache absorbs repeated pane polls; any provider
    failure returns ``[]`` so the caller falls back to the static fallback
    board instead of fabricating an empty tab.
    """
    now = time.monotonic()
    cached = _MOST_CRYPTO_CACHE.get("rows") or []
    if cached and now - float(_MOST_CRYPTO_CACHE.get("at") or 0.0) < _MOST_CRYPTO_CACHE_TTL_S:
        return [dict(row) for row in cached[:limit]]
    try:
        from showme.providers._http import get_client

        client = await get_client()
        response = await asyncio.wait_for(
            client.get(_BINANCE_TICKER_24H_URL),
            timeout=_MOST_CRYPTO_HTTP_TIMEOUT_S,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:  # noqa: BLE001 — outage degrades to the yfinance fallback
        return []
    rows: list[dict[str, Any]] = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        row = _most_active_crypto_row_from_ticker(item)
        if row:
            rows.append(row)
    rows.sort(key=lambda row: float(row.get("dollar_volume") or 0.0), reverse=True)
    rows = rows[:limit]
    if rows:
        _MOST_CRYPTO_CACHE["at"] = now
        _MOST_CRYPTO_CACHE["rows"] = [dict(row) for row in rows]
    return rows


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


_MOST_IDENTITY_FIELDS = ("symbol", "name", "asset_class", "exchange")


def _merge_live_most_rows(
    reference_rows: list[dict[str, Any]],
    quote_rows: list[dict[str, Any]],
    *,
    keep_unresolved: bool = False,
) -> list[dict[str, Any]]:
    """Merge provider quotes into the scanned universe.

    ``keep_unresolved=True`` (the live screen path) emits every scanned
    symbol: rows the provider did not return inside the budget become
    explicit ``quote_state="unavailable"`` rows with null market fields —
    identity fields are preserved, curated reference prices are NOT carried
    into a live board, and nothing is silently dropped. The default
    (``False``) keeps the legacy "live rows only" behaviour used by callers
    that merge a fixed reference table by hand.
    """
    quote_by_symbol = {str(row.get("symbol") or "").upper(): row for row in quote_rows}
    out: list[dict[str, Any]] = []
    for row in reference_rows:
        symbol = str(row.get("symbol") or "").upper()
        quote = quote_by_symbol.get(symbol)
        if quote:
            merged = {**row, **quote, "quote_state": "live"}
            if merged.get("dollar_volume") is None:
                last = merged.get("last")
                volume = merged.get("volume")
                if last is not None and volume is not None:
                    merged["dollar_volume"] = float(last) * float(volume)
            out.append(merged)
            continue
        if not keep_unresolved:
            continue
        identity = {field: row[field] for field in _MOST_IDENTITY_FIELDS if field in row}
        out.append({
            **identity,
            "last": None,
            "prev_close": None,
            "change": None,
            "volume": None,
            "dollar_volume": None,
            "change_pct": None,
            "high": None,
            "low": None,
            "range_pct": None,
            "quote_state": "unavailable",
        })
    return out


def _rank_most_active_rows(rows: list[dict[str, Any]], sort_key: str) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        merged = dict(row)
        # Self-describing rows: deterministic (non-live) reference rows carry
        # quote_state="reference". setdefault never clobbers the "live" state
        # stamped by _merge_live_most_rows, so the shared live path is safe.
        merged.setdefault("quote_state", "reference")
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
    scanned: int | None = None,
    resolved: int | None = None,
    unavailable: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
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
            "or approximate traded notional. Dollar volume is last price multiplied by session/24h volume. "
            "Crypto ranks the Binance USDT spot board by 24h quote volume from one batched ticker call; "
            "equities/ETFs scan a bounded liquid subset of the bundled security master and FX covers the "
            "G10 + major EM pairs — every scanned symbol the provider does not answer inside the latency "
            "budget is emitted as an explicit quote_state=unavailable row (null values, never dropped)."
        ),
        "field_dictionary": _MOST_FIELDS,
    }
    if scanned is not None:
        payload["scanned"] = scanned
        payload["resolved"] = resolved
        payload["unavailable"] = unavailable
    return payload


# Curated world-equity-index meta. Every live-eligible entry below was
# verified to resolve with a finite last price from this machine on the
# public Yahoo quote provider (2026-09-15 probe via /api/quote and the
# yfinance adapter). The set is the single source of truth for both the
# live universe and the deterministic fallback template — keep them
# derived from this map so they never drift.
#
# Verified-rejected on the provider (do NOT re-add without a fresh probe):
# OMXC25.CO (404), TASI.SR / ^TASI (404 — Saudi Arabia), ^ATG (no last),
# ^BUX (no last), ^KSE (no last), ^CSE (no last).
_WORLD_INDEX_META: dict[str, dict[str, str]] = {
    # Americas
    "^GSPC": {"name": "S&P 500", "region": "americas"},
    "^DJI": {"name": "Dow Jones Industrial Average", "region": "americas"},
    "^IXIC": {"name": "Nasdaq Composite", "region": "americas"},
    "^RUT": {"name": "Russell 2000", "region": "americas"},
    "^GSPTSE": {"name": "S&P/TSX Composite (Canada)", "region": "americas"},
    "^BVSP": {"name": "Bovespa (Brazil)", "region": "americas"},
    "^MXX": {"name": "IPC (Mexico)", "region": "americas"},
    # Europe
    "^FTSE": {"name": "FTSE 100", "region": "europe"},
    "^GDAXI": {"name": "DAX", "region": "europe"},
    "^FCHI": {"name": "CAC 40", "region": "europe"},
    "^STOXX50E": {"name": "Euro Stoxx 50", "region": "europe"},
    "^IBEX": {"name": "IBEX 35 (Spain)", "region": "europe"},
    "^AEX": {"name": "AEX (Netherlands)", "region": "europe"},
    "^SSMI": {"name": "SMI (Switzerland)", "region": "europe"},
    "FTSEMIB.MI": {"name": "FTSE MIB (Italy)", "region": "europe"},
    "^OMX": {"name": "OMX Stockholm 30 (Sweden)", "region": "europe"},
    "WIG20.WA": {"name": "WIG 20 (Poland)", "region": "europe"},
    "^BFX": {"name": "BEL 20 (Belgium)", "region": "europe"},
    "OBX.OL": {"name": "OBX 25 (Norway)", "region": "europe"},
    # Asia
    "^N225": {"name": "Nikkei 225", "region": "asia"},
    "^HSI": {"name": "Hang Seng", "region": "asia"},
    "^KS11": {"name": "KOSPI (Korea)", "region": "asia"},
    "^TWII": {"name": "TAIEX (Taiwan)", "region": "asia"},
    "^BSESN": {"name": "BSE Sensex (India)", "region": "asia"},
    "^NSEI": {"name": "Nifty 50 (India)", "region": "asia"},
    "^AXJO": {"name": "S&P/ASX 200 (Australia)", "region": "asia"},
    "000001.SS": {"name": "SSE Composite (Shanghai)", "region": "asia"},
    "399001.SZ": {"name": "Shenzhen Component", "region": "asia"},
    "^STI": {"name": "Straits Times (Singapore)", "region": "asia"},
    "^KLSE": {"name": "FTSE Bursa Malaysia KLCI", "region": "asia"},
    "^JKSE": {"name": "Jakarta Composite (Indonesia)", "region": "asia"},
    "^SET": {"name": "SET Index (Thailand)", "region": "asia"},
    "PSEI.PS": {"name": "PSEi (Philippines)", "region": "asia"},
    "^NZ50": {"name": "NZX 50 (New Zealand)", "region": "asia"},
    # MEA
    "XU100.IS": {"name": "BIST 100 (Turkey)", "region": "mea"},
    "^TA125.TA": {"name": "TA-125 (Israel)", "region": "mea"},
    "^J203.JO": {"name": "JSE All Share (South Africa)", "region": "mea"},
    "^CASE30": {"name": "EGX 30 (Egypt)", "region": "mea"},
}

# Deterministic baseline levels for the offline / provider-down template.
# Coarse round numbers — these are explicitly NOT live quotes (rows carry
# market_state="model"); they exist only so the UI has structure to show
# while clearly labelled as model data.
_WORLD_INDEX_BASELINE: dict[str, float] = {
    "^GSPC": 5200.0, "^DJI": 39000.0, "^IXIC": 16500.0, "^RUT": 2050.0,
    "^GSPTSE": 22000.0, "^BVSP": 128000.0, "^MXX": 56000.0,
    "^FTSE": 8200.0, "^GDAXI": 18400.0, "^FCHI": 8100.0, "^STOXX50E": 5000.0,
    "^IBEX": 11000.0, "^AEX": 900.0, "^SSMI": 12000.0, "FTSEMIB.MI": 34000.0,
    "^OMX": 2500.0, "WIG20.WA": 4100.0, "^BFX": 5720.0, "OBX.OL": 2035.0,
    "^N225": 39200.0, "^HSI": 18100.0, "^KS11": 2700.0, "^TWII": 22000.0,
    "^BSESN": 80000.0, "^NSEI": 24000.0, "^AXJO": 7800.0, "^STI": 3400.0,
    "^JKSE": 7200.0, "000001.SS": 3000.0, "^KLSE": 1600.0,
    "399001.SZ": 13300.0, "^SET": 7600.0, "PSEI.PS": 6010.0, "^NZ50": 13480.0,
    "XU100.IS": 9800.0, "^TA125.TA": 2000.0, "^J203.JO": 80000.0, "^CASE30": 28000.0,
}


def _world_index_symbols() -> list[str]:
    """Curated world-index universe (single source of truth).

    Order = insertion order of ``_WORLD_INDEX_META`` (region-grouped).
    """
    return list(_WORLD_INDEX_META.keys())


def _enrich_world_index_row(row: dict[str, Any]) -> dict[str, Any]:
    meta = _WORLD_INDEX_META.get(str(row.get("symbol") or "").upper(), {})
    return {
        **row,
        "name": row.get("name") or meta.get("name"),
        "region": row.get("region") or meta.get("region"),
        "market_state": row.get("market_state") or "live",
    }


def _complete_world_index_rows(quote_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge resolved quotes into the FULL curated universe (meta order).

    Symbols the provider did not return within the screen budget are
    emitted as explicit no-quote rows (``last=None``, ``market_state=
    "unavailable"``) instead of being silently dropped — the pane must
    paint the whole world board and label the missing quotes as missing.
    """
    by_symbol = {str(row.get("symbol") or "").upper(): row for row in quote_rows}
    rows: list[dict[str, Any]] = []
    for sym in _world_index_symbols():
        quote = by_symbol.get(sym.upper())
        if quote is not None:
            rows.append(_enrich_world_index_row(quote))
            continue
        meta = _WORLD_INDEX_META[sym]
        rows.append({
            "symbol": sym,
            "name": meta["name"],
            "region": meta["region"],
            "last": None,
            "prev_close": None,
            "change": None,
            "change_pct": None,
            "high": None,
            "low": None,
            "market_state": "unavailable",
        })
    return rows


def _world_index_template() -> list[dict[str, Any]]:
    """Deterministic offline / provider-down model for the full universe.

    Derived from ``_WORLD_INDEX_META`` so it never drifts from the live
    set. Every row is labelled ``market_state="model"`` — these are NOT
    live quotes and the UI must surface them as model data.
    """
    rows: list[dict[str, Any]] = []
    for sym in _world_index_symbols():
        meta = _WORLD_INDEX_META[sym]
        base = _WORLD_INDEX_BASELINE.get(sym, 1000.0)
        # Stable, deterministic pseudo-move from the symbol so the model
        # table isn't a wall of zeros, while staying clearly synthetic.
        seed = sum(ord(ch) for ch in sym)
        change_pct = round(((seed % 11) - 5) * 0.08, 2)
        last = round(base * (1 + change_pct / 100), 2)
        high = round(last * 1.004, 2)
        low = round(last * 0.996, 2)
        rows.append({
            "symbol": sym,
            "name": meta["name"],
            "region": meta["region"],
            "last": last,
            "change_pct": change_pct,
            "high": high,
            "low": low,
            "market_state": "model",
        })
    return rows
