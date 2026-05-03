"""TOP — Top News (multi-source aggregator)."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument
from src.services.news_intelligence import critical_articles, enrich_articles, symbol_terms


@FunctionRegistry.register
class TOPFunction(BaseFunction):
    code = "TOP"
    name = "Top News"
    asset_classes = ()  # global
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        limit = int(params.get("limit", 50))
        query = params.get("query") or "market"
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
        alerts = critical_articles(ranked, threshold=threshold)
        return FunctionResult(
            code=self.code, instrument=None,
            data=ranked,
            sources=sources,
            metadata={
                "count": len(results),
                "query": query,
                "provider_errors": warnings,
                "critical_count": len(alerts),
                "top_importance_score": max([float(a.get("importance_score") or 0) for a in ranked], default=0.0),
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


def _symbol_terms(symbol: str, query: Any) -> list[str]:
    upper = symbol.upper()
    if upper.endswith("USDT"):
        base = upper.removesuffix("USDT")
        names = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
        return list(dict.fromkeys([base.lower(), names.get(base, ""), *_query_terms(str(query or ""))]))
    return list(dict.fromkeys([upper.lower(), *_query_terms(str(query or ""))]))
