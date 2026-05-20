"""Veryfinder sidecar bridge for existing ShowMe panes.

Veryfinder is intentionally exposed as an auxiliary data overlay, not as a new
ShowMe terminal function. The bridge imports the local project when present and
returns compact, UI-safe social-view summaries.
"""
from __future__ import annotations

import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from lxml import html as lxml_html

from showme.crypto_aliases import CRYPTO_DISPLAY_NAMES

DEFAULT_ROOT = Path("~/Desktop/Projeler/veryfinder").expanduser()
INTEGRATION_ROOT_NAME = "veryfinder"
INTEGRATION_ROOT_PARTS = ("integrations", INTEGRATION_ROOT_NAME)
MIN_SEARCH_SAMPLE = 140
DEFAULT_SAMPLE = MIN_SEARCH_SAMPLE
CACHE_TTL_SECONDS = 300.0
FIXTURE_SIGNAL_FALLBACK_RELEVANCE = 0.15
FIXTURE_TOPIC_TERMS = {"btc", "bitcoin", "eth", "ethereum", "sol", "solana", "crypto"}
NEWS_PROXY_SOURCE = "news_proxy"
PUBLIC_SEARCH_SOURCE = "public_search"
try:
    PUBLIC_SEARCH_TIMEOUT_SECONDS = max(1.0, float(os.environ.get("SHOWME_VERYFINDER_SEARCH_TIMEOUT", "2.0")))
except ValueError:
    PUBLIC_SEARCH_TIMEOUT_SECONDS = 2.0
try:
    PUBLIC_SEARCH_MAX_QUERIES = max(1, int(os.environ.get("SHOWME_VERYFINDER_MAX_QUERIES", "4")))
except ValueError:
    PUBLIC_SEARCH_MAX_QUERIES = 4
try:
    RECENT_EVIDENCE_DAYS = max(1, int(os.environ.get("SHOWME_VERYFINDER_RECENT_DAYS", "30")))
except ValueError:
    RECENT_EVIDENCE_DAYS = 30
QUERY_STOPWORDS = {
    "a",
    "about",
    "after",
    "and",
    "announces",
    "april",
    "are",
    "as",
    "at",
    "between",
    "by",
    "for",
    "earnings",
    "from",
    "in",
    "into",
    "is",
    "it",
    "its",
    "lang",
    "market",
    "may",
    "more",
    "news",
    "no",
    "not",
    "of",
    "on",
    "or",
    "over",
    "retweet",
    "rose",
    "says",
    "stock",
    "stocks",
    "than",
    "their",
    "the",
    "to",
    "with",
    "without",
    "women",
}

_CACHE: dict[tuple[str, int, str, str, str], tuple[float, dict[str, Any]]] = {}

CRYPTO_ALIASES = {base: name.lower() for base, name in CRYPTO_DISPLAY_NAMES.items()}

NEWS_PROXY_POSITIVE_TERMS = {
    "accumulate",
    "advance",
    "back",
    "backed",
    "backs",
    "boost",
    "bullish",
    "confirmed",
    "confidence",
    "gain",
    "gains",
    "growth",
    "innovation",
    "launch",
    "launched",
    "positive",
    "record",
    "roadmap",
    "safe",
    "secure",
    "support",
    "surge",
    "treasury",
    "upgrade",
}

NEWS_PROXY_NEGATIVE_TERMS = {
    "attack",
    "bearish",
    "breach",
    "crackdown",
    "crash",
    "decline",
    "delay",
    "drop",
    "exploit",
    "fall",
    "fraud",
    "hack",
    "lawsuit",
    "loss",
    "negative",
    "probe",
    "risk",
    "selloff",
    "slump",
    "warning",
}

NEWS_PROXY_BUY_TERMS = {"buy", "long", "accumulate", "added", "adds"}
NEWS_PROXY_SELL_TERMS = {"sell", "short", "exit", "reduce", "cut", "dump"}

VIEW_LABELS = {
    "bullish_or_confident": "bullish/confident",
    "bearish_or_panic": "bearish/panic",
    "neutral_or_waiting": "neutral/waiting",
    "fomo_chasing": "FOMO chasing",
    "no_data": "no data",
}


def health() -> dict[str, Any]:
    root = veryfinder_root()
    if root is None:
        return {
            "ok": False,
            "status": "missing",
            "root": None,
            "message": (
                "Veryfinder runtime was not found in the showMe integration cache. "
                "ANR will continue without requesting Desktop access."
            ),
            "checked": [str(path) for path in veryfinder_root_candidates(include_untrusted=False)],
        }
    try:
        _load_veryfinder(root)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "import_error",
            "root": str(root),
            "message": str(exc),
        }
    env_file = root / ".env"
    return {
        "ok": True,
        "status": "ok",
        "root": str(root),
        "fixture_path": str(default_fixture_path(root)),
        "has_x_bearer_token": bool(os.environ.get("X_BEARER_TOKEN")) or env_file.is_file(),
        "meaning": overlay_meaning(),
    }


def analyze_symbol(
    symbol: str | None,
    *,
    q: str | None = None,
    sample: int = DEFAULT_SAMPLE,
    source: str = "auto",
    engine: str = "rules",
    refresh: bool = False,
) -> dict[str, Any]:
    query = clean_query(q) if q else symbol_query(symbol)
    return analyze_query(query, sample=sample, source=source, engine=engine, refresh=refresh)


