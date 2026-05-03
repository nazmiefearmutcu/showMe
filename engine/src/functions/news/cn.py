"""CN — Company News."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.services.news_intelligence import critical_articles, enrich_articles, symbol_terms

_CRYPTO_NAMES = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
    "BNB": "BNB",
    "XRP": "XRP",
    "ADA": "Cardano",
    "DOGE": "Dogecoin",
    "AVAX": "Avalanche",
    "DOT": "Polkadot",
    "LINK": "Chainlink",
}
_QUOTE_SUFFIXES = ("USDT", "USDC", "USD", "BTC", "ETH", "EUR")


@FunctionRegistry.register
class CNFunction(BaseFunction):
    code = "CN"
    name = "Company News"
    asset_classes = (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.ETF)
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("CN requires a symbol")
        limit = int(params.get("limit", 50) or 50)
        live_news = bool(params.get("live_news") or params.get("live"))
        if not live_news and instrument.asset_class not in (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.ETF):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_fallback_news(instrument, limit, topic="market"),
                sources=["local_news_cache"],
                metadata={"mode": "computed_model"},
            )
        if instrument.asset_class == AssetClass.CRYPTO:
            return await self._execute_crypto(instrument, limit, params)
        results: list = []
        sources: list[str] = []
        warnings: list[str] = []
        timeout = _news_timeout(params, default=5.0)
        source_order = ["rss"]
        if _adapter_has_key(getattr(self.deps, "finnhub_news", None)):
            source_order.append("finnhub_news")
        if params.get("include_yfinance") or params.get("deep"):
            source_order.append("yfinance")
        if params.get("include_gdelt") or params.get("deep"):
            source_order.append("gdelt")

        for src_name in source_order:
            src = getattr(self.deps, src_name, None)
            if src is None:
                continue
            if len(results) >= limit:
                break
            try:
                if src_name == "gdelt":
                    items = await asyncio.wait_for(
                        src.fetch(DataRequest(kind=DataKind.NEWS,
                                              extra={"query": instrument.symbol},
                                              limit=limit)),
                        timeout=timeout,
                    )
                elif src_name == "rss":
                    terms = symbol_terms(instrument.symbol, instrument.symbol)
                    items = await asyncio.wait_for(
                        src.fetch(DataRequest(
                            kind=DataKind.NEWS,
                            instrument=instrument,
                            limit=limit,
                            extra={
                                "query": instrument.symbol,
                                "terms": terms,
                                "optional_terms": terms,
                                "feed_group": "market",
                                "asset_class": instrument.asset_class.value,
                                "collection_timeout_seconds": min(timeout, 4.0),
                                "per_feed_timeout_seconds": min(timeout, 3.5),
                                "symbol_feed_timeout_seconds": min(timeout, 4.0),
                            },
                        )),
                        timeout=timeout,
                    )
                else:
                    items = await asyncio.wait_for(
                        src.fetch(DataRequest(kind=DataKind.NEWS, instrument=instrument,
                                              limit=limit)),
                        timeout=timeout,
                    )
                if items:
                    sources.append(src_name)
                    results.extend(items)
            except Exception as e:
                warnings.append(f"{src_name}: {e}")
        data = enrich_articles(
            _dedupe(results),
            symbol=instrument.symbol,
            query=instrument.symbol,
            asset_class=instrument.asset_class.value,
            threshold=float(params.get("threshold", 70) or 70),
            limit=limit,
        )
        if not data:
            data = _fallback_news(instrument, limit)
            sources = ["local_news_cache"]
        alerts = critical_articles(data, threshold=float(params.get("threshold", 70) or 70))
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=data,
            sources=sources,
            metadata={
                "provider_errors": warnings,
                "critical_count": len(alerts),
                "top_importance_score": max([float(a.get("importance_score") or 0) for a in data], default=0.0),
            },
        )

    async def _execute_crypto(self, instrument: Instrument, limit: int, params: dict[str, Any]) -> FunctionResult:
        terms = _crypto_specific_terms(instrument.symbol)
        context_terms = _crypto_context_terms(instrument.symbol)
        query = " OR ".join(f'"{term}"' for term in terms)
        results: list = []
        sources: list[str] = []
        warnings: list[str] = []
        timeout = _news_timeout(params, default=5.0)

        # RSS is the most reliable no-key crypto source in the native app.
        source_order = ["rss"]
        if params.get("include_yfinance") or params.get("deep"):
            source_order.append("yfinance")
        if _adapter_has_key(getattr(self.deps, "cryptocompare", None)):
            source_order.append("cryptocompare")
        if params.get("include_gdelt") or params.get("deep"):
            source_order.append("gdelt")

        for src_name in source_order:
            src = getattr(self.deps, src_name, None)
            if src is None:
                continue
            if src_name == "cryptocompare" and not getattr(src, "api_key", ""):
                continue
            if len(results) >= limit:
                break
            try:
                if src_name == "cryptocompare":
                    items = await asyncio.wait_for(
                        src.fetch(DataRequest(
                            kind=DataKind.NEWS,
                            instrument=instrument,
                            extra={"category": _crypto_base(instrument.symbol)},
                            limit=limit,
                        )),
                        timeout=timeout,
                    )
                elif src_name == "yfinance":
                    items = await asyncio.wait_for(
                        src.fetch(DataRequest(
                            kind=DataKind.NEWS,
                            instrument=instrument,
                            limit=limit,
                        )),
                        timeout=timeout,
                    )
                else:
                    items = await asyncio.wait_for(
                        src.fetch(DataRequest(
                            kind=DataKind.NEWS,
                            instrument=instrument,
                            extra={
                                "query": query,
                                "terms": terms,
                                "optional_terms": context_terms,
                                "feed_group": "crypto",
                                "asset_class": "CRYPTO",
                                "collection_timeout_seconds": min(timeout, 4.0),
                                "per_feed_timeout_seconds": min(timeout, 3.5),
                            },
                            limit=limit,
                        )),
                        timeout=timeout,
                    )
                if items:
                    sources.append(src_name)
                    results.extend(items)
            except Exception as e:
                warnings.append(f"{src_name}: {e}")
        data = enrich_articles(
            _filter_relevant_news(_dedupe(results), terms, limit * 3),
            symbol=instrument.symbol,
            query=query,
            asset_class="CRYPTO",
            threshold=float(params.get("threshold", 70) or 70),
            limit=limit,
        )
        if not data:
            data = _fallback_news(instrument, limit, topic="digital asset")
            sources = ["local_news_cache"]
        alerts = critical_articles(data, threshold=float(params.get("threshold", 70) or 70))

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=data,
            sources=sources,
            metadata={
                "query": query,
                "terms": terms,
                "context_terms": context_terms,
                "provider_errors": warnings,
                "critical_count": len(alerts),
                "top_importance_score": max([float(a.get("importance_score") or 0) for a in data], default=0.0),
            },
        )


def _crypto_specific_terms(symbol: str) -> list[str]:
    base = _crypto_base(symbol)
    terms = [symbol.upper(), base]
    if base in _CRYPTO_NAMES:
        terms.append(_CRYPTO_NAMES[base])
    if base == "ETH":
        terms.append("Ether")
    return list(dict.fromkeys(t for t in terms if t))


def _news_timeout(params: dict[str, Any], default: float = 5.0) -> float:
    try:
        return max(1.0, min(float(params.get("news_timeout", default)), 6.0))
    except Exception:
        return default


def _adapter_has_key(src: Any) -> bool:
    if src is None:
        return False
    if not getattr(src, "requires_api_key", False):
        return True
    return bool(getattr(src, "api_key", "") or getattr(src, "api_secret", ""))


def _crypto_context_terms(symbol: str) -> list[str]:
    base = _crypto_base(symbol)
    terms = ["cryptocurrency", "crypto", "digital asset", "blockchain"]
    if base == "BTC":
        terms.extend(["spot bitcoin ETF", "Bitcoin ETF"])
    if base == "ETH":
        terms.extend(["Ethereum ETF", "ether ETF", "staking"])
    return list(dict.fromkeys(t for t in terms if t))


def _crypto_terms(symbol: str) -> list[str]:
    terms = [*_crypto_specific_terms(symbol), *_crypto_context_terms(symbol)]
    return list(dict.fromkeys(t for t in terms if t))


def _crypto_base(symbol: str) -> str:
    value = symbol.upper().replace("/", "").replace("-", "")
    for suffix in _QUOTE_SUFFIXES:
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)]
    return value


def _dedupe(items: list) -> list:
    seen: set[str] = set()
    out: list = []
    for item in items:
        if not isinstance(item, dict):
            out.append(item)
            continue
        key = str(item.get("url") or item.get("link") or item.get("title") or item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _filter_relevant_news(items: list, terms: list[str], limit: int) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        score = _news_relevance_score(item, terms)
        if score <= 0:
            continue
        scored.append((score, item))
    scored.sort(
        key=lambda row: (row[0], str(row[1].get("published_at") or row[1].get("published_on") or "")),
        reverse=True,
    )
    return [item for _, item in scored[:limit]]


def _news_relevance_score(item: dict[str, Any], terms: list[str]) -> float:
    title = _news_text(item, title_only=True)
    text = _news_text(item)
    score = 0.0
    for term in terms:
        if _term_in_text(term, title):
            score += 5.0
        elif _term_in_text(term, text):
            score += 2.0
    return score


def _news_text(item: dict[str, Any], title_only: bool = False) -> str:
    keys = ("title",) if title_only else (
        "title", "summary", "body", "description", "categories", "feed", "source"
    )
    return " ".join(str(item.get(k) or "") for k in keys).lower()


def _term_in_text(term: str, text: str) -> bool:
    import re

    needle = str(term or "").strip().lower()
    if not needle:
        return False
    if re.fullmatch(r"[a-z0-9]{2,6}", needle):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text))
    return needle in text


def _fallback_news(instrument: Instrument, limit: int, topic: str = "company") -> list[dict[str, Any]]:
    rows = [
        {
            "title": f"{instrument.symbol} {topic} news feed unavailable",
            "summary": "External news providers returned no usable headlines for this request.",
            "symbol": instrument.symbol,
            "source": "showMe",
            "published_at": None,
            "url": None,
            "status": "news_feed_empty",
        }
    ]
    return rows[: max(1, limit)]
