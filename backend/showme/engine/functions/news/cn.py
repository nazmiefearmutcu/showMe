"""CN — Company News."""

from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import httpx

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.services.news_intelligence import critical_articles, enrich_articles, symbol_terms

try:
    from showme.crypto_aliases import (
        CRYPTO_DISPLAY_NAMES as _CRYPTO_NAMES,
        CRYPTO_QUOTE_SUFFIXES as _QUOTE_SUFFIXES,
    )
except Exception:  # pragma: no cover - standalone engine fallback
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
        "PEPE": "Pepe",
        "WIF": "dogwifhat",
    }
    _QUOTE_SUFFIXES = ("USDT", "USDC", "FDUSD", "USD", "BTC", "ETH", "EUR")


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
        data = _prefer_direct_symbol_matches(data, min_rows=max(3, min(limit, 8)))
        if not data:
            data = _provider_unavailable_rows(instrument, limit, "No directly relevant company headlines were returned for this symbol.")
            sources = sources or ["no_live_source"]
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
            fallback_rows, fallback_sources, fallback_warnings = await _crypto_context_fallback_rows(
                instrument,
                terms,
                limit,
                timeout,
            )
            data = fallback_rows
            sources.extend(src for src in fallback_sources if src not in sources)
            warnings.extend(fallback_warnings)
        if not data:
            data = _provider_unavailable_rows(instrument, limit, "No directly relevant crypto headlines or market context were returned for this symbol.")
            sources = sources or ["no_live_source"]
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


def _prefer_direct_symbol_matches(items: list[dict[str, Any]], *, min_rows: int) -> list[dict[str, Any]]:
    if not items:
        return []
    direct = [
        item for item in items
        if float(item.get("relevance_score") or 0) > 0
        and item.get("matched_terms")
        and not bool(item.get("stale_for_alert"))
    ]
    return direct if len(direct) >= min_rows else direct


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


