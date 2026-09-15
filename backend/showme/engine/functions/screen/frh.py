"""FRH — Funding Rate Heatmap (perpetual futures, multi-exchange).

Top crypto perpetual futures için funding rate snapshot.
Source: Binance, Bybit, OKX REST endpoints.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


def _truthy(value: Any) -> bool:
    """Treat ``"false"``/``"0"``/``""`` strings as False — matches EVTS/FA/FLY/FTS."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


_DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "TRXUSDT", "DOTUSDT",
    "MATICUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "TIAUSDT",
    "SUIUSDT", "APTUSDT", "NEARUSDT", "FILUSDT", "ATOMUSDT",
    "LTCUSDT", "ETCUSDT", "BCHUSDT", "UNIUSDT",
]


_BINANCE_TICKER_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"
_RANKING_TTL_S = 600.0
_ranking_cache: tuple[float, list[str]] | None = None


async def _binance_ranked_symbols(client: Any) -> list[str] | None:
    """Top USDT perpetuals by 24h quote volume — ``None`` on any failure."""
    try:
        r = await client.get(_BINANCE_TICKER_URL)
        if r.status_code != 200:
            return None
        items = r.json() or []
        ranked = sorted(
            (
                item for item in items
                if isinstance(item, dict)
                and str(item.get("symbol", "")).endswith("USDT")
            ),
            key=lambda item: float(item.get("quoteVolume", 0) or 0),
            reverse=True,
        )
        symbols = [str(item["symbol"]).upper() for item in ranked]
        return symbols or None
    except Exception:
        return None


async def _symbol_universe(client: Any, limit: int) -> list[str]:
    """Default 25-symbol list, expanded from Binance's volume ranking when asked."""
    global _ranking_cache
    if limit <= len(_DEFAULT_SYMBOLS):
        return _DEFAULT_SYMBOLS[:limit]
    cached = _ranking_cache
    if cached is not None:
        ts, ranked = cached
        if time.monotonic() - ts < _RANKING_TTL_S and len(ranked) >= limit:
            return ranked[:limit]
    ranked = await _binance_ranked_symbols(client)
    if ranked is None:
        return _DEFAULT_SYMBOLS[:limit]
    _ranking_cache = (time.monotonic(), ranked)
    return ranked[:limit]


async def _binance_funding(client: httpx.AsyncClient, symbol: str) -> float | None:
    try:
        r = await client.get("https://fapi.binance.com/fapi/v1/premiumIndex",
                              params={"symbol": symbol})
        if r.status_code == 200:
            return float((r.json() or {}).get("lastFundingRate", 0))
    except Exception:
        return None
    return None


async def _bybit_funding(client: httpx.AsyncClient, symbol: str) -> float | None:
    try:
        r = await client.get("https://api.bybit.com/v5/market/tickers",
                              params={"category": "linear", "symbol": symbol})
        if r.status_code == 200:
            items = ((r.json() or {}).get("result") or {}).get("list") or []
            if items:
                return float(items[0].get("fundingRate", 0) or 0)
    except Exception:
        return None
    return None


async def _okx_funding(client: httpx.AsyncClient, symbol: str) -> float | None:
    try:
        # OKX uses BTC-USDT-SWAP
        if symbol.endswith("USDT"):
            inst = symbol[:-4] + "-USDT-SWAP"
        else:
            return None
        r = await client.get("https://www.okx.com/api/v5/public/funding-rate",
                              params={"instId": inst})
        if r.status_code == 200:
            items = (r.json() or {}).get("data") or []
            if items:
                return float(items[0].get("fundingRate", 0) or 0)
    except Exception:
        return None
    return None


