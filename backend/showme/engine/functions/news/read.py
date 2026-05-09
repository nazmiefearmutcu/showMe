"""READ — Personalized News (portföy bazlı)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news.cn import CNFunction
from showme.engine.services.news_intelligence import article_timestamp


@FunctionRegistry.register
class READFunction(BaseFunction):
    code = "READ"
    name = "Personalized News (For You)"
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        watchlist: list[str] = params.get("watchlist") or ["AAPL", "MSFT", "BTCUSDT"]
        if isinstance(watchlist, str):
            watchlist = [s.strip() for s in watchlist.split(",") if s.strip()]
        max_age_days = _int_param(params.get("max_age_days", params.get("days", 14)), default=14, min_value=1, max_value=365)
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
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
            return symbol, await cn.execute(
                inst,
                limit=10,
                live=True,
                news_timeout=params.get("news_timeout", params.get("timeout", 8)),
            )

        batches = await asyncio.gather(*(_one(s) for s in watchlist), return_exceptions=True)
        for item in batches:
            if isinstance(item, Exception):
                continue
            s, res = item
            sources.extend(res.sources or [])
            for art in (res.data or []):
                if isinstance(art, dict):
                    if _is_unusable_placeholder(art):
                        continue
                    if _is_stale_article(art, cutoff):
                        continue
                    art["matched_symbol"] = s
                results.append(art)
        if not results:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": f"No live watchlist headlines newer than {max_age_days} day(s) were returned for the configured symbols.",
                    "articles": [],
                    "watchlist": watchlist,
                    "max_age_days": max_age_days,
                    "next_actions": [
                        "Edit the watchlist symbols and rerun READ.",
                        "Increase the Range control or retry with Deep enabled if RSS providers are sparse.",
                    ],
                },
                sources=list(dict.fromkeys(sources)) or ["no_live_source"],
                metadata={"watchlist": watchlist, "live": True, "max_age_days": max_age_days},
            )
        results.sort(key=_article_sort_key, reverse=True)
        return FunctionResult(code=self.code, instrument=None, data=results[:100],
                              sources=list(dict.fromkeys(sources)) or ["watchlist_cache"],
                              metadata={
                                  "watchlist": watchlist,
                                  "live": True,
                                  "max_age_days": max_age_days,
                                  "personalization": "watchlist_symbol_match_v2",
                              })


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int_param(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(min_value, min(parsed, max_value))


def _asset_class_for(symbol: str) -> AssetClass:
    value = str(symbol).upper()
    if value.endswith(("USDT", "USDC")) or value in {"BTC", "ETH", "SOL"}:
        return AssetClass.CRYPTO
    if len(value) == 6 and value[:3].isalpha() and value[3:].isalpha():
        return AssetClass.FX
    if value.endswith("=F"):
        return AssetClass.COMMODITY
    return AssetClass.EQUITY


def _is_unusable_placeholder(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").lower()
    source = str(row.get("source") or "").lower()
    title = str(row.get("title") or "").lower()
    return (
        status in {"news_feed_empty", "provider_unavailable", "unavailable"}
        or source in {"watchlist_cache", "showme"}
        or "news feed unavailable" in title
    )


def _is_stale_article(row: dict[str, Any], cutoff: datetime) -> bool:
    ts = article_timestamp(row)
    if ts is None:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts < cutoff


def _article_sort_key(row: dict[str, Any]) -> datetime:
    return article_timestamp(row) or datetime.min.replace(tzinfo=timezone.utc)