def analyze_item(
    item: dict[str, Any],
    *,
    symbol: str | None = None,
    topic: str | None = None,
    sample: int = DEFAULT_SAMPLE,
    source: str = "auto",
    engine: str = "rules",
) -> dict[str, Any]:
    query = article_query(item, symbol=symbol, topic=topic)
    overlay = analyze_query(query, sample=sample, source=source, engine=engine)
    if should_use_news_proxy(overlay, item=item, symbol=symbol, topic=topic):
        fallback = news_proxy_overlay(item, query=query, sample=sample, engine=engine)
        fallback["source_requested"] = source
        fallback["source_fallback_from"] = overlay.get("source")
        fallback["fixture_mode"] = False
        fallback["fallback_mode"] = "article_context"
        fallback["model_notes"] = [
            *fallback.get("model_notes", []),
            "X/fixture social source had no query-relevant posts; scored the visible news item as an RSS/news context proxy instead.",
        ]
        return fallback
    return overlay


def analyze_batch(
    items: list[dict[str, Any]],
    *,
    symbol: str | None = None,
    topic: str | None = None,
    sample: int = DEFAULT_SAMPLE,
    source: str = "auto",
    engine: str = "rules",
    limit: int = 12,
) -> dict[str, Any]:
    overlays: list[dict[str, Any]] = []
    max_items = max(0, int(limit or len(items)))
    for index, item in enumerate(items[:max_items]):
        key = str(item.get("key") or item.get("url") or item.get("link") or item.get("title") or index)
        item_sample = item.get("sample") or item.get("min_tweets") or sample
        overlay = analyze_item(
            item,
            symbol=str(item.get("symbol") or symbol or "") or None,
            topic=topic,
            sample=item_sample,
            source=source,
            engine=engine,
        )
        overlays.append({"key": key, "overlay": overlay})
    return {
        "ok": True,
        "count": len(overlays),
        "items": overlays,
        "meaning": overlay_meaning(),
    }


def analyze_query(
    query: str,
    *,
    sample: int = DEFAULT_SAMPLE,
    source: str = "auto",
    engine: str = "rules",
    refresh: bool = False,
) -> dict[str, Any]:
    query = clean_query(query)
    if not query:
        raise ValueError("query is required")
    sample = normalize_sample(sample, source=source)
    engine = (engine or "rules").strip().lower()
    root = veryfinder_root()
    if root is None:
        return unavailable_overlay(
            query,
            sample=sample,
            source=source,
            engine=engine,
            reason="Veryfinder integration cache is missing; Desktop fallback is disabled in packaged showMe.",
        )
    try:
        vf_cls, config_cls = _load_veryfinder(root)
        config = config_cls.from_env(env_file=root / ".env")
    except Exception as exc:  # noqa: BLE001
        return unavailable_overlay(
            query,
            sample=sample,
            source=source,
            engine=engine,
            reason=f"Veryfinder import/config failed from {root}: {exc}",
        )
    resolved_source = resolve_source(source, config)
    fixture_path = str(default_fixture_path(root)) if resolved_source == "fixture" else ""
    cache_key = (query, sample, resolved_source, engine, fixture_path)
    previous_cached = _cache_get(cache_key)
    cached = None if refresh else previous_cached
    if cached is not None:
        cached["cache"] = "hit"
        return cached
    vf = vf_cls(config)
    report = vf.analyze_query(
        query=query,
        sample=sample,
        source=resolved_source,
        engine=engine,
        fixture_path=fixture_path or None,
    )
    overlay = compact_report(report.to_dict(include_posts=True), engine=engine)
    overlay["source_requested"] = source
    overlay["fixture_mode"] = resolved_source == "fixture"
    if should_expand_public_search(overlay, requested_source=source, resolved_source=resolved_source):
        fallback = public_search_overlay(query, sample=sample, engine=engine)
        if int(_as_float(fallback.get("unique_accounts"))) > 0:
            fallback["source_requested"] = source
            fallback["source_fallback_from"] = overlay.get("source")
            fallback["fixture_mode"] = False
            fallback["fallback_mode"] = "expanded_public_search"
            fallback["model_notes"] = [
                "auto source had zero query-relevant tweet evidence; expanded to public web/social search",
                *fallback.get("model_notes", []),
                *overlay.get("model_notes", []),
            ]
            fallback["cache"] = "refresh" if refresh else "miss"
            _cache_set(cache_key, fallback)
            return fallback
        retained = retained_cached_overlay(
            previous_cached,
            reason="live refresh returned no usable new rows; previous rolling window retained",
        )
        if refresh and retained is not None:
            return retained
        overlay["fallback_mode"] = "search_exhausted"
        overlay["model_notes"] = [
            *overlay.get("model_notes", []),
            "auto source had zero query-relevant tweet evidence; public web/social search also returned no usable evidence",
        ]
    retained = retained_cached_overlay(
        previous_cached,
        reason="live refresh returned no query-relevant rows; previous rolling window retained",
    )
    if refresh and int(_as_float(overlay.get("unique_accounts"))) == 0 and retained is not None:
        return retained
    overlay["cache"] = "refresh" if refresh else "miss"
    _cache_set(cache_key, overlay)
    return overlay


def unavailable_overlay(
    query: str,
    *,
    sample: int,
    source: str,
    engine: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "query": clean_query(query),
        "source": "unavailable",
        "engine": engine,
        "dominant_view": {
            "label": "no_data",
            "display": VIEW_LABELS["no_data"],
            "score": 0.0,
        },
        "label": "no data 0%",
        "tone": "muted",
        "social_score": 0,
        "impact_score": 0,
        "quality": "veryfinder unavailable",
        "unique_accounts": 0,
        "requested_sample": max(1, int(sample or DEFAULT_SAMPLE)),
        "collected_posts": 0,
        "source_posts": 0,
        "tweet_count_estimate": None,
        "view_distribution": {},
        "sentiment_distribution": {},
        "mood_distribution": {},
        "action_distribution": {},
        "top_mood": None,
        "top_action": None,
        "posts": [],
        "analyzed_posts": [],
        "model_notes": [reason],
        "meaning": overlay_meaning(),
        "source_requested": source,
        "fixture_mode": False,
        "fallback_mode": "unavailable",
    }


