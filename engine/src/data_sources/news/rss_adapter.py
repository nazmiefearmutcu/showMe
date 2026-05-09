"""RSS feed aggregator — Reuters, FT, Bloomberg, CNBC, NPR.

DATA PIPELINE:
    Source: feed list from config/data_sources.yaml ``rss.feeds``.
    Latency: per-feed ~500ms.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree as ET

import httpx

from src.core.base_data_source import BaseDataSource, DataKind, DataRequest


_MARKET_FEEDS = [
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://www.ft.com/?format=rss",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "https://www.nasdaq.com/feed/rssoutbound?category=Markets",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.investing.com/rss/news_25.rss",
    "https://www.prnewswire.com/rss/financial-services-latest-news/financial-services-latest-news-list.rss",
    "https://www.globenewswire.com/RssFeed/subjectcode/27-News-Releases/feedTitle/GlobeNewswire%20-%20News%20about%20Financial%20Services",
    "https://www.sec.gov/news/pressreleases.rss",
]

_CRYPTO_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://www.coindesk.com/arc/outboundfeeds/rss",
    "https://www.theblock.co/rss.xml",
]
_DEFAULT_FEEDS = list(dict.fromkeys([*_MARKET_FEEDS, *_CRYPTO_FEEDS]))


class RSSAdapter(BaseDataSource):
    name = "rss"
    supported_kinds = (DataKind.NEWS,)
    rate_limit_rps = 5.0
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        config = config or {}
        self.per_feed_timeout_seconds = float(config.get("per_feed_timeout_seconds", 2.5))
        self.collection_timeout_seconds = float(config.get("collection_timeout_seconds", 2.0))
        self.symbol_feed_timeout_seconds = float(config.get("symbol_feed_timeout_seconds", 2.4))
        self.market_feeds: list[str] = list(config.get("market_feeds", _MARKET_FEEDS))
        self.crypto_feeds: list[str] = list(config.get("crypto_feeds", _CRYPTO_FEEDS))
        self.feeds: list[str] = list(
            config.get("feeds", [*self.market_feeds, *self.crypto_feeds])
        )
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout_seconds,
                headers={"User-Agent": "ShowMe-RSS/0.1"},
                follow_redirects=True,
            )
        return self._client

    async def _fetch_feed(self, url: str, timeout: float | None = None) -> list[dict[str, Any]]:
        client = await self._client_()
        try:
            r = await client.get(url, timeout=timeout or self.per_feed_timeout_seconds)
            r.raise_for_status()
        except Exception:
            return []
        return _parse_feed(r.text, url)

    async def probe_feeds(
        self,
        request: DataRequest | None = None,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        feeds = self._feeds_for(request or DataRequest(kind=DataKind.NEWS))
        per_feed_timeout = timeout or self.per_feed_timeout_seconds

        async def probe(url: str) -> dict[str, Any]:
            started = time.perf_counter()
            client = await self._client_()
            try:
                r = await client.get(url, timeout=per_feed_timeout)
                latency_ms = (time.perf_counter() - started) * 1000
                parsed_items = _parse_feed(r.text, url)
                items = len(parsed_items)
                ok = 200 <= r.status_code < 400 and items > 0
                return {
                    "url": url,
                    "feed": parsed_items[0].get("feed", url) if parsed_items else url,
                    "ok": ok,
                    "status_code": r.status_code,
                    "latency_ms": round(latency_ms, 1),
                    "items": items,
                    "error": None if ok else ("empty feed" if items == 0 else f"HTTP {r.status_code}"),
                }
            except Exception as exc:
                return {
                    "url": url,
                    "feed": url,
                    "ok": False,
                    "status_code": None,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    "items": 0,
                    "error": str(exc) or type(exc).__name__,
                }

        tasks = [asyncio.create_task(probe(url)) for url in feeds]
        done, pending = await asyncio.wait(tasks, timeout=per_feed_timeout + 0.7)
        for task in pending:
            task.cancel()
        rows = [task.result() for task in done if not task.cancelled()]
        rows.extend({
            "url": feeds[idx],
            "feed": feeds[idx],
            "ok": False,
            "status_code": None,
            "latency_ms": round((per_feed_timeout + 0.7) * 1000, 1),
            "items": 0,
            "error": "timeout",
        } for idx, task in enumerate(tasks) if task in pending)
        rows.sort(key=lambda row: (not bool(row.get("ok")), float(row.get("latency_ms") or 0)))
        return rows

    def _feeds_for(self, request: DataRequest) -> list[str]:
        group = str((request.extra or {}).get("feed_group") or "").lower()
        asset_class = str((request.extra or {}).get("asset_class") or "").upper()
        symbol = _request_symbol(request)
        if group == "crypto" or asset_class == "CRYPTO":
            return self.crypto_feeds
        if group == "market":
            return _with_symbol_feeds(self.market_feeds, symbol)
        return self.feeds

    async def fetch(self, request: DataRequest) -> list[dict[str, Any]]:
        feeds = self._feeds_for(request)
        symbol_feeds = [u for u in feeds if "rssoutbound?symbol=" in u]
        extra = request.extra or {}
        collection_timeout = _float_extra(
            extra,
            "collection_timeout_seconds",
            self.collection_timeout_seconds,
        )
        per_feed_timeout = _float_extra(
            extra,
            "per_feed_timeout_seconds",
            collection_timeout,
        )
        symbol_feed_timeout = _float_extra(
            extra,
            "symbol_feed_timeout_seconds",
            max(per_feed_timeout, self.symbol_feed_timeout_seconds),
        )
        results = await self._collect_feeds(
            feeds,
            timeout_for={
                url: symbol_feed_timeout if url in symbol_feeds else per_feed_timeout
                for url in feeds
            },
        )
        articles: list[dict[str, Any]] = [a for batch in results for a in batch]
        terms = _request_terms(request)
        optional_terms = _request_terms(request, "optional_terms")
        if terms:
            scored = [
                (_score_article(a, terms, optional_terms), a)
                for a in articles
                if _matches_terms(a, terms)
            ]
            scored.sort(key=lambda item: (item[0], item[1].get("published_at", "")), reverse=True)
            articles = [a for _, a in scored]
        else:
            articles.sort(key=lambda x: x.get("published_at", ""), reverse=True)
        if request.limit:
            articles = articles[: request.limit]
        return articles

    async def _collect_feeds(self, feeds: list[str], timeout_for: dict[str, float]) -> list[list[dict[str, Any]]]:
        tasks = [
            asyncio.create_task(self._fetch_feed(url, timeout_for.get(url)))
            for url in feeds
        ]
        timeout = max(timeout_for.values(), default=self.collection_timeout_seconds)
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        for task in pending:
            task.cancel()
        results: list[list[dict[str, Any]]] = []
        for task in done:
            try:
                results.append(task.result())
            except Exception:
                results.append([])
        return results


def _request_terms(request: DataRequest, key: str = "terms") -> list[str]:
    raw_terms = request.extra.get(key) if request.extra else None
    if isinstance(raw_terms, list):
        return [str(t).lower() for t in raw_terms if str(t).strip()]
    if key != "terms":
        return []
    query = (
        (request.extra or {}).get("query")
        or (request.instrument.symbol if request.instrument else None)
        or (request.symbols[0] if request.symbols else None)
    )
    if not query:
        return []
    return [
        part.strip().strip('"').lower()
        for part in str(query).replace("|", " OR ").split("OR")
        if part.strip()
    ]


def _request_symbol(request: DataRequest) -> str:
    raw = (
        (request.instrument.symbol if request.instrument else None)
        or (request.symbols[0] if request.symbols else None)
        or (request.extra or {}).get("symbol")
        or ""
    )
    return str(raw).strip().upper()


def _with_symbol_feeds(base_feeds: list[str], symbol: str) -> list[str]:
    if not symbol:
        return base_feeds
    clean = re.sub(r"[^A-Z0-9.\-]", "", symbol)
    if not clean or len(clean) > 12:
        return base_feeds
    symbol_feeds = [
        f"https://www.nasdaq.com/feed/rssoutbound?symbol={quote(clean)}",
    ]
    return list(dict.fromkeys([*symbol_feeds, *base_feeds]))


def _parse_feed(xml_text: str, url: str) -> list[dict[str, Any]]:
    try:
        import feedparser  # type: ignore

        parsed = feedparser.parse(xml_text)
        out: list[dict[str, Any]] = []
        for entry in parsed.entries:
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            ts = (
                datetime(*published[:6], tzinfo=timezone.utc)
                if published else datetime.now(timezone.utc)
            )
            out.append({
                "feed": parsed.feed.get("title", url),
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", ""),
                "published_at": ts.isoformat(),
                "source": "rss",
            })
        if out:
            return out
    except Exception:
        pass
    return _parse_feed_stdlib(xml_text, url)


def _parse_feed_stdlib(xml_text: str, url: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except Exception:
        return []
    channel = root.find("channel")
    feed_title = _node_text(channel, "title") if channel is not None else _node_text(root, "{*}title")
    feed_title = feed_title or url
    nodes = list(root.findall(".//item")) or list(root.findall(".//{*}entry"))
    out: list[dict[str, Any]] = []
    for node in nodes:
        title = _node_text(node, "title") or _node_text(node, "{*}title")
        link = _node_text(node, "link") or _node_text(node, "{*}link")
        if not link:
            link_node = node.find("{*}link")
            if link_node is not None:
                link = link_node.attrib.get("href", "")
        summary = (
            _node_text(node, "description")
            or _node_text(node, "{*}summary")
            or _node_text(node, "{*}content")
        )
        published_raw = (
            _node_text(node, "pubDate")
            or _node_text(node, "{*}published")
            or _node_text(node, "{*}updated")
        )
        out.append({
            "feed": feed_title,
            "title": title,
            "link": link,
            "summary": summary,
            "published_at": _parse_date(published_raw).isoformat(),
            "source": "rss",
        })
    return out


def _node_text(node: ET.Element | None, path: str) -> str:
    if node is None:
        return ""
    found = node.find(path)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def _float_extra(extra: dict[str, Any], key: str, default: float) -> float:
    try:
        return max(0.5, float(extra.get(key, default)))
    except Exception:
        return default


def _parse_date(value: str) -> datetime:
    if value:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


def _matches_terms(article: dict[str, Any], terms: list[str]) -> bool:
    return any(_term_in_text(term, _article_text(article)) for term in terms)


def _score_article(
    article: dict[str, Any],
    required_terms: list[str],
    optional_terms: list[str],
) -> float:
    title = str(article.get("title") or "").lower()
    text = _article_text(article)
    score = 0.0
    for term in required_terms:
        if _term_in_text(term, title):
            score += 5.0
        elif _term_in_text(term, text):
            score += 2.0
    for term in optional_terms:
        if _term_in_text(term, title):
            score += 1.5
        elif _term_in_text(term, text):
            score += 0.5
    return score


def _article_text(article: dict[str, Any]) -> str:
    text = " ".join(
        str(article.get(k) or "")
        for k in ("title", "summary", "category")
    ).lower()
    return text


def _term_in_text(term: str, text: str) -> bool:
    needle = str(term or "").strip().lower()
    if not needle:
        return False
    if re.fullmatch(r"[a-z0-9]{2,6}", needle):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text))
    return needle in text