async def _crypto_context_fallback_rows(
    instrument: Instrument,
    terms: list[str],
    limit: int,
    timeout: float,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    symbol = instrument.symbol.upper()
    base = _crypto_base(symbol)
    sources: list[str] = []
    warnings: list[str] = []
    headers = {"User-Agent": "showMe/1.0"}
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        tasks = [
            _binance_market_context_row(client, symbol),
            _coingecko_project_context_row(client, base),
            _google_crypto_news_rows(client, symbol, terms, limit),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    rows: list[dict[str, Any]] = []
    for name, result in zip(("binance", "coingecko", "google_news"), results):
        if isinstance(result, Exception):
            warnings.append(f"{name}: {result}")
            continue
        if not result:
            continue
        batch = result if isinstance(result, list) else [result]
        if batch:
            sources.append(name)
            rows.extend(batch)
    rows = _dedupe([row for row in rows if isinstance(row, dict)])
    rows.sort(
        key=lambda row: (
            float(row.get("importance_score") or 0),
            str(row.get("published_at") or ""),
        ),
        reverse=True,
    )
    return rows[: max(1, limit)], sources, warnings


async def _binance_market_context_row(client: httpx.AsyncClient, symbol: str) -> dict[str, Any] | None:
    ticker = None
    venue = "spot"
    for url, candidate_venue in (
        ("https://api.binance.com/api/v3/ticker/24hr", "spot"),
        ("https://fapi.binance.com/fapi/v1/ticker/24hr", "futures"),
    ):
        try:
            response = await client.get(url, params={"symbol": symbol})
            if response.status_code != 200:
                continue
            ticker = response.json() or {}
            venue = candidate_venue
            break
        except Exception:
            continue
    if not ticker:
        return None
    change = _num(ticker.get("priceChangePercent"))
    last = _num(ticker.get("lastPrice"))
    high = _num(ticker.get("highPrice"))
    low = _num(ticker.get("lowPrice"))
    quote_volume = _num(ticker.get("quoteVolume"))
    close_ms = _num(ticker.get("closeTime"))
    published = _millis_to_iso(close_ms) or datetime.now(timezone.utc).isoformat()
    abs_change = abs(change or 0.0)
    impact = min(100.0, 25.0 + abs_change * 2.0 + min((quote_volume or 0.0) / 2_000_000, 25.0))
    direction = "up" if (change or 0) > 0 else "down" if (change or 0) < 0 else "flat"
    summary_parts = [
        f"Binance {venue} market is live",
        f"last {_fmt_price(last)}",
        f"24h {change:+.2f}%" if change is not None else "",
        f"range {_fmt_price(low)} - {_fmt_price(high)}" if low is not None and high is not None else "",
        f"quote volume {_fmt_price(quote_volume)} USDT" if quote_volume is not None else "",
    ]
    return {
        "feed": f"Binance {venue.title()}",
        "title": f"{symbol} Binance {venue} market is live ({change:+.2f}% 24h)" if change is not None else f"{symbol} Binance {venue} market is live",
        "summary": " · ".join(part for part in summary_parts if part),
        "symbol": symbol,
        "source": "binance",
        "published_at": published,
        "url": f"https://www.binance.com/en/futures/{symbol}" if venue == "futures" else f"https://www.binance.com/en/trade/{symbol[:-4]}_USDT",
        "status": "market_context",
        "importance_score": round(impact, 1),
        "severity": "critical" if abs_change >= 15 else "high" if abs_change >= 5 else "medium",
        "alert": abs_change >= 10,
        "matched_terms": [symbol, _crypto_base(symbol)],
        "importance_reasons": [
            f"Binance {venue} listing active",
            f"24h move {direction} {abs_change:.2f}%",
        ],
    }


async def _coingecko_project_context_row(client: httpx.AsyncClient, base: str) -> dict[str, Any] | None:
    try:
        search = await client.get("https://api.coingecko.com/api/v3/search", params={"query": base})
        if search.status_code != 200:
            return None
        coins = (search.json() or {}).get("coins") or []
    except Exception:
        return None
    exact = [
        coin for coin in coins
        if str(coin.get("symbol") or "").upper() == base
    ]
    if not exact:
        return None
    exact.sort(key=lambda coin: int(coin.get("market_cap_rank") or 10_000_000))
    coin = exact[0]
    coin_id = str(coin.get("id") or "")
    if not coin_id:
        return None
    try:
        detail = await client.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}",
            params={
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false",
            },
        )
        if detail.status_code != 200:
            return None
        payload = detail.json() or {}
    except Exception:
        return None
    name = str(payload.get("name") or coin.get("name") or base)
    description = _clean_html(((payload.get("description") or {}).get("en") or ""))
    categories = [str(item) for item in (payload.get("categories") or [])[:4] if item]
    market = payload.get("market_data") if isinstance(payload.get("market_data"), dict) else {}
    price = _nested_num(market, "current_price", "usd")
    change = _num(market.get("price_change_percentage_24h"))
    rank = payload.get("market_cap_rank") or coin.get("market_cap_rank")
    summary_bits = [
        description[:340],
        f"categories: {', '.join(categories)}" if categories else "",
        f"rank #{rank}" if rank else "",
        f"price {_fmt_price(price)}" if price is not None else "",
        f"24h {change:+.2f}%" if change is not None else "",
    ]
    impact = 35.0 + min(abs(change or 0) * 1.5, 25.0)
    return {
        "feed": "CoinGecko",
        "title": f"{name} project profile and market context",
        "summary": " · ".join(part for part in summary_bits if part),
        "symbol": f"{base}USDT",
        "source": "coingecko",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "url": f"https://www.coingecko.com/en/coins/{coin_id}",
        "status": "project_context",
        "importance_score": round(impact, 1),
        "severity": "medium",
        "alert": False,
        "matched_terms": [base, name],
        "importance_reasons": ["CoinGecko project profile", "coin metadata fallback"],
    }