def normalize_sample(sample: int | str | None, *, source: str | None) -> int:
    try:
        parsed = int(float(sample or DEFAULT_SAMPLE))
    except (TypeError, ValueError):
        parsed = DEFAULT_SAMPLE
    requested = (source or "auto").strip().lower()
    if requested in {"", "auto", "official", "x", "x-api", "twikit"}:
        return max(MIN_SEARCH_SAMPLE, parsed)
    return max(1, parsed)


def compact_report(raw: dict[str, Any], *, engine: str) -> dict[str, Any]:
    source = str(raw.get("source") or "unknown")
    analyzed_posts = raw.get("analyzed_posts")
    query = str(raw.get("query") or "")
    score_posts = scoreable_posts(analyzed_posts, source=source, query=query)
    filtered_by_relevance = isinstance(analyzed_posts, list) and len(score_posts) != len(analyzed_posts)
    view_distribution = distribution_from_posts(score_posts, "view")
    sentiment_distribution = distribution_from_posts(score_posts, "sentiment")
    mood_distribution = distribution_from_posts(score_posts, "mood")
    action_distribution = distribution_from_posts(score_posts, "action")
    if view_distribution:
        label, confidence = max(view_distribution.items(), key=lambda item: item[1])
        if source in {NEWS_PROXY_SOURCE, PUBLIC_SEARCH_SOURCE}:
            label_scores = [
                _as_float((item.get("view") or {}).get("score"))
                for item in score_posts
                if nested_label(item.get("view")) == label
            ]
            if label_scores:
                confidence = sum(label_scores) / len(label_scores)
        dominant = {"label": label, "score": confidence}
    else:
        raw_dominant = raw.get("dominant_view") if isinstance(raw.get("dominant_view"), dict) else {}
        use_raw = source != "fixture" and not isinstance(analyzed_posts, list)
        dominant = raw_dominant if use_raw else {"label": "no_data", "score": 0.0}
        if use_raw:
            view_distribution = _dict_float(raw.get("view_distribution"))
            sentiment_distribution = _dict_float(raw.get("sentiment_distribution"))
            mood_distribution = _dict_float(raw.get("mood_distribution"))
            action_distribution = _dict_float(raw.get("action_distribution"))
    label = str(dominant.get("label") or "no_data")
    confidence = _as_float(dominant.get("score"))
    social_score, tone = social_score_from_view(label, confidence)
    unique_accounts = unique_account_count(score_posts) if isinstance(analyzed_posts, list) else int(_as_float(raw.get("unique_accounts")))
    requested_sample = int(_as_float(raw.get("requested_sample")))
    raw_collected_posts = int(_as_float(raw.get("collected_posts")))
    collected_posts = len(score_posts) if isinstance(analyzed_posts, list) else raw_collected_posts
    if unique_accounts == 0:
        quality = "no query-relevant posts"
    elif unique_accounts < min(5, requested_sample):
        quality = "thin sample"
    else:
        quality = "ok"
    model_notes = [str(note) for note in raw.get("model_notes") or []]
    if filtered_by_relevance:
        model_notes.append(f"fixture relevance filter kept {len(score_posts)}/{len(analyzed_posts)} posts")
    if source == "fixture" and not score_posts:
        model_notes.append("fixture source has no query-relevant demo posts; score withheld")
    return {
        "ok": True,
        "query": query,
        "source": source,
        "engine": engine,
        "dominant_view": {
            "label": label,
            "display": VIEW_LABELS.get(label, label.replace("_", " ")),
            "score": round(confidence, 4),
        },
        "label": overlay_label(label, confidence),
        "tone": tone,
        "social_score": social_score,
        "impact_score": impact_score_from_view(label, confidence, unique_accounts),
        "quality": quality,
        "unique_accounts": unique_accounts,
        "requested_sample": requested_sample,
        "collected_posts": collected_posts,
        "source_posts": raw_collected_posts,
        "tweet_count_estimate": raw.get("tweet_count_estimate"),
        "evidence_window_days": raw.get("evidence_window_days"),
        "evidence_cutoff": raw.get("evidence_cutoff"),
        "rolling_window_size": raw.get("rolling_window_size"),
        "refreshed_at": raw.get("refreshed_at"),
        "view_distribution": view_distribution,
        "sentiment_distribution": sentiment_distribution,
        "mood_distribution": mood_distribution,
        "action_distribution": action_distribution,
        "top_mood": top_distribution(mood_distribution),
        "top_action": top_distribution(action_distribution),
        "posts": compact_posts(score_posts),
        "analyzed_posts": compact_posts(score_posts),
        "model_notes": model_notes,
        "meaning": overlay_meaning(),
    }


def should_expand_public_search(
    overlay: dict[str, Any],
    *,
    requested_source: str | None,
    resolved_source: str,
) -> bool:
    requested = (requested_source or "auto").strip().lower()
    if requested not in {"", "auto"}:
        return False
    if resolved_source != "fixture":
        return False
    return int(_as_float(overlay.get("unique_accounts"))) == 0


