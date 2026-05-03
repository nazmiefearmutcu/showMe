"""SRCH, FSRC, CSRC, SECF, MOST, WEI — screen suite."""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class SRCHFunction(BaseFunction):
    """SRCH — Bond Screener (alias of EQS pattern)."""
    code = "SRCH"
    name = "Bond Screener"
    asset_classes = (AssetClass.BOND,)
    category = "screen"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        rows = params.get("universe") or [
            {"symbol": "US10Y", "issuer": "US Treasury", "yield": 4.45, "duration": 8.2},
            {"symbol": "US2Y", "issuer": "US Treasury", "yield": 4.62, "duration": 1.9},
        ]
        return FunctionResult(code=self.code, instrument=None, data=rows,
                              sources=["bond_screener_baseline"])


@FunctionRegistry.register
class FSRCFunction(BaseFunction):
    """FSRC — Fund Screener."""
    code = "FSRC"
    name = "Fund Screener"
    asset_classes = (AssetClass.FUND, AssetClass.ETF)
    category = "screen"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        rows = params.get("universe") or [
            {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "aum_usd": 500_000_000_000},
            {"symbol": "QQQ", "name": "Invesco QQQ Trust", "aum_usd": 250_000_000_000},
        ]
        return FunctionResult(code=self.code, instrument=None, data=rows,
                              sources=["fund_screener_baseline"])


@FunctionRegistry.register
class CSRCFunction(BaseFunction):
    """CSRC — Commodity Screener."""
    code = "CSRC"
    name = "Commodity Screener"
    asset_classes = (AssetClass.COMMODITY,)
    category = "screen"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        rows = params.get("universe") or [
            {"symbol": "CL=F", "name": "WTI Crude", "sector": "Energy"},
            {"symbol": "GC=F", "name": "Gold", "sector": "Metals"},
            {"symbol": "NG=F", "name": "Natural Gas", "sector": "Energy"},
        ]
        return FunctionResult(code=self.code, instrument=None, data=rows,
                              sources=["commodity_screener_baseline"])


@FunctionRegistry.register
class SECFFunction(BaseFunction):
    """SECF — Security Finder (NL → query)."""
    code = "SECF"
    name = "Security Finder"
    category = "screen"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        nl_query = params.get("query", "")
        # Phase 7 LLM agent will translate NL → DSL. For now: direct DSL passthrough.
        from src.functions.equity.eqs import EQSFunction
        result = await EQSFunction(self.deps).execute(
            query=nl_query or "marketCap > 0",
            universe=params.get("universe"),
        )
        data = result.data
        sources = result.sources
        if _empty_result(data):
            data = [
                {"symbol": "AAPL", "name": "Apple Inc.", "asset_class": "EQUITY", "match": "security_finder_baseline"},
                {"symbol": "MSFT", "name": "Microsoft Corp.", "asset_class": "EQUITY", "match": "security_finder_baseline"},
                {"symbol": "BTCUSDT", "name": "Bitcoin / Tether", "asset_class": "CRYPTO", "match": "security_finder_baseline"},
            ]
            sources = ["security_finder_baseline"]
        return FunctionResult(
            code=self.code,
            instrument=result.instrument,
            data=data,
            metadata={**(result.metadata or {}), "alias_of": "EQS"},
            sources=sources,
        )


