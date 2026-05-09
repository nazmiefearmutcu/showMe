"""News intelligence scoring and feed-health helpers.

This module stays deterministic: it does not call an LLM, so alarms are fast,
repeatable, and usable inside the local alert loop.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any


CRYPTO_NAMES = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "bnb",
    "XRP": "xrp",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche",
    "DOT": "polkadot",
    "LINK": "chainlink",
}

EQUITY_ALIASES = {
    "AAPL": ("apple", "apple inc"),
    "MSFT": ("microsoft", "microsoft corp"),
    "NVDA": ("nvidia",),
    "TSLA": ("tesla",),
    "AMZN": ("amazon",),
    "GOOG": ("google", "alphabet"),
    "GOOGL": ("google", "alphabet"),
    "META": ("meta", "facebook"),
    "NFLX": ("netflix",),
    "AVGO": ("broadcom",),
    "AMD": ("advanced micro devices", "amd"),
    "INTC": ("intel",),
    "JPM": ("jpmorgan", "jp morgan"),
    "BAC": ("bank of america",),
    "GS": ("goldman sachs",),
    "MS": ("morgan stanley",),
    "XOM": ("exxon", "exxonmobil"),
    "CVX": ("chevron",),
    "BRK.B": ("berkshire hathaway",),
    "SPY": ("s&p 500", "spdr s&p 500"),
    "QQQ": ("nasdaq 100", "invesco qqq"),
}

QUOTE_SUFFIXES = ("USDT", "USDC", "USD", "BTC", "ETH", "EUR")

CRITICAL_PATTERNS: list[tuple[str, float, str]] = [
    (r"\bbankrupt(cy)?\b|\bchapter 11\b|\binsolven", 38, "bankruptcy/insolvency"),
    (r"\bdefault\b|\bmissed payment\b|\bdebt restructuring\b", 34, "credit default"),
    (r"\btrading halt\b|\bhalted\b|\bsuspended trading\b", 34, "trading halt"),
    (r"\bsec\b.*\b(sues|charges|investigat|probe)\b|\bdoj\b.*\b(sues|charges|probe)\b", 34, "regulatory enforcement"),
    (r"\bfraud\b|\baccounting irregularit|\brestatement\b", 32, "fraud/accounting risk"),
    (r"\bhack(ed)?\b|\bexploit\b|\bsecurity breach\b|\bbridge attack\b", 36, "security exploit"),
    (r"\bliquidation\b|\bliquidat(ed|es)\b|\bmargin call\b", 30, "forced liquidation"),
    (r"\betf\b.*\b(approv|reject|delay)\b|\bspot bitcoin etf\b|\bether etf\b", 30, "ETF decision"),
    (r"\bmerger\b|\bacquisition\b|\btakeover\b|\bbuyout\b|\bto acquire\b", 26, "M&A"),
    (r"\bguidance\b.*\b(cut|raise|lower|withdraw)\b|\bprofit warning\b", 27, "guidance change"),
    (r"\bearnings\b.*\b(miss|beat)\b|\brevenue\b.*\b(miss|beat)\b", 21, "earnings surprise"),
    (r"\bdowngrade\b|\bupgrade\b|\bprice target\b", 16, "analyst action"),
    (r"\bceo\b.*\b(resign|steps down|ousted)\b|\bcfo\b.*\b(resign|steps down|ousted)\b", 25, "leadership shock"),
    (r"\bsanction(s)?\b|\bwar\b|\bmissile\b|\battack\b|\bceasefire\b", 22, "geopolitical shock"),
    (r"\bfederal reserve\b|\bfomc\b|\bpowell\b|\bcpi\b|\binflation\b|\bjobs report\b", 18, "macro catalyst"),
    (r"\boutage\b|\bsystem failure\b|\bnetwork down\b", 20, "infrastructure outage"),
]

SOURCE_WEIGHTS = [
    ("sec", 18, "regulatory source"),
    ("federal reserve", 14, "central-bank source"),
    ("dow jones", 10, "tier-1 market source"),
    ("bloomberg", 10, "tier-1 market source"),
    ("ft", 8, "tier-1 market source"),
    ("financial times", 8, "tier-1 market source"),
    ("cnbc", 7, "major market source"),
    ("coindesk", 8, "major crypto source"),
    ("the block", 8, "major crypto source"),
    ("cointelegraph", 5, "crypto source"),
    ("globenewswire", 5, "company-release source"),
    ("pr newswire", 5, "company-release source"),
]


def symbol_terms(symbol: str | None, query: str | None = None) -> list[str]:
    raw = (symbol or "").strip().upper()
    out: list[str] = []
    if raw:
        out.append(raw)
        base = crypto_base(raw)
        if base != raw:
            out.append(base)
        if base in CRYPTO_NAMES:
            out.append(CRYPTO_NAMES[base])
        if base == "ETH":
            out.append("ether")
        for alias in EQUITY_ALIASES.get(raw, ()):
            out.append(alias)
    if query:
        for part in re.split(r"[\s,/|()\"'-]+", str(query).lower()):
            if len(part) >= 3 and part not in {"stock", "market", "markets", "news", "latest"}:
                out.append(part)
    return list(dict.fromkeys(t for t in out if t))


def crypto_base(symbol: str) -> str:
    value = symbol.upper().replace("/", "").replace("-", "")
    for suffix in QUOTE_SUFFIXES:
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)]
    return value


def enrich_articles(
    items: list[Any],
    *,
    symbol: str | None = None,
    query: str | None = None,
    asset_class: str | None = None,
    threshold: float = 70.0,
    limit: int | None = None,
    max_alert_age_minutes: float | None = None,
) -> list[dict[str, Any]]:
    terms = symbol_terms(symbol, query)
    enriched: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        clean_article_text(item)
        if str(item.get("status") or "").startswith("provider_"):
            item.update({
                "importance_score": 0,
                "severity": "unavailable",
                "alert": False,
                "importance_reasons": ["provider unavailable"],
            })
            enriched.append(item)
            continue
        score, relevance, reasons, matched = score_article(
            item,
            terms=terms,
            asset_class=asset_class,
        )
        age_minutes = item.get("age_minutes")
        if max_alert_age_minutes and isinstance(age_minutes, (int, float)) and age_minutes > max_alert_age_minutes:
            score = min(score, threshold - 1.0)
            reasons.append(f"stale for alert window >{max_alert_age_minutes / 60:.0f}h")
            item["stale_for_alert"] = True
        item["relevance_score"] = round(relevance, 2)
        item["importance_score"] = round(score, 2)
        item["severity"] = severity_for_score(score)
        item["alert"] = score >= threshold and not bool(item.get("stale_for_alert"))
        item["matched_terms"] = matched
        item["importance_reasons"] = reasons[:6]
        enriched.append(item)
    enriched = sort_articles_newest_first(enriched)
    if limit:
        return enriched[:limit]
    return enriched


def score_article(
    item: dict[str, Any],
    *,
    terms: list[str],
    asset_class: str | None = None,
) -> tuple[float, float, list[str], list[str]]:
    title = text_for(item, title_only=True)
    text = text_for(item)
    source_text = " ".join(str(item.get(k) or "") for k in ("source", "feed", "publisher", "provider")).lower()
    score = 8.0
    relevance = 0.0
    reasons: list[str] = []
    matched: list[str] = []
    title_matched: list[str] = []

    for term in terms:
        term_score = 0.0
        if term_in_text(term, title):
            term_score = 22.0
            title_matched.append(term)
        elif term_in_text(term, text):
            term_score = 10.0
        if term_score:
            matched.append(term)
            relevance += term_score
    if matched:
        score += min(relevance, 32.0)
        reasons.append("symbol/query match: " + ", ".join(matched[:4]))
    elif terms:
        score -= 12.0
        reasons.append("weak symbol/query match")

    for pattern, weight, reason in CRITICAL_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            title_bonus = 6.0 if re.search(pattern, title, flags=re.IGNORECASE) else 0.0
            score += weight + title_bonus
            reasons.append(reason)

    for needle, weight, reason in SOURCE_WEIGHTS:
        source_hit = (
            bool(re.search(r"\bsec\b", f"{source_text} {text}")) if needle == "sec"
            else needle in source_text or needle in text
        )
        if source_hit:
            score += weight
            reasons.append(reason)
            break

    age_minutes = article_age_minutes(item)
    if age_minutes is not None:
        item["age_minutes"] = round(age_minutes, 1)
        if age_minutes <= 90:
            score += 14.0
            reasons.append("fresh <90m")
        elif age_minutes <= 360:
            score += 9.0
            reasons.append("fresh <6h")
        elif age_minutes <= 1440:
            score += 5.0
            reasons.append("fresh <24h")

    if str(asset_class or "").upper() == "CRYPTO":
        if re.search(r"\betf\b|\bsec\b|\bhack\b|\bexploit\b|\bliquidation\b|\bstaking\b", text, re.I):
            score += 8.0
            reasons.append("crypto-market catalyst")

    if terms and not matched:
        cap = 52.0 if str(asset_class or "").upper() == "CRYPTO" and "crypto" in text else 42.0
        score = min(score, cap)
        reasons.append("broad market item; no direct symbol match")
    elif terms and matched and not title_matched:
        score = min(score, 68.0)
        reasons.append("summary-only symbol match")

    return max(0.0, min(100.0, score)), relevance, unique(reasons), unique(matched)


def severity_for_score(score: float) -> str:
    if score >= 85:
        return "critical"
    if score >= 70:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def critical_articles(items: list[dict[str, Any]], threshold: float = 70.0) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if float(item.get("importance_score") or 0) >= threshold
        and not bool(item.get("stale_for_alert"))
    ]


def sort_articles_newest_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fallback = datetime.min.replace(tzinfo=timezone.utc)
    indexed: list[tuple[datetime, float, float, int, dict[str, Any]]] = []
    for idx, item in enumerate(items):
        ts = article_timestamp(item) or fallback
        indexed.append((
            ts,
            float(item.get("importance_score") or 0),
            float(item.get("relevance_score") or 0),
            -idx,
            item,
        ))
    indexed.sort(reverse=True)
    return [item for _, _, _, _, item in indexed]


def health_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    ok_rows = [row for row in rows if row.get("ok")]
    latencies = [
        float(row.get("latency_ms") or 0)
        for row in ok_rows
        if float(row.get("latency_ms") or 0) > 0
    ]
    return {
        "feeds": total,
        "ok": len(ok_rows),
        "failed": total - len(ok_rows),
        "ok_rate": round((len(ok_rows) / total) if total else 0.0, 3),
        "median_latency_ms": round(sorted(latencies)[len(latencies) // 2], 1) if latencies else None,
        "items": sum(int(row.get("items") or 0) for row in ok_rows),
    }


def text_for(item: dict[str, Any], title_only: bool = False) -> str:
    keys = ("title",) if title_only else (
        "title", "summary", "body", "description", "categories"
    )
    return " ".join(str(item.get(k) or "") for k in keys).lower()


def clean_article_text(item: dict[str, Any]) -> dict[str, Any]:
    for key in ("title", "headline", "summary", "description", "snippet"):
        value = item.get(key)
        if isinstance(value, str):
            item[key] = strip_markup(value)
    return item


def strip_markup(value: str) -> str:
    text = unescape(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def term_in_text(term: str, text: str) -> bool:
    needle = str(term or "").strip().lower()
    if not needle:
        return False
    if re.fullmatch(r"[a-z0-9]{2,12}", needle):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text))
    return needle in text


def article_age_minutes(item: dict[str, Any]) -> float | None:
    dt = article_timestamp(item)
    if dt is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60)


def article_timestamp(item: dict[str, Any]) -> datetime | None:
    raw = (
        item.get("published_at")
        or item.get("publishedAt")
        or item.get("published_on")
        or item.get("published")
        or item.get("date")
        or item.get("datetime")
        or item.get("time")
        or item.get("ts")
    )
    if not raw:
        return None
    return parse_news_timestamp(raw)


def parse_news_timestamp(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    lowered = raw.lower()
    now = datetime.now(timezone.utc)
    if lowered in {"now", "just now", "az once", "az önce"}:
        return now

    relative = re.fullmatch(
        r"(\d+)\s*(s|sec|secs|second|seconds|sn|m|min|mins|minute|minutes|dk|dakika|h|hr|hrs|hour|hours|saat|d|day|days|gün|gun|w|week|weeks|hafta|mo|month|months|ay|y|yr|year|years|yıl|yil)(?:\s*(ago|once|önce))?",
        lowered,
    )
    if relative:
        amount = max(0, int(relative.group(1)))
        unit = relative.group(2)
        minute = timedelta(minutes=1)
        hour = timedelta(hours=1)
        day = timedelta(days=1)
        multipliers = {
            "s": timedelta(seconds=1),
            "sec": timedelta(seconds=1),
            "secs": timedelta(seconds=1),
            "second": timedelta(seconds=1),
            "seconds": timedelta(seconds=1),
            "sn": timedelta(seconds=1),
            "m": minute,
            "min": minute,
            "mins": minute,
            "minute": minute,
            "minutes": minute,
            "dk": minute,
            "dakika": minute,
            "h": hour,
            "hr": hour,
            "hrs": hour,
            "hour": hour,
            "hours": hour,
            "saat": hour,
            "d": day,
            "day": day,
            "days": day,
            "gun": day,
            "gün": day,
            "w": 7 * day,
            "week": 7 * day,
            "weeks": 7 * day,
            "hafta": 7 * day,
            "mo": 30 * day,
            "month": 30 * day,
            "months": 30 * day,
            "ay": 30 * day,
            "y": 365 * day,
            "yr": 365 * day,
            "year": 365 * day,
            "years": 365 * day,
            "yil": 365 * day,
            "yıl": 365 * day,
        }
        return now - amount * multipliers.get(unit, day)

    date_only = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if date_only:
        year, month, day = (int(part) for part in date_only.groups())
        return datetime(year, month, day, tzinfo=timezone.utc)

    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))