def retained_cached_overlay(cached: dict[str, Any] | None, *, reason: str) -> dict[str, Any] | None:
    if not cached or int(_as_float(cached.get("unique_accounts"))) <= 0:
        return None
    retained = dict(cached)
    retained["cache"] = "retained"
    retained["refreshed_at"] = now_utc_iso()
    retained["model_notes"] = [
        reason,
        *[str(note) for note in retained.get("model_notes") or []],
    ]
    return retained


def public_search_overlay(query: str, *, sample: int, engine: str) -> dict[str, Any]:
    items = public_search_items(query, sample=sample)
    analyses: list[dict[str, Any]] = []
    for index, item in enumerate(items[:sample]):
        text = article_text(item)
        if not text:
            continue
        labels = classify_news_proxy(text)
        source_name = str(item.get("source") or "public search")
        url = item.get("url") or item.get("link")
        post = {
            "id": str(url or item.get("id") or f"public-search-{index}"),
            "text": text,
            "author_id": source_name,
            "username": source_name,
            "created_at": item.get("published_at") or item.get("published") or item.get("date"),
            "url": url,
            "lang": item.get("lang") or "en",
            "source": PUBLIC_SEARCH_SOURCE,
            "like_count": 0,
            "reply_count": 0,
            "repost_count": 0,
            "quote_count": 0,
            "view_count": 0,
        }
        analyses.append({
            "post": post,
            "relevance": labels["relevance"],
            "sentiment": labels["sentiment"],
            "financial_sentiment": labels["sentiment"],
            "emotion": labels["mood"],
            "action": labels["action"],
            "mood": labels["mood"],
            "view": labels["view"],
            "themes": labels["themes"],
            "emoji_reactions": {},
            "signals": labels["signals"],
        })
    raw = {
        "source": PUBLIC_SEARCH_SOURCE,
        "query": query,
        "requested_sample": sample,
        "collected_posts": len(items),
        "tweet_count_estimate": None,
        "evidence_window_days": RECENT_EVIDENCE_DAYS,
        "evidence_cutoff": recent_evidence_cutoff().isoformat(),
        "rolling_window_size": sample,
        "refreshed_at": now_utc_iso(),
        "model_notes": [
            f"public search fallback collected {len(items)} candidate evidence rows",
            f"public search evidence is limited to the last {RECENT_EVIDENCE_DAYS} days when the source exposes a date",
            f"rolling evidence window keeps the newest {sample} rows and drops older rows first",
            "rows are public web/news/social evidence because X API/Twikit credentials were unavailable",
        ],
        "analyzed_posts": analyses,
    }
    return compact_report(raw, engine=engine)


def public_search_items(query: str, *, sample: int) -> list[dict[str, Any]]:
    limit = max(int(sample or DEFAULT_SAMPLE), MIN_SEARCH_SAMPLE)
    collect_limit = limit
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    cutoff = recent_evidence_cutoff()
    for item in yahoo_finance_news_items(query, sample=collect_limit):
        _append_unique_search_item(items, seen, item, collect_limit, cutoff=cutoff)
        if len(items) >= collect_limit:
            break
    if len(items) >= limit:
        return sort_public_items_newest_first(items)[:limit]
    with httpx.Client(
        timeout=PUBLIC_SEARCH_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 showMe/veryfinder"},
    ) as client:
        for search_query in public_search_queries(query)[:PUBLIC_SEARCH_MAX_QUERIES]:
            if len(items) >= collect_limit:
                break
            for item in google_news_items(client, search_query):
                if _append_unique_search_item(items, seen, item, collect_limit, cutoff=cutoff):
                    continue
            if len(items) >= collect_limit:
                break
            for item in duckduckgo_items(client, search_query):
                _append_unique_search_item(items, seen, item, collect_limit, cutoff=cutoff)
                if len(items) >= collect_limit:
                    break
    return sort_public_items_newest_first(items)[:limit]


def yahoo_finance_news_items(query: str, *, sample: int) -> list[dict[str, Any]]:
    ticker = equity_ticker_from_query(query)
    if not ticker:
        return []
    try:
        import yfinance as yf

        news = yf.Ticker(ticker).news
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for entry in list(news or [])[: max(1, int(sample or DEFAULT_SAMPLE))]:
        content = entry.get("content") if isinstance(entry, dict) and isinstance(entry.get("content"), dict) else entry
        if not isinstance(content, dict):
            continue
        title = clean_html_text(str(content.get("title") or ""))
        summary = clean_html_text(str(content.get("summary") or content.get("description") or ""))
        provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
        provider_name = str(provider.get("displayName") or "Yahoo Finance")
        url = nested_url(content.get("clickThroughUrl")) or nested_url(content.get("canonicalUrl"))
        published_at = str(content.get("pubDate") or content.get("displayTime") or "")
        if not title:
            continue
        items.append({
            "title": title,
            "summary": summary,
            "source": provider_name,
            "url": url,
            "published_at": published_at,
            "category": "yahoo finance rolling news",
        })
    return items


def equity_ticker_from_query(query: str) -> str:
    raw_query = query.lower()
    if "crypto" in raw_query or "usdt" in raw_query or "usdc" in raw_query:
        return ""
    for token in re.findall(r"\$?([A-Za-z][A-Za-z0-9.-]{0,7})", query):
        clean = token.upper().strip(".")
        if clean.lower() in QUERY_STOPWORDS or clean in {"OR", "AND"}:
            continue
        if 1 <= len(clean) <= 5 and clean.replace(".", "").isalnum():
            return clean
    return ""


def nested_url(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("url") or "")
    return ""


