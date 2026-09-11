"""FRH — Funding Rate Heatmap (perpetual futures, multi-exchange).

Top crypto perpetual futures için funding rate snapshot.
Source: Binance, Bybit, OKX REST endpoints.
"""

from __future__ import annotations

import asyncio
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


def _funding_template(symbols: list[str]) -> list[dict[str, Any]]:
    rows = []
    for i, symbol in enumerate(symbols):
        avg = round((i % 7 - 3) * 0.00005, 7)
        rows.append({
            "symbol": symbol,
            "binance": avg,
            "bybit": round(avg * 0.9, 7),
            "okx": round(avg * 1.1, 7),
            "avg": avg,
            "rate": avg,
            "interpretation": _interpret_funding(avg),
        })
    rows.sort(key=lambda x: -(x.get("avg") or 0))
    return rows


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
    description = "Perpetual funding rates across Binance / Bybit / OKX (top 25 pairs)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbols = params.get("symbols") or _DEFAULT_SYMBOLS
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
        symbols = [str(s).upper() for s in symbols]
        limit = max(1, min(int(params.get("limit", len(symbols)) or len(symbols)), 100))
        symbols = symbols[:limit]
        # Default polarity (2026-09-11, L5): the keyless Binance/Bybit/OKX
        # endpoints are the DEFAULT. An explicit falsy ``live``/``live_funding``
        # (or ``reference=true``) opts back into the labelled model template.
        reference = _truthy(params.get("reference"))
        live_param_present = (
            params.get("live") is not None or params.get("live_funding") is not None
        )
        live_requested = (
            _truthy(params.get("live_funding") or params.get("live"))
            if live_param_present
            else True
        )
        if reference or not live_requested:
            rows = _funding_template(symbols)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_payload(rows, live=False),
                sources=["funding_rate_model"],
                metadata={
                    "note": "Positive funding => longs paying shorts.",
                    "samples": len(rows),
                    "unit": "fraction per funding interval",
                    "live": False,
                    "data_mode": "modeled",
                },
            )
        client = getattr(self, "_http_client", None)
        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(timeout=float(params.get("funding_timeout", 6)))
        try:
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
                        "Run with reference=true for the labelled funding model.",
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