@FunctionRegistry.register
class FRHFunction(BaseFunction):
    code = "FRH"
    name = "Funding Rate Heatmap"
    category = "screen"
    description = "Perpetual funding rates across Binance / Bybit / OKX."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        raw_symbols = params.get("symbols")
        if isinstance(raw_symbols, str):
            explicit = [s.strip().upper() for s in raw_symbols.split(",") if s.strip()]
        elif raw_symbols:
            explicit = [str(s).upper() for s in raw_symbols]
        else:
            explicit = []
        raw_limit = int(params.get("limit") or 0)
        limit = max(1, min(raw_limit or len(explicit) or len(_DEFAULT_SYMBOLS), 100))
        # FRH is always live: the keyless Binance/Bybit/OKX endpoints are the
        # only source (the labelled model template was removed 2026-09-15).
        client = getattr(self, "_http_client", None)
        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(timeout=float(params.get("funding_timeout", 6)))
        try:
            symbols = explicit[:limit] if explicit else await _symbol_universe(client, limit)
            rows = await self._fetch_live_rows(client, symbols)
        finally:
            if owns_client:
                await client.aclose()
        usable = [row for row in rows if row.get("avg") is not None]
        if not usable:
            # Provider-exhausted envelope: REAL provider names stay visible
            # for diagnostics, but the failure semantics keep the sanitizer
            # from ever labelling this payload LIVE (L5 loophole fix).
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "Funding rate providers returned no usable rates.",
                    "rows": [],
                    "surface": [],
                    "exchanges": ["binance", "bybit", "okx"],
                    "unit": "funding_rate_fraction_per_interval",
                    "next_actions": [
                        "Retry FRH after the public futures exchanges recover.",
                        "Verify outbound network access to fapi.binance.com, api.bybit.com, and www.okx.com.",
                    ],
                    "methodology": (
                        "FRH fetches current perpetual funding from Binance, Bybit, "
                        "and OKX. No usable rates returned on this attempt."
                    ),
                },
                sources=["binance", "bybit", "okx"],
                warnings=["binance/bybit/okx funding rates unavailable"],
                metadata={
                    "fallback": True,
                    "degraded": True,
                    "live": False,
                    "data_mode": "provider_unavailable",
                },
            )
        missing = [str(row.get("symbol")) for row in rows if row.get("avg") is None]
        warnings = (
            [f"{len(missing)} symbol(s) had no funding data: {', '.join(missing[:4])}"]
            if missing
            else []
        )
        usable.sort(key=lambda x: -(x.get("avg") or 0))
        return FunctionResult(
            code=self.code, instrument=None,
            data=_payload(usable, live=True), sources=["binance", "bybit", "okx"],
            warnings=warnings,
            metadata={
                "note": "Positive funding => longs paying shorts.",
                "samples": len(usable),
                "unit": "fraction per funding interval",
                "live": True,
                "data_mode": "live_exchange",
            },
        )

    async def _fetch_live_rows(self, client: Any, symbols: list[str]) -> list[dict[str, Any]]:
        async def _per_symbol(sym: str) -> dict[str, Any]:
            rates = await asyncio.gather(
                _binance_funding(client, sym),
                _bybit_funding(client, sym),
                _okx_funding(client, sym),
                return_exceptions=True,
            )
            row: dict[str, Any] = {"symbol": sym}
            for ex_name, val in zip(("binance", "bybit", "okx"), rates):
                row[ex_name] = (None if isinstance(val, Exception) else val)
            non_null = [v for v in (row["binance"], row["bybit"], row["okx"])
                         if isinstance(v, (int, float))]
            row["avg"] = sum(non_null) / len(non_null) if non_null else None
            row["rate"] = row["avg"]
            row["interpretation"] = _interpret_funding(row["avg"])
            row["provider_count"] = len(non_null)
            return row

        rows = await asyncio.gather(*(_per_symbol(s) for s in symbols))
        return list(rows)


def _interpret_funding(rate: Any) -> str:
    if not isinstance(rate, (int, float)):
        return "missing"
    if rate >= 0.0005:
        return "crowded longs"
    if rate <= -0.0005:
        return "short pressure"
    if rate > 0:
        return "longs pay shorts"
    if rate < 0:
        return "shorts pay longs"
    return "neutral"


def _payload(rows: list[dict[str, Any]], *, live: bool) -> dict[str, Any]:
    return {
        "surface": rows,
        "rows": rows,
        "exchanges": ["binance", "bybit", "okx"],
        "unit": "funding_rate_fraction_per_interval",
        "live": live,
        "methodology": (
            "Fetches current perpetual funding from Binance, Bybit, and OKX. "
            "rate/avg is the cross-exchange average; positive means longs pay shorts, "
            "negative means shorts pay longs."
        ),
    }
