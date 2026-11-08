"""BQL — Bloomberg Query Language (basit DSL).

Format:
    get(price, volume) for(['AAPL','MSFT']) with(start='2024-01-01', end='2024-12-31') by(date)

Bu sürüm parser'ı oldukça basit (regex tabanlı). Phase 7'de pyparsing/lark.

BQL returns provider data only. There is no offline price model: when live
mode is not requested the function reports ``provider_unavailable`` with no
rows, and a missing universe reports ``input_required`` (never a substitute
symbol).
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


_BLOCK = re.compile(r"(\w+)\s*\(([^)]*)\)")

# yfinance OHLCV columns BQL can serve, and the template-vocabulary aliases
# that BQL maps onto them (reported as a warning when used).
_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")
_FIELD_ALIASES = {"px_last": "close", "last": "close", "price": "close"}
_SEED_QUERY_KEYS = ("start", "end", "interval")


@dataclass
class BQLQuery:
    fields: list[str]
    universe: list[str]
    params: dict[str, Any]
    by: str | None = None


def parse_bql(text: str) -> BQLQuery:
    blocks = {m.group(1): m.group(2) for m in _BLOCK.finditer(text)}
    fields = [s.strip() for s in (blocks.get("get") or "").split(",") if s.strip()]
    raw_universe = (blocks.get("for") or "").strip()
    universe = []
    if raw_universe.startswith("["):
        raw_universe = raw_universe.strip("[]")
        universe = [s.strip().strip("'\"") for s in raw_universe.split(",") if s.strip()]
    params: dict[str, Any] = {}
    for kv in (blocks.get("with") or "").split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            params[k.strip()] = v.strip().strip("'\"")
    by = (blocks.get("by") or None)
    if by is not None:
        by = by.strip()
    return BQLQuery(fields=fields, universe=universe, params=params, by=by)


def _infer_asset_class(symbol: str) -> AssetClass:
    upper = symbol.upper()
    if upper.startswith("^"):
        return AssetClass.INDEX
    if upper.endswith("=F") or upper in {"XAUUSD", "XAGUSD", "WTI", "BRENT"}:
        return AssetClass.COMMODITY
    if upper.endswith("=X") or re.fullmatch(r"[A-Z]{6}", upper):
        return AssetClass.FX
    if any(upper.endswith(q) for q in ("USDT", "USDC", "USD", "-USD", "/USD")) and len(upper) > 6:
        return AssetClass.CRYPTO
    return AssetClass.EQUITY


def _default_universe(instrument: Instrument | None, params: dict[str, Any]) -> list[str]:
    """Universe when the query has no for([...]) clause.

    An explicit symbol from the caller (``__explicit_symbol``, set by the
    router) wins over the router's injected peer ``symbols`` default, so the
    pane's symbol is what gets queried. Otherwise the caller's own
    ``symbols``/``universe`` are used, then the instrument. An empty list
    means the caller must supply a universe; nothing is substituted.
    """
    if params.get("__explicit_symbol") and instrument and instrument.symbol:
        return [instrument.symbol]
    raw = params.get("symbols") or params.get("universe")
    if isinstance(raw, str):
        values = [s.strip() for s in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        values = [str(s).strip() for s in raw]
    else:
        values = []
    values = [s for s in values if s]
    if values:
        return values
    if instrument and instrument.symbol:
        return [instrument.symbol]
    symbol = str(params.get("symbol") or "").strip()
    return [symbol] if symbol else []


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _live_requested(params: dict[str, Any]) -> bool:
    """Live mode unless the caller explicitly turns it off.

    ``live_query`` (the seed input) takes precedence over ``live``, which the
    router injects as True by default. Explicit ``false`` values, including
    the string ``"false"`` from a GET query string, switch live mode off.
    """
    for key in ("live_query", "live"):
        value = params.get(key)
        if value is None or value == "":
            continue
        return _truthy(value)
    return True


def _apply_runtime_window(query: BQLQuery, params: dict[str, Any]) -> None:
    if query.params.get("start") or query.params.get("end") or query.params.get("period"):
        return
    try:
        days = int(params.get("days") or 90)
    except Exception:
        days = 90
    days = max(5, min(days, 365 * 5))
    query.params["period"] = f"{days}d"


def _limit_rows(rows: list[dict[str, Any]], limit: Any) -> list[dict[str, Any]]:
    # BQL#4: a caller limit is honoured as given (1..1000); it is no longer
    # raised to 10. An unreadable limit falls back to the 200-row default.
    try:
        n = int(limit)
    except Exception:
        n = 200
    n = max(1, min(n, 1000))
    if len(rows) <= n:
        return rows
    symbols = list(dict.fromkeys(str(row.get("symbol") or "") for row in rows))
    symbols = [symbol for symbol in symbols if symbol]
    if len(symbols) <= 1:
        return rows[-n:]
    per_symbol = max(1, n // len(symbols))
    grouped: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
    for row in rows:
        symbol = str(row.get("symbol") or "")
        if symbol in grouped:
            grouped[symbol].append(row)
    kept: list[dict[str, Any]] = []
    for symbol in symbols:
        kept.extend(grouped[symbol][-per_symbol:])
    return kept


def _history_rows(rows: list[dict[str, Any]], field: str = "close") -> list[dict[str, Any]]:
    first_symbol = next((str(row.get("symbol")) for row in rows if row.get("symbol")), "")
    out: list[dict[str, Any]] = []
    for row in rows:
        if first_symbol and str(row.get("symbol")) != first_symbol:
            continue
        value = row.get(field)
        if value is None:
            continue
        out.append({"date": row.get("date"), "symbol": row.get("symbol"), field: value})
    return out


def _format_payload(
    query: BQLQuery,
    rows: list[dict[str, Any]],
    mode: str,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    date_values = [str(row.get("date")) for row in rows if row.get("date")]
    field = next((f for f in query.fields if f.lower() in {"close", "px_last", "last", "price"}), query.fields[0])
    history = _history_rows(rows, field)
    return {
        "rows": rows,
        "history": history,
        "summary": {
            "mode": mode,
            "symbols": len(query.universe),
            "fields": ", ".join(query.fields),
            "rows": len(rows),
            "first_date": min(date_values) if date_values else None,
            "last_date": max(date_values) if date_values else None,
            "by": query.by or "date",
        },
        "query_plan": [
            {
                "step": "parse",
                "detail": "get(...) fields, for([...]) universe, with(...) date/period params, by(...) grouping parsed from the visible query.",
            },
            {
                "step": "fetch",
                "detail": "Live mode requests OHLCV rows from yfinance for each parsed symbol and requested period.",
            },
            {
                "step": "shape",
                "detail": "Returned rows are symbol/date records; chart history is the first symbol's selected price field.",
            },
        ],
        "methodology": (
            "ShowMe BQL is a constrained query DSL: get(field list) selects output columns, "
            "for(symbol list) defines the universe, with(period/start/end/interval) defines the time window, "
            "and by(date) requests date-level rows. It is intentionally limited to provider-backed market fields."
        ),
        "field_dictionary": {
            "query": "Visible DSL text sent to the backend.",
            "symbol": "Security identifier from the for([...]) universe.",
            "date": "Provider timestamp for the OHLCV row.",
            "close": "Closing price from the yfinance OHLCV row (px_last, last and price map to close).",
            "volume": "Provider-reported session volume.",
            "mode": "live when yfinance rows are returned; unavailable when no provider rows exist.",
        },
        "warnings": warnings or [],
    }


def _unavailable(q: BQLQuery, reason: str, next_actions: list[str], status: str = "provider_unavailable") -> FunctionResult:
    return FunctionResult(
        code=BQLFunction.code,
        instrument=None,
        data={
            "status": status,
            "reason": reason,
            "rows": [],
            "next_actions": next_actions,
        },
        sources=[],
        warnings=[],
        metadata={"parsed": q.__dict__, "rows": 0, "mode": "unavailable"},
    )


@FunctionRegistry.register
class BQLFunction(BaseFunction):
    code = "BQL"
    name = "ShowMe Query Language"
    category = "api"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        text = params.get("query") or ""
        q = parse_bql(text)
        if not q.universe:
            q.universe = _default_universe(instrument, params)
        if not q.fields:
            q.fields = ["close", "volume"]
        # Seed inputs for the time window and bar size apply unless the
        # query's own with(...) block sets them.
        for key in _SEED_QUERY_KEYS:
            value = params.get(key)
            if not q.params.get(key) and value not in (None, ""):
                q.params[key] = str(value).strip()
        _apply_runtime_window(q, params)
        if not _live_requested(params):
            return _unavailable(
                q,
                "BQL has no offline data model: live=false returns no rows. Only yfinance OHLCV is served.",
                ["Run the query with live set to true to read yfinance OHLCV rows."],
            )
        if not q.universe:
            return _unavailable(
                q,
                "BQL needs a universe: add for(['AAPL']) to the query or select an instrument.",
                ["Use query like get(close, volume) for(['AAPL']) with(period='1mo') by(date)."],
                status="input_required",
            )
        if not self.deps.yfinance:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "BQL live mode requires the yfinance provider.",
                    "rows": [],
                },
                sources=["yfinance"],
                warnings=["no yfinance"],
                metadata={"parsed": q.__dict__, "rows": 0, "mode": "unavailable"},
            )

        # Map requested fields onto yfinance OHLCV columns. Anything else is
        # reported, never silently dropped.
        field_column: dict[str, str] = {}
        field_warnings: list[str] = []
        for f in q.fields:
            key = f.lower()
            column = _FIELD_ALIASES.get(key, key)
            if column in _OHLCV_COLUMNS:
                field_column[f] = column
                if column != key:
                    field_warnings.append(f"{f}: mapped to yfinance {column}")
            else:
                field_warnings.append(
                    f"{f}: not provided by yfinance OHLCV (available: {', '.join(_OHLCV_COLUMNS)}); column omitted"
                )
        if not field_column:
            return _unavailable(
                q,
                "None of the requested fields are provided by yfinance OHLCV.",
                [f"Request fields from: {', '.join(_OHLCV_COLUMNS)}."],
                status="input_error",
            )

        from showme.engine.core.instrument import Instrument as I
        import asyncio
        # An explicit window (start and/or end) is sent as period1/period2. A
        # range period would silently replace it on the wire, so it is dropped.
        window_warnings: list[str] = []
        request_start = pd.to_datetime(q.params["start"]) if q.params.get("start") else None
        request_end = pd.to_datetime(q.params["end"]) if q.params.get("end") else None
        request_period: str | None = None
        if request_start is not None or request_end is not None:
            if q.params.get("period"):
                window_warnings.append(
                    f"period={q.params['period']}: ignored because start/end are set"
                )
            if request_start is None:
                # The yfinance adapter would fall back to a 6-month range and drop end.
                request_start = request_end - pd.Timedelta(days=180)
                window_warnings.append("end without start: window starts 180 days before end")
        else:
            request_period = q.params.get("period") or "1mo"
        tasks = [self.deps.yfinance.fetch(DataRequest(
            kind=DataKind.OHLCV,
            instrument=I(symbol=s, asset_class=_infer_asset_class(s)),
            start=request_start,
            end=request_end,
            interval=q.params.get("interval", "1d"),
            extra={"period": request_period, "timeout": float(params.get("yfinance_timeout", 6))},
        )) for s in q.universe]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        provider_errors: list[str] = []
        rows: list[dict[str, Any]] = []
        for sym, df in zip(q.universe, results):
            if isinstance(df, Exception) or df is None or df.empty:
                if isinstance(df, Exception):
                    provider_errors.append(f"{sym}: {df}")
                else:
                    provider_errors.append(f"{sym}: no rows")
                continue
            columns = {str(c).lower(): c for c in df.columns}
            for ts, row in df.iterrows():
                d = {"symbol": sym, "date": ts.isoformat()}
                for f, column in field_column.items():
                    source_col = columns.get(column)
                    if source_col is not None:
                        d[f] = float(row[source_col])
                rows.append(d)
        warnings = provider_errors + window_warnings + field_warnings
        # 200 rows is the default cap (the seed no longer declares a limit input).
        rows = _limit_rows(rows, params.get("limit", 200))
        if not rows:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "No live rows returned for the requested BQL universe.",
                    "rows": [],
                    "next_actions": [
                        "Use query like get(close, volume) for(['AAPL']) with(period='1mo') by(date).",
                        "For crypto, use Binance-style symbols such as BTCUSDT or Yahoo-style BTC-USD.",
                        "Increase timeout with params {\"live\":true,\"yfinance_timeout\":12}.",
                    ],
                },
                sources=["yfinance"],
                warnings=warnings,
                metadata={
                    "parsed": q.__dict__,
                    "rows": 0,
                    "mode": "unavailable",
                    "provider_errors": provider_errors,
                },
            )
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=_format_payload(q, rows, "live", warnings),
            sources=["yfinance"],
            warnings=warnings,
            metadata={"parsed": q.__dict__, "rows": len(rows), "mode": "live"},
        )
