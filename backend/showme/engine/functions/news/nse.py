"""NSE — News Search Engine (Meilisearch backend if available)."""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.services.news_intelligence import critical_articles, enrich_articles, symbol_terms


@FunctionRegistry.register
class NSEFunction(BaseFunction):
    code = "NSE"
    name = "News Search Engine"
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        query = params.get("query") or (instrument.symbol if instrument else "")
        if not query:
            return FunctionResult(code=self.code, instrument=instrument, data=[],
                                  warnings=["empty query"])
        symbol = str(params.get("symbol") or (instrument.symbol if instrument else "") or "").upper()
        asset_class = str(
            params.get("asset_class")
            or getattr(getattr(instrument, "asset_class", None), "value", "")
            or ""
        ).upper()
        sources: list[str] = []
        results: list = []
        warnings: list[str] = []
        live = _truthy(params.get("live_news") or params.get("live"))
        limit = _int_param(params, "limit", 100)
        if not live:
            results = [{
                "title": f"{query} news search snapshot",
                "summary": "Local continuity result for the current symbol/query.",
                "query": query,
                "source": "local_news_template",
                "published_at": None,
                "url": None,
                "status": "ready",
            }]
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=results,
                sources=["local_news_cache"],
                metadata={"query": query, "provider_errors": [], "live": False},
            )
        # Try local index first (Meili → SQLite FTS5)
        try:
            from showme.engine.services.news_index import NewsIndex
            idx = NewsIndex()
            results = await asyncio.wait_for(
                idx.search(
                    query, start=params.get("start"), end=params.get("end"),
                    limit=limit,
                ),
                timeout=float(params.get("index_timeout", 5)),
            )
            if results:
                sources.append("meilisearch" if idx.meili else "sqlite_fts")
        except Exception as e:
            warnings.append(f"news_index: {str(e) or type(e).__name__}")
        if not results and self.deps.rss:
            try:
                timeout = float(params.get("timeout", params.get("news_timeout", 8)))
                results = await asyncio.wait_for(
                    self.deps.rss.fetch(DataRequest(
                        kind=DataKind.NEWS,
                        extra={
                            "query": query,
                            "terms": symbol_terms(symbol, str(query)) if symbol else _query_terms(str(query)),
                            "optional_terms": [str(query).lower()],
                            "feed_group": "crypto" if asset_class == "CRYPTO" else "market",
                            "asset_class": asset_class,
                            "symbol": symbol,
                            "collection_timeout_seconds": min(timeout, 4.0),
                            "per_feed_timeout_seconds": min(timeout, 3.5),
                            "symbol_feed_timeout_seconds": min(timeout, 4.0),
                        },
                        limit=limit,
                    )),
                    timeout=timeout,
                )
                if results:
                    sources.append("rss")
            except Exception as e:
                warnings.append(f"rss: {str(e) or type(e).__name__}")
        # GDELT is a slow/rate-limited deep fallback, not the default path.
        if not results and self.deps.gdelt and _truthy(params.get("include_gdelt") or params.get("deep")):
            try:
                results = await asyncio.wait_for(
                    self.deps.gdelt.fetch(DataRequest(
                        kind=DataKind.NEWS, extra={"query": query},
                        start=params.get("start"), end=params.get("end"),
                        limit=limit,
                    )),
                    timeout=float(params.get("timeout", 8)),
                )
                sources.append("gdelt")
                # Index hits for next time
                try:
                    from showme.engine.services.news_index import NewsIndex
                    await NewsIndex().add_articles(results)
                except Exception:
                    pass
            except Exception as e:
                warnings.append(f"gdelt: {str(e) or type(e).__name__}")
        threshold = float(params.get("threshold", 70) or 70)
        ranked = enrich_articles(
            results,
            symbol=symbol,
            query=str(query),
            asset_class=asset_class,
            threshold=threshold,
            limit=limit,
        )
        if live and not ranked:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "reason": f"No live news rows returned for query '{query}'.",
                    "rows": [],
                    "next_actions": [
                        "Try a more specific company, ticker, or topic query.",
                        "Click Deep to include the slower GDELT fallback when available.",
                    ],
                },
                sources=sources,
                metadata={
                    "query": query,
                    "provider_errors": warnings or ["news providers returned no usable rows"],
                    "critical_count": 0,
                    "top_importance_score": 0.0,
                },
            )
        alerts = critical_articles(ranked, threshold=threshold)
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=ranked,
            sources=sources,
            metadata={
                "query": query,
                "provider_errors": warnings,
                "critical_count": len(alerts),
                "top_importance_score": max([float(a.get("importance_score") or 0) for a in ranked], default=0.0),
            },
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int_param(params: dict[str, Any], name: str, default: int) -> int:
    try:
        return max(1, int(params.get(name, default) or default))
    except Exception:
        return default


def _query_terms(query: str) -> list[str]:
    stop = {"stock", "stocks", "market", "markets", "news", "latest", "price", "prices"}
    terms = [
        part.strip().lower()
        for part in query.replace("/", " ").replace("-", " ").split()
        if len(part.strip()) >= 3 and part.strip().lower() not in stop
    ]
    return terms[:6] or [query.lower()]


def _symbol_terms(symbol: str, query: str) -> list[str]:
    upper = symbol.upper()
    if upper.endswith("USDT"):
        base = upper.removesuffix("USDT")
        names = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
        return list(dict.fromkeys([base.lower(), names.get(base, ""), *_query_terms(query)]))
    return list(dict.fromkeys([upper.lower(), *_query_terms(query)]))
