"""TOP — Top News (multi-source aggregator)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.services.news_intelligence import article_timestamp, critical_articles, enrich_articles, symbol_terms
from showme.finbert_analyzer import stamp_items as _finbert_stamp_items


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
        stamp_sentiment = str(params.get("stamp_sentiment", "True")).strip().lower() not in {"0", "false", "no", "off"}
        results: list[dict[str, Any]] = []
        sources: list[str] = []
        warnings: list[str] = []
        source_order = ["rss"]
        if params.get("include_gdelt") or params.get("deep"):
            source_order.append("gdelt")
        # Clamp the caller-supplied timeout once and reuse — the original
        # code clamped each `collection_*` field to 4.0s individually but
        # left `asyncio.wait_for` using the raw (unclamped) timeout, so a
        # caller passing `news_timeout=10` got per-feed 4s budgets inside
        # a 10s outer wait that no inner feed could ever exhaust.
        #
        # QA-fix: bump the default from 5s -> 10s. The previous 5s default
        # was hit so often during real RSS fan-out that callers saw "0 rows
        # in 3s" silent fails. 10s sits comfortably under the 30s FastAPI
        # request budget while giving the slowest feeds room to land.
        raw_timeout = float(params.get("news_timeout", params.get("timeout", 10)))
        outer_timeout = max(1.0, min(raw_timeout, 15.0))
        collection_budget = min(outer_timeout, 8.0)
        per_feed_budget = min(outer_timeout, 6.0)
        for src_name in source_order:
            src = getattr(self.deps, src_name, None)
            if src is None:
                continue
            try:
                extra: dict[str, Any] = {
                    "feed_group": "crypto" if asset_class == "CRYPTO" else "market",
                    "asset_class": asset_class,
                    "symbol": symbol,
                    "collection_timeout_seconds": collection_budget,
                    "per_feed_timeout_seconds": per_feed_budget,
                    "symbol_feed_timeout_seconds": collection_budget,
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
                    timeout=outer_timeout,
                )
                if items:
                    sources.append(src_name)
                    results.extend(items)
            except asyncio.TimeoutError:
                # QA-fix: surface the timeout reason explicitly so the UI no
                # longer shows an empty "rss: " warning.
                warnings.append(
                    f"{src_name}: timed out after {outer_timeout:.1f}s"
                )
            except Exception as exc:  # noqa: BLE001
                # QA-fix: propagate the exception class name when str(exc) is
                # empty so the UI never shows a bare "rss: " label.
                reason = str(exc) or exc.__class__.__name__
                warnings.append(f"{src_name}: {reason}")
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
        # FinBERT sentiment pass — stamps `sentiment` + `sentiment_score` on
        # every item so the UI shows finance-domain labels instead of the
        # bare keyword fallback. Non-fatal: if the model can't load, items
        # get neutral and a warning lands in `provider_errors`.
        finbert_warning = None
        sentiment_model = "skipped"
        if stamp_sentiment:
            _, finbert_warning = await _finbert_stamp_items(ranked)
            if finbert_warning:
                warnings.append(finbert_warning)
            sentiment_model = "finbert" if finbert_warning is None else "neutral_fallback"
        alerts = critical_articles(ranked, threshold=threshold)
        # Per FUNC-10 P1: wrap the list payload as ``{items: ranked, ...}`` so
        # function_contracts._extract_rows can pick it up and the contract
        # envelope stays uniform with every other function.
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "items": ranked,
                "alerts": alerts,
                "status": "ok" if ranked else "empty",
            },
            sources=sources,
            metadata={
                "count": len(results),
                "query": query,
                "freshness_max_days": max_age_days,
                "provider_errors": warnings,
                "critical_count": len(alerts),
                "top_importance_score": max([float(a.get("importance_score") or 0) for a in ranked], default=0.0),
                "method": "deterministic_impact_score_v2",
                "sentiment_model": sentiment_model,
                "methodology": (
                    "Ranks live RSS/GDELT headlines by query relevance, market catalyst keywords, "
                    "source quality, and freshness. Headlines outside freshness_max_days are filtered. "
                    "Each card exposes importance_reasons. FinBERT (ProsusAI/finbert) labels "
                    "sentiment per row."
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