def public_search_queries(query: str) -> list[str]:
    terms = list(query_terms(query))
    priority = [
        term for term in terms
        if term not in {"stock", "earnings", "market", "retweet"} and not term.startswith("is")
    ]
    if not priority:
        priority = ["market"]
    compact = " ".join(priority[:4])
    first = priority[0]
    cashtag = f"${first.upper()}" if re.fullmatch(r"[a-z0-9]{2,12}", first) else first
    raw_query = query.lower()
    is_crypto = "crypto" in raw_query or any(term.endswith(("usdt", "usdc", "usd")) for term in priority)
    if is_crypto:
        queries = [
            f"{compact} crypto twitter X",
            f"{compact} crypto token news",
            f"site:x.com {compact} crypto",
            f"{cashtag} crypto",
            f"{compact} Binance",
            f"{compact} TradingView",
            f"{compact} CoinMarketCap",
            f"{compact} token price",
            f"{compact} liquidity volume",
            f"{compact} partnership roadmap",
            f"{compact} AI crypto",
            f"{compact} decentralized AI",
        ]
        if "." in first:
            queries.append(f"{first} crypto")
        elif len(first) <= 8:
            queries.append(f"{first}USDT crypto")
            queries.append(f"{first}USDT Binance futures")
            queries.append(f"{first}USDT MEXC")
    else:
        ticker = first.upper()
        queries = [
            f"{ticker} stock news",
            f"{ticker} earnings news",
            f"{cashtag} stock",
            f"site:x.com {cashtag} stock",
            f"{ticker} market reaction",
            f"{ticker} Yahoo Finance",
            f"{ticker} Reuters",
            f"{ticker} analyst rating",
        ]
    return _dedupe_strings(queries)


def google_news_items(client: httpx.Client, query: str) -> list[dict[str, Any]]:
    recent_query = f"{query} when:{RECENT_EVIDENCE_DAYS}d"
    url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(recent_query)}&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        response = client.get(url)
        response.raise_for_status()
        root = ET.fromstring(response.text)
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for node in root.findall(".//item"):
        title = _node_text(node, "title")
        link = _node_text(node, "link")
        source_node = node.find("source")
        source = source_node.text.strip() if source_node is not None and source_node.text else "Google News"
        source_url = source_node.attrib.get("url") if source_node is not None else ""
        summary = clean_html_text(_node_text(node, "description"))
        if not title:
            continue
        items.append({
            "title": title,
            "summary": summary,
            "source": source,
            "source_url": source_url,
            "url": link,
            "published_at": _node_text(node, "pubDate"),
            "category": "public search",
        })
    return items


def duckduckgo_items(client: httpx.Client, query: str) -> list[dict[str, Any]]:
    try:
        response = client.get(
            "https://duckduckgo.com/html/",
            params={"q": query, "df": duckduckgo_date_filter()},
        )
        response.raise_for_status()
        doc = lxml_html.fromstring(response.text)
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for result in doc.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' result ')]"):
        anchor = result.xpath(".//a[contains(concat(' ', normalize-space(@class), ' '), ' result__a ')]")
        if not anchor:
            continue
        raw_url = anchor[0].get("href") or ""
        title = clean_html_text(anchor[0].text_content())
        snippet_nodes = result.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' result__snippet ')]")
        summary = clean_html_text(snippet_nodes[0].text_content()) if snippet_nodes else ""
        url = resolve_duckduckgo_url(raw_url)
        source = urlparse(url).netloc.replace("www.", "") if url else "DuckDuckGo"
        if not title:
            continue
        items.append({
            "title": title,
            "summary": summary,
            "source": source or "DuckDuckGo",
            "url": url,
            "published_at": None,
            "category": "public search",
        })
    return items


def _append_unique_search_item(
    items: list[dict[str, Any]],
    seen: set[str],
    item: dict[str, Any],
    limit: int,
    *,
    cutoff: datetime | None = None,
) -> bool:
    key = str(item.get("url") or item.get("title") or "").strip()
    if not key or key in seen or len(items) >= limit:
        return False
    if not is_recent_public_item(item, cutoff=cutoff):
        return False
    seen.add(key)
    items.append(item)
    return True


def recent_evidence_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=RECENT_EVIDENCE_DAYS)


def duckduckgo_date_filter() -> str:
    if RECENT_EVIDENCE_DAYS <= 1:
        return "d"
    if RECENT_EVIDENCE_DAYS <= 7:
        return "w"
    if RECENT_EVIDENCE_DAYS <= 31:
        return "m"
    return "y"


def is_recent_public_item(item: dict[str, Any], *, cutoff: datetime | None = None) -> bool:
    published = public_item_datetime(item)
    if published is None:
        return True
    threshold = cutoff or recent_evidence_cutoff()
    now = datetime.now(timezone.utc)
    if published > now + timedelta(days=1):
        return False
    return published >= threshold


def public_item_datetime(item: dict[str, Any]) -> datetime | None:
    for key in ("published_at", "published", "date", "created_at"):
        parsed = parse_public_datetime(item.get(key))
        if parsed is not None:
            return parsed
    return parse_public_datetime(f"{item.get('title') or ''} {item.get('summary') or ''}")


def sort_public_items_newest_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]) -> tuple[int, float]:
        published = public_item_datetime(item)
        if published is None:
            return (0, 0.0)
        return (1, published.timestamp())

    return sorted(items, key=key, reverse=True)


