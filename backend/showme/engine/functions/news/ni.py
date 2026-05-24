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
        # BugHunt 2026-05-24: NI used to forward `params.get("limit", 50)` raw
        # into DataRequest(limit=...) and TOPFunction(limit=...). When the UI
        # serialised query strings as text (`?limit=50`), the downstream RSS
        # adapter executed `articles[: request.limit]` and crashed with
        # `TypeError: slice indices must be integers or None`. The error
        # bubbled into NI's `provider_errors` field and topic-mode silently
        # returned no rows. Coerce once at the top so every downstream call
        # sees a real int.
        limit = _coerce_int(params.get("limit"), default=50, min_value=1, max_value=500)
        threshold = _coerce_float(params.get("threshold"), default=70.0, min_value=0.0, max_value=100.0)
        if live and self.deps.rss:
            try:
                timeout = _coerce_float(
                    params.get("news_timeout", params.get("timeout", 5)),
                    default=5.0,
                    min_value=0.5,
                    max_value=30.0,
                )
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
                        kind=DataKind.NEWS, extra=extra, limit=limit,
                    )),
                    timeout=timeout,
                )
                if results:
                    sources.append("rss")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"rss: {exc}")
        if not results and live and self.deps.gdelt and _truthy(params.get("include_gdelt") or params.get("deep")):
            try:
                gdelt_timeout = _coerce_float(
                    params.get("timeout", 8),
                    default=8.0,
                    min_value=0.5,
                    max_value=30.0,
                )
                results = await asyncio.wait_for(
                    self.deps.gdelt.fetch(DataRequest(
                        kind=DataKind.NEWS, extra={"query": query}, limit=limit,
                    )),
                    timeout=gdelt_timeout,
                )
                sources.append("gdelt")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"gdelt: {exc}")
        if not results and live:
            try:
                from showme.engine.functions.news.top import TOPFunction

                outer_timeout = _coerce_float(
                    params.get("news_timeout", params.get("timeout", 5)),
                    default=5.0,
                    min_value=0.5,
                    max_value=30.0,
                ) + 1.0
                top = await asyncio.wait_for(
                    TOPFunction(self.deps).execute(
                        instrument,
                        symbol=symbol,
                        asset_class=asset_class,
                        query=query,
                        topic=topic,
                        limit=limit,
                        __explicit_symbol=bool(symbol),
                        news_timeout=params.get("news_timeout", params.get("timeout", 5)),
                    ),
                    timeout=outer_timeout,
                )
                if top.data:
                    # TOPFunction now returns dict {items, alerts, status} per
                    # FUNC-10 P1; unwrap to the bare list enrich_articles wants.
                    if isinstance(top.data, dict):
                        results = list(top.data.get("items") or [])
                    elif isinstance(top.data, list):
                        results = top.data
                    sources.extend(top.sources or [])
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"top: {exc}")
        ranked = enrich_articles(
            results,
            symbol=symbol,
            query=query,
            asset_class=asset_class,
            threshold=threshold,
            limit=limit,
        )
        alerts = critical_articles(ranked, threshold=threshold)
        # Per FUNC-10 P1: wrap list payload as ``{items: ...}`` so the shared
        # contract envelope works (was a bare list which silently bypassed
        # status injection in function_contracts._attach_data_status).
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "items": ranked,
                "alerts": alerts,
                "status": "ok" if ranked else "empty",
            },
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


def _coerce_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    """Coerce ``value`` to a clamped int. Falls back to ``default`` on any error.

    BugHunt 2026-05-24: NI used to forward query-string limits verbatim to
    DataRequest, which crashed the RSS adapter with
    ``TypeError: slice indices must be integers or None`` when the caller
    passed ``limit="50"``. This helper guarantees we never hand a non-int
    downstream.
    """
    if value is None or value == "":
        return max(min_value, min(default, max_value))
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            parsed = default
    return max(min_value, min(parsed, max_value))


def _coerce_float(value: Any, *, default: float, min_value: float, max_value: float) -> float:
    if value is None or value == "":
        return max(min_value, min(default, max_value))
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(parsed, max_value))


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
