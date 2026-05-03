"""READ — Personalized News (portföy bazlı)."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.functions.news.cn import CNFunction


@FunctionRegistry.register
class READFunction(BaseFunction):
    code = "READ"
    name = "Personalized News (For You)"
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        watchlist: list[str] = params.get("watchlist") or ["AAPL", "MSFT", "BTCUSDT"]
        if isinstance(watchlist, str):
            watchlist = [s.strip() for s in watchlist.split(",") if s.strip()]
        if not _truthy(params.get("live_news") or params.get("live")):
            results = [
                {"title": f"{s} watchlist brief", "matched_symbol": s,
                 "source": "watchlist_cache", "url": None}
                for s in watchlist[:10]
            ]
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=results,
                sources=["watchlist_cache"],
                metadata={"watchlist": watchlist, "live": False},
            )
        results: list = []
        sources: list[str] = []
        cn = CNFunction(self.deps)

        async def _one(symbol: str) -> tuple[str, Any]:
            inst = Instrument(symbol=symbol.upper(), asset_class=_asset_class_for(symbol))
            return symbol, await cn.execute(inst, limit=10, news_timeout=params.get("timeout", 8))

        batches = await asyncio.gather(*(_one(s) for s in watchlist), return_exceptions=True)
        for item in batches:
            if isinstance(item, Exception):
                continue
            s, res = item
            sources.extend(res.sources or [])
            for art in (res.data or []):
                if isinstance(art, dict):
                    art["matched_symbol"] = s
                results.append(art)
        if not results:
            results = [
                {"title": f"{s} watchlist brief", "matched_symbol": s,
                 "source": "watchlist_cache", "url": None}
                for s in watchlist[:10]
            ]
        results.sort(key=lambda x: str(x.get("seendate") or ""), reverse=True)
        return FunctionResult(code=self.code, instrument=None, data=results[:100],
                              sources=list(dict.fromkeys(sources)) or ["watchlist_cache"],
                              metadata={"watchlist": watchlist})


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _asset_class_for(symbol: str) -> AssetClass:
    value = str(symbol).upper()
    if value.endswith(("USDT", "USDC")) or value in {"BTC", "ETH", "SOL"}:
        return AssetClass.CRYPTO
    if len(value) == 6 and value[:3].isalpha() and value[3:].isalpha():
        return AssetClass.FX
    if value.endswith("=F"):
        return AssetClass.COMMODITY
    return AssetClass.EQUITY