def parse_public_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is not None:
        return ensure_utc(parsed)
    relative = parse_relative_datetime(text)
    if relative is not None:
        return relative
    for candidate in date_candidates(text):
        for fmt in (
            "%m/%d/%Y, %I:%M:%S %p",
            "%m/%d/%Y, %I:%M %p",
            "%m/%d/%Y",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                return ensure_utc(datetime.strptime(candidate, fmt))
            except ValueError:
                continue
    return None


def parse_relative_datetime(text: str) -> datetime | None:
    match = re.search(r"\b(\d+)\s+(minute|hour|day|week|month)s?\s+ago\b", text, re.I)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit == "minute":
        delta = timedelta(minutes=amount)
    elif unit == "hour":
        delta = timedelta(hours=amount)
    elif unit == "day":
        delta = timedelta(days=amount)
    elif unit == "week":
        delta = timedelta(weeks=amount)
    else:
        delta = timedelta(days=amount * 30)
    return datetime.now(timezone.utc) - delta


def date_candidates(text: str) -> list[str]:
    candidates = re.findall(
        r"\b\d{1,2}/\d{1,2}/\d{4}(?:,\s*\d{1,2}:\d{2}(?::\d{2})?\s*[AP]M)?\b",
        text,
        flags=re.I,
    )
    candidates.extend(re.findall(r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:?\d{2})?)?\b", text))
    return candidates


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _node_text(node: ET.Element, child: str) -> str:
    found = node.find(child)
    return str(found.text or "").strip() if found is not None else ""


def resolve_duckduckgo_url(raw_url: str) -> str:
    value = str(raw_url or "")
    parsed = urlparse(value)
    params = parse_qs(parsed.query)
    if "uddg" in params and params["uddg"]:
        return unquote(params["uddg"][0])
    return value


def clean_html_text(value: str | None) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def veryfinder_root() -> Path | None:
    for candidate in veryfinder_root_candidates():
        root = candidate.expanduser()
        if (root / "veryfinder" / "orchestrator.py").is_file():
            return root.resolve()
    return None


def veryfinder_root_candidates(*, include_untrusted: bool = True) -> list[Path]:
    candidates: list[Path] = []
    override = os.environ.get("SHOWME_VERYFINDER_ROOT")
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(app_support_veryfinder_root())
    bundled = bundled_veryfinder_root()
    if bundled is not None:
        candidates.append(bundled)
    if include_untrusted and allow_desktop_veryfinder_fallback():
        candidates.append(DEFAULT_ROOT)
    return _dedupe_paths(candidates)


def app_support_veryfinder_root() -> Path:
    return app_home().joinpath(*INTEGRATION_ROOT_PARTS)


def bundled_veryfinder_root() -> Path | None:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if not frozen_root:
        return None
    return Path(frozen_root).joinpath(*INTEGRATION_ROOT_PARTS)


def app_home() -> Path:
    override = os.environ.get("SHOWME_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "showMe"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "showMe"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "showMe"


def allow_desktop_veryfinder_fallback() -> bool:
    if _truthy(os.environ.get("SHOWME_ALLOW_DESKTOP_VERYFINDER")):
        return True
    if getattr(sys, "_MEIPASS", None):
        return False
    return not _falsy(os.environ.get("SHOWME_ALLOW_DESKTOP_VERYFINDER"))


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _falsy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"0", "false", "no", "off"}


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    output: list[Path] = []
    for path in paths:
        key = str(path.expanduser())
        if key in seen:
            continue
        seen.add(key)
        output.append(path)
    return output


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        clean = re.sub(r"\s+", " ", str(value or "")).strip()
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        output.append(clean)
    return output


def default_fixture_path(root: Path) -> Path:
    return root / "data" / "fixtures" / "sample_posts.jsonl"


def _load_veryfinder(root: Path):
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    from veryfinder.config import VeryfinderConfig
    from veryfinder.orchestrator import Veryfinder

    return Veryfinder, VeryfinderConfig


def resolve_source(source: str | None, config: Any) -> str:
    requested = (source or "auto").strip().lower()
    if requested in {"", "auto"}:
        return "official" if getattr(config, "x_bearer_token", None) else "fixture"
    if requested in {"x", "x-api"}:
        return "official"
    return requested


def symbol_query(symbol: str | None) -> str:
    clean = re.sub(r"[^A-Za-z0-9=^./-]", "", str(symbol or "")).upper()
    if not clean:
        return "market news"
    base = clean.replace("/", "").replace("-", "").lstrip("^")
    for suffix in ("USDT", "USDC", "USD", "BTC", "ETH", "=X", "=F"):
        if base.endswith(suffix) and len(base) > len(suffix):
            base = base[: -len(suffix)]
            break
    alias = CRYPTO_ALIASES.get(base)
    if alias:
        return f"{base} OR {alias} -is:retweet"
    if len(base) <= 5:
        return f"${base} OR {base} stock OR {base} earnings -is:retweet"
    return f"{base} market news -is:retweet"


def article_query(item: dict[str, Any], *, symbol: str | None = None, topic: str | None = None) -> str:
    parts = [
        item.get("title"),
        item.get("headline"),
        item.get("summary"),
        item.get("category"),
        topic,
    ]
    if symbol:
        parts.insert(0, symbol_query(symbol))
    raw = " ".join(str(part) for part in parts if part)
    return clean_query(raw)[:420] or symbol_query(symbol) or "market news"


def clean_query(value: str | None) -> str:
    text = re.sub(r"https?://\S+", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def social_score_from_view(label: str, confidence: float) -> tuple[int, str]:
    if label == "bullish_or_confident":
        return int(round(confidence * 100)), "positive"
    if label == "bearish_or_panic":
        return -int(round(confidence * 100)), "negative"
    if label == "fomo_chasing":
        return int(round(confidence * 50)), "warn"
    return 0, "muted"


def impact_score_from_view(label: str, confidence: float, unique_accounts: int) -> int:
    """Non-directional VF display score.

    ``social_score`` is signed and intentionally returns zero for
    neutral/waiting views. The terminal still needs a visible VF score when
    evidence exists, so this score measures inference strength instead of trade
    direction.
    """

    if label == "no_data" or unique_accounts <= 0:
        return 0
    return int(round(max(0.0, min(1.0, confidence)) * 100))


def overlay_label(label: str, confidence: float) -> str:
    display = VIEW_LABELS.get(label, label.replace("_", " "))
    return f"{display} {round(confidence * 100):.0f}%"


def should_use_news_proxy(
    overlay: dict[str, Any],
    *,
    item: dict[str, Any],
    symbol: str | None,
    topic: str | None,
) -> bool:
    if not isinstance(item, dict) or not item_has_real_news_text(item):
        return False
    if int(_as_float(overlay.get("unique_accounts"))) > 0:
        return False
    source = str(overlay.get("source") or "").lower()
    requested = str(overlay.get("source_requested") or "").lower()
    if source not in {"fixture", "official"} and requested not in {"auto", "fixture", "official", "x", "x-api"}:
        return False
    return article_has_symbol_context(item, symbol=symbol, topic=topic)


def item_has_real_news_text(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").lower()
    if status in {"provider_unavailable", "news_feed_empty"}:
        return False
    title = str(item.get("title") or item.get("headline") or "").strip()
    summary = str(item.get("summary") or item.get("description") or "").strip()
    return bool(title and len(f"{title} {summary}".strip()) >= 16)


def article_has_symbol_context(
    item: dict[str, Any],
    *,
    symbol: str | None,
    topic: str | None,
) -> bool:
    text = article_text(item).lower()
    candidates = set(query_terms(symbol_query(symbol))) if symbol else set()
    if topic:
        candidates |= query_terms(topic)
    raw_symbols = item.get("symbols")
    if isinstance(raw_symbols, list):
        for raw in raw_symbols:
            candidates |= query_terms(symbol_query(str(raw)))
    if item.get("symbol"):
        candidates |= query_terms(symbol_query(str(item.get("symbol"))))
    candidates = {term for term in candidates if term not in {"stock", "earnings", "market"}}
    if not candidates:
        return False
    if candidates & FIXTURE_TOPIC_TERMS:
        return bool((candidates & FIXTURE_TOPIC_TERMS) & query_terms(text))
    return any(_term_in_text(term, text) for term in candidates)


def news_proxy_overlay(
    item: dict[str, Any],
    *,
    query: str,
    sample: int,
    engine: str,
) -> dict[str, Any]:
    text = article_text(item)
    labels = classify_news_proxy(text)
    source_name = str(item.get("source") or item.get("publisher") or "news")
    url = item.get("url") or item.get("link")
    post = {
        "id": str(url or item.get("id") or item.get("title") or "news-context"),
        "text": text,
        "author_id": source_name,
        "username": source_name,
        "created_at": item.get("published_at") or item.get("publishedAt") or item.get("published") or item.get("date"),
        "url": url,
        "lang": item.get("lang") or item.get("language"),
        "source": NEWS_PROXY_SOURCE,
        "like_count": 0,
        "reply_count": 0,
        "repost_count": 0,
        "quote_count": 0,
        "view_count": 0,
    }
    raw = {
        "source": NEWS_PROXY_SOURCE,
        "query": query,
        "requested_sample": sample,
        "collected_posts": 1,
        "tweet_count_estimate": None,
        "model_notes": ["article/news context proxy used"],
        "analyzed_posts": [
            {
                "post": post,
                "relevance": labels["relevance"],
                "sentiment": labels["sentiment"],
                "financial_sentiment": labels["sentiment"],
                "emotion": labels["mood"],
                "action": labels["action"],
                "mood": labels["mood"],
                "view": labels["view"],
                "themes": labels["themes"],
                "emoji_reactions": {},
                "signals": labels["signals"],
            }
        ],
    }
    return compact_report(raw, engine=engine)


def classify_news_proxy(text: str) -> dict[str, Any]:
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    positive = len(tokens & NEWS_PROXY_POSITIVE_TERMS)
    negative = len(tokens & NEWS_PROXY_NEGATIVE_TERMS)
    buy = len(tokens & NEWS_PROXY_BUY_TERMS)
    sell = len(tokens & NEWS_PROXY_SELL_TERMS)
    signals: list[str] = []
    if positive:
        signals.append(f"positive_terms:{positive}")
    if negative:
        signals.append(f"negative_terms:{negative}")
    if positive > negative:
        confidence = min(0.88, 0.58 + 0.06 * positive)
        view = {"label": "bullish_or_confident", "score": confidence}
        sentiment = {"label": "positive", "score": confidence}
        mood = {"label": "confidence", "score": min(0.86, confidence)}
    elif negative > positive:
        confidence = min(0.88, 0.58 + 0.06 * negative)
        view = {"label": "bearish_or_panic", "score": confidence}
        sentiment = {"label": "negative", "score": confidence}
        mood = {"label": "fear", "score": min(0.86, confidence)}
    else:
        confidence = 0.56
        view = {"label": "neutral_or_waiting", "score": confidence}
        sentiment = {"label": "neutral", "score": confidence}
        mood = {"label": "uncertainty", "score": 0.52}
    if buy > sell:
        action = {"label": "buy", "score": min(0.78, 0.55 + 0.08 * buy)}
    elif sell > buy:
        action = {"label": "sell", "score": min(0.78, 0.55 + 0.08 * sell)}
    else:
        action = {"label": "no clear trading advice", "score": 0.55}
    themes = []
    if "treasury" in tokens:
        themes.append({"label": "treasury adoption", "score": 0.7})
    if "etf" in tokens:
        themes.append({"label": "ETF flow", "score": 0.7})
    if "staking" in tokens:
        themes.append({"label": "staking", "score": 0.65})
    if "roadmap" in tokens or "upgrade" in tokens:
        themes.append({"label": "protocol roadmap", "score": 0.65})
    return {
        "relevance": 0.82 if signals else 0.62,
        "sentiment": sentiment,
        "mood": mood,
        "action": action,
        "view": view,
        "themes": themes,
        "signals": signals or ["news_context"],
    }


def article_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("title", "headline", "summary", "description", "category", "source")
        if item.get(key)
    ).strip()


def _term_in_text(term: str, text: str) -> bool:
    needle = str(term or "").strip().lower()
    if not needle:
        return False
    if re.fullmatch(r"[a-z0-9]{2,8}", needle):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text))
    return needle in text


