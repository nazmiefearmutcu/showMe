"""TOP — Top News (multi-source aggregator)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument
from src.services.news_intelligence import article_timestamp, critical_articles, enrich_articles, symbol_terms


@FunctionRegistry.register
class TOPFunction(BaseFunction):
    code = "TOP"
    name = "Top News"
    asset_classes = ()  # global
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        limit = int(params.get("limit", 50))
        query = params.get("query") or "market"
        max_age_days = _int_param(params.get("max_age_days", params.get("days", 45)), default=45, min_value=1, max_value=365)
        explicit_symbol = bool(params.get("__explicit_symbol"))
        symbol = (instrument.symbol if instrument and explicit_symbol else params.get("symbol") or "").upper()
        asset_class = str(
            params.get("asset_class")
            or getattr(getattr(instrument, "asset_class", None), "value", "")
            or ""
        ).upper()
        results: list[dict[str, Any]] = []
        sources: list[str] = []
        warnings: list[str] = []
        source_order = ["rss"]
        if params.get("include_gdelt") or params.get("deep"):
            source_order.append("gdelt")
        for src_name in source_order:
            src = getattr(self.deps, src_name, None)
            if src is None:
                continue
            try:
                extra: dict[str, Any] = {
                    "feed_group": "crypto" if asset_class == "CRYPTO" else "market",
                    "asset_class": asset_class,
                    "symbol": symbol,
                    "collection_timeout_seconds": min(float(params.get("news_timeout", params.get("timeout", 5))), 4.0),
                    "per_feed_timeout_seconds": min(float(params.get("news_timeout", params.get("timeout", 5))), 3.5),
                    "symbol_feed_timeout_seconds": min(float(params.get("news_timeout", params.get("timeout", 5))), 4.0),
                }
                if symbol:
                    terms = symbol_terms(symbol, str(query or symbol))
                    extra["query"] = str(query or symbol)
                    extra["terms"] = terms
                    extra["optional_terms"] = [symbol]
                elif str(query).strip().lower() not in {"", "market", "markets", "top", "latest"}:
                    extra["query"] = query
                    extra["terms"] = _query_terms(str(query))
                items = await asyncio.wait_for(
                    src.fetch(DataRequest(kind=DataKind.NEWS, extra=extra, limit=limit)),
                    timeout=float(params.get("news_timeout", params.get("timeout", 5))),
                )
                if items:
                    sources.append(src_name)
                    results.extend(items)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{src_name}: {exc}")
        threshold = float(params.get("threshold", 70) or 70)
        ranked = enrich_articles(
            results,
            symbol=symbol,
            query=str(query),
            asset_class=asset_class,
            threshold=threshold,
            limit=limit,
        )
        ranked = [article for article in ranked if _within_age_window(article, max_age_days)]
        ranked = ranked[:limit]
        alerts = critical_articles(ranked, threshold=threshold)
        return FunctionResult(
            code=self.code, instrument=None,
            data=ranked,
            sources=sources,
            metadata={
                "count": len(results),
                "query": query,
                "freshness_max_days": max_age_days,
                "provider_errors": warnings,
                "critical_count": len(alerts),
                "top_importance_score": max([float(a.get("importance_score") or 0) for a in ranked], default=0.0),
                "method": "deterministic_impact_score_v2",
                "methodology": (
                    "Ranks live RSS/GDELT headlines by query relevance, market catalyst keywords, "
                    "source quality, and freshness. Headlines outside freshness_max_days are filtered. "
                    "Each card exposes importance_reasons."
                ),
            },
        )


def _query_terms(query: str) -> list[str]:
    stop = {"stock", "stocks", "market", "markets", "news", "latest", "price", "prices"}
    words = [
        part.strip().lower()
        for part in query.replace("/", " ").replace("-", " ").split()
        if len(part.strip()) >= 3 and part.strip().lower() not in stop
    ]
    return words[:5] or [query.lower()]


def _int_param(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(min_value, min(parsed, max_value))


def _within_age_window(article: dict[str, Any], max_age_days: int) -> bool:
    ts = article_timestamp(article)
    if ts is None:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    return ts >= cutoff


def _symbol_terms(symbol: str, query: Any) -> list[str]:
    upper = symbol.upper()
    if upper.endswith("USDT"):
        base = upper.removesuffix("USDT")
        names = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
        return list(dict.fromkeys([base.lower(), names.get(base, ""), *_query_terms(str(query or ""))]))
    return list(dict.fromkeys([upper.lower(), *_query_terms(str(query or ""))]))
