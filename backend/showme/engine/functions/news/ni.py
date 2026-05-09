"""NI — News by Topic (NI BANKS, NI EARN, NI FED, ...)."""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.services.news_intelligence import critical_articles, enrich_articles, symbol_terms

_TOPIC_QUERIES = {
    "BANKS": "bank OR banking OR JPMorgan OR Citi OR Goldman",
    "EARN":  "earnings OR \"earnings call\" OR \"quarterly results\"",
    "FED":   "Federal Reserve OR FOMC OR Powell",
    "CHIPS": "semiconductor OR TSMC OR ASML OR NVIDIA OR chips",
    "OIL":   "OPEC OR crude OR Brent OR WTI OR oil prices",
    "TECH":  "technology OR Apple OR Microsoft OR cloud OR AI",
    "MACRO": "GDP OR CPI OR inflation OR unemployment",
    "WAR":   "war OR conflict OR sanctions",
    "M&A":   "acquisition OR merger OR \"agreed to acquire\"",
    "IPO":   "IPO OR \"initial public offering\" OR direct listing",
}


@FunctionRegistry.register
class NIFunction(BaseFunction):
    code = "NI"
    name = "News by Topic"
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        explicit_query = str(params.get("query") or "").strip()
        topic = (params.get("topic") or explicit_query or "MACRO").upper()
        query = explicit_query or _TOPIC_QUERIES.get(topic, topic)
        asset_class = str(
            params.get("asset_class")
            or getattr(getattr(instrument, "asset_class", None), "value", "")
            or ""
        ).upper()
        symbol = str(params.get("symbol") or (instrument.symbol if instrument else "") or "").upper()
        sources: list[str] = []
        results: list = []
        warnings: list[str] = []
        live = _truthy(params.get("live_news") or params.get("live"))
        if live and self.deps.rss:
            try:
                timeout = float(params.get("news_timeout", params.get("timeout", 5)))
                extra = {
                    "query": query,
                    "terms": symbol_terms(symbol, query) if symbol else _query_terms(query),
                    "optional_terms": [topic.lower()],
                    "feed_group": "crypto" if asset_class == "CRYPTO" else "market",
                    "asset_class": asset_class,
                    "symbol": symbol,
                    "collection_timeout_seconds": min(timeout, 4.0),
                    "per_feed_timeout_seconds": min(timeout, 3.5),
                    "symbol_feed_timeout_seconds": min(timeout, 4.0),
                }
                results = await asyncio.wait_for(
                    self.deps.rss.fetch(DataRequest(
                        kind=DataKind.NEWS, extra=extra, limit=params.get("limit", 50),
                    )),
                    timeout=float(params.get("news_timeout", params.get("timeout", 5))),
                )
                if results:
                    sources.append("rss")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"rss: {exc}")
        if not results and live and self.deps.gdelt and _truthy(params.get("include_gdelt") or params.get("deep")):
            try:
                results = await asyncio.wait_for(
                    self.deps.gdelt.fetch(DataRequest(
                        kind=DataKind.NEWS, extra={"query": query}, limit=params.get("limit", 50),
                    )),
                    timeout=float(params.get("timeout", 8)),
                )
                sources.append("gdelt")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"gdelt: {exc}")
        if not results and live:
            try:
                from showme.engine.functions.news.top import TOPFunction

                top = await asyncio.wait_for(
                    TOPFunction(self.deps).execute(
                        instrument,
                        symbol=symbol,
                        asset_class=asset_class,
                        query=query,
                        topic=topic,
                        limit=params.get("limit", 50),
                        __explicit_symbol=bool(symbol),
                        news_timeout=params.get("news_timeout", params.get("timeout", 5)),
                    ),
                    timeout=float(params.get("news_timeout", params.get("timeout", 5))) + 1,
                )
                if top.data:
                    results = top.data
                    sources.extend(top.sources or [])
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"top: {exc}")
        threshold = float(params.get("threshold", 70) or 70)
        ranked = enrich_articles(
            results,
            symbol=symbol,
            query=query,
            asset_class=asset_class,
            threshold=threshold,
            limit=int(params.get("limit", 50) or 50),
        )
        alerts = critical_articles(ranked, threshold=threshold)
        return FunctionResult(
            code=self.code, instrument=None, data=ranked,
            sources=sources, metadata={
                "topic": topic,
                "query": query,
                "live": live,
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