def overlay_meaning() -> str:
    return (
        "Veryfinder measures the dominant unique-account X/RSS market view for the query. "
        "It is social confirmation/contradiction, not analyst consensus, target price, or trade advice."
    )


def top_distribution(distribution: dict[str, float]) -> dict[str, Any] | None:
    if not distribution:
        return None
    label, score = max(distribution.items(), key=lambda item: item[1])
    return {"label": label, "score": round(float(score), 4)}


def scoreable_posts(items: Any, *, source: str, query: str) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    posts = [item for item in items if isinstance(item, dict)]
    if source != "fixture":
        return posts
    terms = query_terms(query)
    return [
        item for item in posts
        if _as_float(item.get("relevance")) > FIXTURE_SIGNAL_FALLBACK_RELEVANCE + 0.0001
        and query_matches_post(terms, item)
    ]


def query_terms(query: str) -> set[str]:
    terms: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9$#^=.-]+", query.lower()):
        clean = token.strip("$#^").strip("-").replace("=f", "").replace("=x", "")
        if not clean or clean in QUERY_STOPWORDS or clean.startswith("is:"):
            continue
        if len(clean) <= 1 and clean not in {"x"}:
            continue
        terms.add(clean)
    return terms


def query_matches_post(terms: set[str], item: dict[str, Any]) -> bool:
    if not terms:
        return False
    post = item.get("post") if isinstance(item.get("post"), dict) else {}
    text = str(post.get("text") or "").lower()
    post_terms = {token.strip("$#^") for token in re.findall(r"[A-Za-z0-9$#^=.-]+", text)}
    topic_terms = terms & FIXTURE_TOPIC_TERMS
    if not topic_terms:
        return False
    return bool(topic_terms & post_terms)


