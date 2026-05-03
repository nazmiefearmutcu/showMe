"""NALRT — Critical News Alerts."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.services.news_intelligence import (
    critical_articles,
    enrich_articles,
    health_summary,
    symbol_terms,
)


@FunctionRegistry.register
class NewsAlertFunction(BaseFunction):
    code = "NALRT"
    name = "Critical News Alerts"
    category = "news"
    description = "Ranks live headlines by market impact and raises critical/high news alerts."
    asset_classes = (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.ETF, AssetClass.INDEX)

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbol = str(params.get("symbol") or (instrument.symbol if instrument else "") or "").upper()
        asset_class = str(
            params.get("asset_class")
            or getattr(getattr(instrument, "asset_class", None), "value", "")
            or ("CRYPTO" if symbol.endswith(("USDT", "USDC")) else "EQUITY" if symbol else "")
        ).upper()
        query = str(params.get("query") or symbol or "market").strip()
        limit = int(params.get("limit", 30) or 30)
        scan_limit = max(limit * 3, 60)
        threshold = float(params.get("threshold", 70) or 70)
        timeout = float(params.get("news_timeout", params.get("timeout", 6)) or 6)
        include_health = _truthy(params.get("health", True))
        feed_group = "crypto" if asset_class == "CRYPTO" else "market"
        terms = symbol_terms(symbol, query)

        results: list[dict[str, Any]] = []
        sources: list[str] = []
        warnings: list[str] = []
        provider_health: list[dict[str, Any]] = []
        pending: list[tuple[str, asyncio.Task[Any], float]] = []
        health_task: asyncio.Task[Any] | None = None
        rss_request: DataRequest | None = None

        if self.deps.rss:
            request = DataRequest(
                kind=DataKind.NEWS,
                instrument=instrument,
                limit=scan_limit,
                extra={
                    "query": query,
                    "terms": terms,
                    "optional_terms": terms,
                    "feed_group": feed_group,
                    "asset_class": asset_class,
                    "symbol": symbol,
                    "collection_timeout_seconds": min(timeout, 4.0),
                    "per_feed_timeout_seconds": min(timeout, 3.5),
                    "symbol_feed_timeout_seconds": min(timeout, 4.0),
                },
            )
            rss_request = request
            pending.append(("rss", asyncio.create_task(self.deps.rss.fetch(request)), timeout))
            if include_health and hasattr(self.deps.rss, "probe_feeds"):
                health_task = asyncio.create_task(
                    self.deps.rss.probe_feeds(request, timeout=min(timeout, 3.0)),
                )

        if symbol and asset_class in {"EQUITY", "ETF", "INDEX"} and getattr(self.deps, "yfinance", None):
            yf_instrument = instrument or Instrument(
                symbol=symbol,
                asset_class=_asset_class(asset_class),
                exchange=None,
                currency="USD",
            )
            pending.append((
                "yfinance_news",
                asyncio.create_task(self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.NEWS,
                    instrument=yf_instrument,
                    symbols=[symbol],
                    limit=scan_limit,
                    extra={"timeout": min(timeout, 4.0)},
                ))),
                min(timeout, 4.5),
            ))

        for name, task, task_timeout in pending:
            try:
                items = await asyncio.wait_for(task, timeout=task_timeout)
                if items:
                    results.extend(items)
                    sources.append(name)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{name}: {_error_message(exc)}")

        if health_task is not None:
            try:
                provider_health = await asyncio.wait_for(
                    health_task,
                    timeout=min(timeout + 1.0, 6.0),
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"rss_health: {_error_message(exc)}")

        if not results and self.deps.rss and rss_request is not None:
            retry_extra = dict(rss_request.extra or {})
            retry_extra.update({
                "collection_timeout_seconds": min(timeout + 2.0, 6.0),
                "per_feed_timeout_seconds": min(timeout + 2.0, 5.0),
                "symbol_feed_timeout_seconds": min(timeout + 2.0, 6.0),
            })
            retry_request = DataRequest(
                kind=rss_request.kind,
                instrument=rss_request.instrument,
                symbols=rss_request.symbols,
                start=rss_request.start,
                end=rss_request.end,
                interval=rss_request.interval,
                limit=rss_request.limit,
                extra=retry_extra,
            )
            try:
                items = await asyncio.wait_for(
                    self.deps.rss.fetch(retry_request),
                    timeout=min(timeout + 3.0, 9.0),
                )
                if items:
                    results.extend(items)
                    sources.append("rss")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"rss_retry: {_error_message(exc)}")
            if include_health and _health_ok_rate(provider_health) < 0.5:
                try:
                    provider_health = await asyncio.wait_for(
                        self.deps.rss.probe_feeds(retry_request, timeout=min(timeout + 2.0, 5.0)),
                        timeout=min(timeout + 3.0, 9.0),
                    )
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"rss_health_retry: {_error_message(exc)}")

        if results and include_health and self.deps.rss and rss_request is not None and _health_ok_rate(provider_health) < 0.5:
            retry_extra = dict(rss_request.extra or {})
            retry_extra.update({
                "collection_timeout_seconds": min(timeout + 2.0, 6.0),
                "per_feed_timeout_seconds": min(timeout + 2.0, 5.0),
                "symbol_feed_timeout_seconds": min(timeout + 2.0, 6.0),
            })
            try:
                provider_health = await asyncio.wait_for(
                    self.deps.rss.probe_feeds(
                        DataRequest(
                            kind=rss_request.kind,
                            instrument=rss_request.instrument,
                            symbols=rss_request.symbols,
                            start=rss_request.start,
                            end=rss_request.end,
                            interval=rss_request.interval,
                            limit=rss_request.limit,
                            extra=retry_extra,
                        ),
                        timeout=min(timeout + 2.0, 5.0),
                    ),
                    timeout=min(timeout + 3.0, 9.0),
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"rss_health_retry: {_error_message(exc)}")

        if _truthy(params.get("deep")) and self.deps.gdelt:
            try:
                gdelt_items = await asyncio.wait_for(
                    self.deps.gdelt.fetch(DataRequest(
                        kind=DataKind.NEWS,
                        limit=scan_limit,
                        extra={"query": query},
                    )),
                    timeout=timeout,
                )
                if gdelt_items:
                    results.extend(gdelt_items)
                    sources.append("gdelt")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"gdelt: {_error_message(exc)}")

        ranked = enrich_articles(
            _dedupe(results),
            symbol=symbol,
            query=query,
            asset_class=asset_class,
            threshold=threshold,
            limit=limit,
        )
        alerts = critical_articles(ranked, threshold=threshold)
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "alerts": alerts,
                "top": ranked,
                "health": health_summary(provider_health),
                "feed_health": provider_health,
                "threshold": threshold,
                "query": query,
                "symbol": symbol,
                "alert_count": len(alerts),
                "top_importance_score": max(
                    [float(row.get("importance_score") or 0) for row in ranked],
                    default=0.0,
                ),
            },
            sources=sources,
            metadata={
                "provider_errors": warnings,
                "method": "deterministic_impact_score_v1",
                "terms": terms,
            },
        )


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("url") or item.get("link") or item.get("title") or item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _asset_class(value: str) -> AssetClass:
    try:
        return AssetClass(value)
    except Exception:
        return AssetClass.EQUITY


def _error_message(exc: Exception) -> str:
    return str(exc) or type(exc).__name__


def _health_ok_rate(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row.get("ok")) / len(rows)