async def _google_crypto_news_rows(
    client: httpx.AsyncClient,
    symbol: str,
    terms: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    base = _crypto_base(symbol)
    display = _CRYPTO_NAMES.get(base, base)
    query_parts = [
        f'"{symbol}"',
        f'"{base} token"',
        f'"{base} price"',
        f'"{base} USDT"',
        f'"{base} unlock"',
    ]
    if display and display.lower() != base.lower():
        query_parts.append(f'"{display}"')
    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(" OR ".join(query_parts) + " when:30d")
        + "&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        response = await client.get(url)
        if response.status_code != 200:
            return []
    except Exception:
        return []
    rows = _parse_google_rss(response.text, url)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if not _google_crypto_row_relevant(row, symbol, base, display):
            continue
        score = _news_relevance_score(row, [symbol, base, display, *terms])
        row.update({
            "symbol": symbol,
            "source": "google_news",
            "status": "news_search",
            "importance_score": max(30.0, min(85.0, 30.0 + score * 4.0)),
            "severity": "medium" if score < 8 else "high",
            "alert": score >= 10,
            "matched_terms": [term for term in [symbol, base, display] if _term_in_text(term, _news_text(row))],
            "importance_reasons": ["Google News query match", "crypto fallback search"],
        })
        filtered.append(row)
    return filtered[: max(0, limit)]


def _parse_google_rss(xml_text: str, url: str) -> list[dict[str, Any]]:
    try:
        import feedparser  # type: ignore

        parsed = feedparser.parse(xml_text)
        rows: list[dict[str, Any]] = []
        for entry in parsed.entries:
            rows.append({
                "feed": _entry_source_title(entry),
                "title": html.unescape(str(entry.get("title") or "")),
                "summary": _clean_html(str(entry.get("summary") or "")),
                "link": entry.get("link") or "",
                "url": entry.get("link") or "",
                "published_at": _published_to_iso(entry),
            })
        return rows
    except Exception:
        pass
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except Exception:
        return []
    rows = []
    for item in root.findall(".//item"):
        rows.append({
            "feed": "Google News",
            "title": html.unescape(item.findtext("title") or ""),
            "summary": _clean_html(item.findtext("description") or ""),
            "link": item.findtext("link") or "",
            "url": item.findtext("link") or "",
            "published_at": _rss_pubdate_to_iso(item.findtext("pubDate")),
        })
    return rows


def _google_crypto_row_relevant(row: dict[str, Any], symbol: str, base: str, display: str) -> bool:
    text = _news_text(row)
    if _term_in_text(symbol, text):
        return True
    direct_name = display and display.lower() != base.lower() and _term_in_text(display, text)
    token_phrase = bool(re.search(rf"(?<![a-z0-9]){re.escape(base.lower())}(?![a-z0-9]).{{0,45}}\b(token|coin|price|usd|usdt|unlock|listing|binance|crypto)\b", text))
    reverse_phrase = bool(re.search(rf"\b(token|coin|price|usd|usdt|unlock|listing|binance|crypto)\b.{{0,45}}(?<![a-z0-9]){re.escape(base.lower())}(?![a-z0-9])", text))
    return bool(direct_name or token_phrase or reverse_phrase)


def _entry_source_title(entry: Any) -> str:
    source = entry.get("source") if hasattr(entry, "get") else None
    if isinstance(source, dict):
        return str(source.get("title") or "Google News")
    return "Google News"


def _published_to_iso(entry: Any) -> str:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _rss_pubdate_to_iso(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat()
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _millis_to_iso(value: float | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _nested_num(payload: dict[str, Any], key: str, subkey: str) -> float | None:
    value = payload.get(key)
    if not isinstance(value, dict):
        return None
    return _num(value.get(subkey))


def _fmt_price(value: float | None) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 1:
        return f"{value:.4f}"
    return f"{value:.8f}".rstrip("0").rstrip(".")


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


def _provider_unavailable_rows(instrument: Instrument, limit: int, reason: str) -> list[dict[str, Any]]:
    return [
        {
            "title": f"{instrument.symbol} news unavailable",
            "summary": reason,
            "symbol": instrument.symbol,
            "source": "showMe",
            "published_at": None,
            "url": None,
            "status": "provider_unavailable",
            "importance_score": 0,
            "severity": "unavailable",
            "alert": False,
            "importance_reasons": [reason],
        }
    ][: max(1, limit)]