def distribution_from_posts(items: list[dict[str, Any]], field: str) -> dict[str, float]:
    counter: Counter[str] = Counter()
    for item in items:
        label = nested_label(item.get(field))
        if label:
            counter[label] += 1
    total = sum(counter.values())
    if total <= 0:
        return {}
    return {label: round(count / total, 4) for label, count in sorted(counter.items())}


def nested_label(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get("label") or "")


def unique_account_count(items: list[dict[str, Any]]) -> int:
    seen: set[str] = set()
    for item in items:
        post = item.get("post") if isinstance(item.get("post"), dict) else {}
        key = str(post.get("author_id") or post.get("username") or post.get("id") or "")
        if key:
            seen.add(key)
    return len(seen)


def compact_posts(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        post = item.get("post") if isinstance(item.get("post"), dict) else {}
        text = str(post.get("text") or "")
        out.append({
            "id": str(post.get("id") or ""),
            "text": text,
            "username": post.get("username"),
            "author_id": post.get("author_id"),
            "created_at": post.get("created_at"),
            "url": post.get("url"),
            "lang": post.get("lang"),
            "source": post.get("source"),
            "like_count": int(_as_float(post.get("like_count"))),
            "reply_count": int(_as_float(post.get("reply_count"))),
            "repost_count": int(_as_float(post.get("repost_count"))),
            "quote_count": int(_as_float(post.get("quote_count"))),
            "view_count": int(_as_float(post.get("view_count"))),
            "engagement": (
                int(_as_float(post.get("like_count")))
                + int(_as_float(post.get("reply_count")))
                + int(_as_float(post.get("repost_count")))
                + int(_as_float(post.get("quote_count")))
            ),
            "relevance": round(_as_float(item.get("relevance")), 4),
            "sentiment": _label_score(item.get("sentiment")),
            "financial_sentiment": _label_score(item.get("financial_sentiment")),
            "emotion": _label_score(item.get("emotion")),
            "action": _label_score(item.get("action")),
            "mood": _label_score(item.get("mood")),
            "view": _label_score(item.get("view")),
            "signals": [str(signal) for signal in item.get("signals") or []],
        })
    return out


def _label_score(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "label": str(value.get("label") or ""),
        "score": round(_as_float(value.get("score")), 4),
    }


def _dict_float(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {str(key): round(_as_float(item), 4) for key, item in value.items()}


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _cache_get(key: tuple[str, int, str, str, str]) -> dict[str, Any] | None:
    cached = _CACHE.get(key)
    if cached is None:
        return None
    created, payload = cached
    if time.monotonic() - created > CACHE_TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    return {**payload, "cache": "hit"}


def _cache_set(key: tuple[str, int, str, str, str], payload: dict[str, Any]) -> None:
    if len(_CACHE) > 256:
        oldest = sorted(_CACHE.items(), key=lambda item: item[1][0])[:64]
        for old_key, _ in oldest:
            _CACHE.pop(old_key, None)
    _CACHE[key] = (time.monotonic(), {**payload, "cache": "miss"})