@FunctionRegistry.register
class MOSTFunction(BaseFunction):
    """MOST — Most Active (volume + |return| + range)."""
    code = "MOST"
    name = "Most Active"
    category = "screen"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        universe = params.get("universe") or [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
            "JPM", "V", "WMT", "PG", "DIS", "BTCUSDT", "ETHUSDT",
        ]
        live = _truthy(params.get("live_screen") or params.get("live"))
        if live and self.deps.yfinance:
            rows, warnings = await _quote_rows(
                self.deps.yfinance,
                [str(s).upper() for s in universe],
                timeout=_float_param(params, "quote_timeout", 4.0),
                screen_timeout=_float_param(params, "screen_timeout", 5.0),
            )
            if rows:
                rows.sort(
                    key=lambda x: (
                        x.get("volume") or 0,
                        abs(x.get("change_pct") or 0),
                    ),
                    reverse=True,
                )
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data=rows,
                    metadata={"live": True, "universe_size": len(universe)},
                    sources=["yfinance"],
                    warnings=warnings,
                )
        warnings = [] if not live else ["market data provider did not return a usable most-active snapshot within the latency budget"]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=_most_active_baseline(),
            metadata={"live": False, "universe_size": len(universe)},
            sources=["showme_local_baseline"],
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
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data=rows,
                    metadata={"live": True, "universe_size": len(indices)},
                    sources=["yfinance"],
                    warnings=warnings,
                )
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "World index quote provider returned no usable live rows.",
                    "rows": [],
                    "next_actions": [
                        "Retry WEI after the public quote provider recovers.",
                        "Run without live=true for the deterministic world-index template.",
                    ],
                },
                metadata={
                    "live": True,
                    "universe_size": len(indices),
                    "provider_errors": warnings or ["yfinance world index quotes unavailable"],
                },
                sources=["yfinance"],
                warnings=warnings,
            )
        warnings = [] if not live else ["market data provider did not return world-index quotes within the latency budget"]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=_world_index_template(),
            metadata={"live": False, "universe_size": len(indices)},
            sources=["showme_local_baseline"],
            warnings=warnings,
        )


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
            warnings.append(str(exc))
            continue
        if row:
            rows.append(row)
    if pending:
        warnings.append(f"{len(pending)} quote request(s) exceeded {screen_timeout:.1f}s")
    return rows, warnings[:4]


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
    change_pct = ((quote.last or 0) / (quote.close_prev or 1) - 1) * 100 if quote.close_prev else None
    high = quote.high_24h
    low = quote.low_24h
    range_pct = ((high or 0) - (low or 0)) / (quote.last or 1) * 100 if high is not None and low is not None else None
    return {
        "symbol": symbol,
        "last": quote.last,
        "volume": quote.volume_24h,
        "change_pct": change_pct,
        "high": high,
        "low": low,
        "range_pct": range_pct,
    }


def _asset_for_screen_symbol(symbol: str) -> AssetClass:
    s = symbol.upper()
    if s.startswith("^"):
        return AssetClass.INDEX
    if s.endswith("USDT") or s.endswith("USDC") or s.endswith("USD") and len(s) > 3:
        return AssetClass.CRYPTO
    if "=" in s:
        return AssetClass.COMMODITY
    return AssetClass.EQUITY


def _float_param(params: dict[str, Any], name: str, default: float) -> float:
    try:
        return float(params.get(name, default))
    except Exception:
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _most_active_baseline() -> list[dict[str, Any]]:
    return [
        {"symbol": "NVDA", "last": 920.0, "volume": 52_000_000, "change_pct": 1.24, "high": 928.0, "low": 906.0, "range_pct": 2.39},
        {"symbol": "TSLA", "last": 184.0, "volume": 96_000_000, "change_pct": -0.88, "high": 188.0, "low": 181.0, "range_pct": 3.8},
        {"symbol": "AAPL", "last": 185.0, "volume": 45_000_000, "change_pct": 0.32, "high": 187.2, "low": 183.4, "range_pct": 2.05},
        {"symbol": "MSFT", "last": 420.0, "volume": 24_000_000, "change_pct": 0.41, "high": 423.5, "low": 416.8, "range_pct": 1.6},
        {"symbol": "BTCUSDT", "last": 64000.0, "volume": 1_800_000_000, "change_pct": 0.76, "high": 64800.0, "low": 63100.0, "range_pct": 2.66},
        {"symbol": "ETHUSDT", "last": 3150.0, "volume": 980_000_000, "change_pct": 0.52, "high": 3204.0, "low": 3096.0, "range_pct": 3.43},
    ]


def _world_index_template() -> list[dict[str, Any]]:
    return [
        {"symbol": "^GSPC", "last": 5200.0, "change_pct": 0.18, "high": 5215.0, "low": 5178.0},
        {"symbol": "^DJI", "last": 39000.0, "change_pct": -0.05, "high": 39120.0, "low": 38860.0},
        {"symbol": "^IXIC", "last": 16500.0, "change_pct": 0.31, "high": 16590.0, "low": 16380.0},
        {"symbol": "^FTSE", "last": 8200.0, "change_pct": 0.12, "high": 8230.0, "low": 8160.0},
        {"symbol": "XU100.IS", "last": 9800.0, "change_pct": 0.44, "high": 9860.0, "low": 9720.0},
    ]
