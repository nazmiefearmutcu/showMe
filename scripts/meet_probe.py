#!/usr/bin/env python3
"""MEET provider probe — Gate-3 cron (read-only, never fails).

Single live round over the keyless MEET sources:

  * FF    — ForexFactory weekly calendar JSON (schedule leg, ECO/MEET)
  * FC    — FinanceCalendar future-window supplement (required attribution)
  * GDELT — GDELT DOC 2.0 article list (world wire leg)
  * RSS   — fast world-wire RSS feed(s) (fallback leg)

Per source it records: latency_ms, count, http status (429 flagged
explicitly), timeout flag, and tagged_ratio (fraction of rows carrying
usable attribution — country/title/date for FF, title+url for
GDELT/RSS items).

Budget: every request carries its own timeout (default 10 s; ``--quick``
probes a single RSS feed) so a full round stays
well under 60 s. The script NEVER fails: every error is captured into
the report and the process always exits 0 so the cron workflow stays
green (informational probe, not a gate).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from showme.engine.services import world_events as we  # noqa: E402

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FC_URL = "https://www.financecalendar.com/wp-json/fc/v1/calendar"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
RSS_FEEDS_QUICK = ["https://feeds.bbci.co.uk/news/world/rss.xml"]
RSS_FEEDS_FULL = [
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://www.ft.com/?format=rss",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "https://www.nasdaq.com/feed/rssoutbound?category=Markets",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.investing.com/rss/news_25.rss",
    "https://www.prnewswire.com/rss/financial-services-latest-news/financial-services-latest-news-list.rss",
    "https://www.sec.gov/news/pressreleases.rss",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://www.theguardian.com/world/rss",
]
UA = {"User-Agent": "ShowMe-MEET-Probe/1.0"}
GLOBAL_BUDGET_S = 50.0


def _blank(source: str) -> dict:
    return {
        "source": source,
        "ok": False,
        "http_status": None,
        "latency_ms": None,
        "count": 0,
        "tagged_ratio": 0.0,
        "timed_count": 0,
        "undated_count": 0,
        "unique_count": 0,
        "duplicate_count": 0,
        "freshest_age_minutes": None,
        "field_complete_count": 0,
        "upcoming_count": 0,
        "attribution_present": False,
        "feeds_healthy_count": 0,
        "feeds_expected_count": 0,
        "threshold_failures": [],
        "rate_limited_429": False,
        "timeout": False,
        "note": "",
    }


def _timestamp(value) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 16 and raw.endswith("Z") and "T" in raw:
            return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _evaluate(row: dict) -> dict:
    """Advisory quality labels only; never controls process exit or CI gates."""
    source = row["source"]
    count = row["count"]
    failures: list[str] = []
    if row["rate_limited_429"]:
        failures.append("HTTP 429 rate limit")
    if row["timeout"]:
        failures.append("request timeout")
    if source == "gdelt" and row["latency_ms"] is not None and row["latency_ms"] > we.MEET_GDELT_TIMEOUT_SECONDS * 1000:
        failures.append("response exceeded MEET GDELT deadline")
    if source == "rss":
        if not row["feeds_expected_count"] or row["feeds_healthy_count"] < row["feeds_expected_count"]:
            failures.append("not all configured feeds healthy")
    elif row["http_status"] is None or not 200 <= row["http_status"] < 400:
        failures.append("HTTP unhealthy")
    if count == 0:
        failures.append("no rows")
    else:
        thresholds = {
            "ff": (0.95, 0.95, 0.99),
            "financecalendar": (0.80, 0.80, 0.95),
            "gdelt": (0.80, 0.90, 0.95),
            "rss": (0.80, 0.90, 0.95),
        }
        timed_min, complete_min, unique_min = thresholds[source]
        if row["timed_count"] / count < timed_min:
            failures.append(f"timed ratio < {timed_min:.0%}")
        if row["field_complete_count"] / count < complete_min:
            failures.append(f"field completeness < {complete_min:.0%}")
        if row["unique_count"] / count < unique_min:
            failures.append(f"unique ratio < {unique_min:.0%}")
    if source == "financecalendar":
        if not row["attribution_present"]:
            failures.append("required attribution missing")
        if row["upcoming_count"] == 0:
            failures.append("no timed upcoming events")
    if source == "ff" and row["upcoming_count"] == 0:
        failures.append("weekly snapshot has no upcoming events")
    if source in {"gdelt", "rss"}:
        age = row["freshest_age_minutes"]
        if age is None or age > 180:
            failures.append("freshest timestamp absent or > 180m old")
    row["threshold_failures"] = failures
    row["ok"] = not failures
    return row


def _probe_ff(client, timeout: float) -> dict:
    """ForexFactory weekly calendar JSON: count rows, tag = country+title+date."""
    row = _blank("ff")
    t0 = time.perf_counter()
    try:
        resp = client.get(FF_URL, timeout=timeout)
        row["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        row["http_status"] = resp.status_code
        if resp.status_code == 429:
            row["rate_limited_429"] = True
            row["note"] = "HTTP 429 rate-limited"
            return _evaluate(row)
        resp.raise_for_status()
        raw = resp.json()
        items = raw if isinstance(raw, list) else []
        row["count"] = len(items)
        tagged = sum(
            1
            for it in items
            if isinstance(it, dict)
            and str(it.get("country") or "").strip()
            and str(it.get("title") or "").strip()
            and str(it.get("date") or "").strip()
        )
        row["tagged_ratio"] = round(tagged / len(items), 3) if items else 0.0
        row["field_complete_count"] = tagged
        times = [_timestamp(it.get("date")) for it in items if isinstance(it, dict)]
        row["timed_count"] = sum(t is not None for t in times)
        row["undated_count"] = len(items) - row["timed_count"]
        row["upcoming_count"] = sum(t is not None and t > datetime.now(timezone.utc) for t in times)
        keys = {
            (str(it.get("date")), str(it.get("country")), str(it.get("title")))
            for it in items if isinstance(it, dict)
        }
        row["unique_count"] = len(keys)
        row["duplicate_count"] = len(items) - len(keys)
        row["note"] = f"{tagged}/{len(items)} rows with country+title+date"
    except Exception as exc:
        if row["latency_ms"] is None:
            row["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        name = type(exc).__name__
        if "Timeout" in name or "timed out" in str(exc).lower():
            row["timeout"] = True
        if "429" in str(exc):
            row["rate_limited_429"] = True
        row["note"] = f"{name}: {str(exc)[:160]}"
    return _evaluate(row)


def _probe_fc(client, timeout: float) -> dict:
    """FinanceCalendar's documented, attribution-required future feed."""
    row = _blank("financecalendar")
    t0 = time.perf_counter()
    now = datetime.now(timezone.utc)
    try:
        resp = client.get(
            FC_URL,
            params={"from": now.date().isoformat(), "to": (now + timedelta(days=92)).date().isoformat()},
            timeout=timeout,
        )
        row["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        row["http_status"] = resp.status_code
        if resp.status_code == 429:
            row["rate_limited_429"] = True
            row["note"] = "HTTP 429 rate-limited"
            return _evaluate(row)
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("events", []) if isinstance(payload, dict) else []
        attribution = payload.get("attribution") if isinstance(payload, dict) else None
        complete = sum(1 for it in items if isinstance(it, dict) and it.get("title") and it.get("time_utc") and it.get("impact"))
        keys = {(str(it.get("time_utc")), str(it.get("title"))) for it in items if isinstance(it, dict)}
        times = [_timestamp(it.get("time_utc")) for it in items if isinstance(it, dict)]
        row.update({
            "count": len(items),
            "tagged_ratio": round(complete / len(items), 3) if items else 0.0,
            "field_complete_count": complete,
            "timed_count": sum(t is not None for t in times),
            "undated_count": len(items) - sum(t is not None for t in times),
            "upcoming_count": sum(t is not None and t > now for t in times),
            "attribution_present": bool(attribution),
            "unique_count": len(keys),
            "duplicate_count": len(items) - len(keys),
            "note": f"{complete}/{len(items)} title+time_utc+impact; attribution={'present' if attribution else 'missing'}",
        })
    except Exception as exc:
        row["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        row["timeout"] = "Timeout" in type(exc).__name__ or "timed out" in str(exc).lower()
        row["rate_limited_429"] = "429" in str(exc)
        row["note"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return _evaluate(row)


def _probe_gdelt(client, timeout: float, maxrecords: int) -> dict:
    """GDELT DOC artlist: count articles, tag = title+url present."""
    row = _blank("gdelt")
    params = {
        "query": we.world_query(),
        "mode": "ArtList",
        "format": "json",
        "maxrecords": we.MEET_GDELT_LIMIT,
        "sort": "DateDesc",
        "startdatetime": (datetime.now(timezone.utc) - timedelta(days=we.MEET_GDELT_LOOKBACK_DAYS)).strftime("%Y%m%d%H%M%S"),
    }
    t0 = time.perf_counter()
    try:
        resp = client.get(GDELT_URL, params=params, timeout=min(timeout, we.MEET_GDELT_TIMEOUT_SECONDS))
        row["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        row["http_status"] = resp.status_code
        if resp.status_code == 429:
            row["rate_limited_429"] = True
            row["note"] = "HTTP 429 rate-limited"
            return _evaluate(row)
        resp.raise_for_status()
        articles = (resp.json() or {}).get("articles", []) or []
        row["count"] = len(articles)
        tagged = sum(
            1
            for a in articles
            if isinstance(a, dict) and a.get("title") and a.get("url")
        )
        row["tagged_ratio"] = round(tagged / len(articles), 3) if articles else 0.0
        row["field_complete_count"] = tagged
        times = [
            _timestamp(a.get("seendate") or a.get("published_at") or a.get("date"))
            for a in articles if isinstance(a, dict)
        ]
        row["timed_count"] = sum(t is not None for t in times)
        row["undated_count"] = len(articles) - row["timed_count"]
        urls = [str(a.get("url") or "").strip() for a in articles if isinstance(a, dict) and a.get("url")]
        row["unique_count"] = len(set(urls))
        row["duplicate_count"] = len(urls) - row["unique_count"]
        if any(t is not None for t in times):
            row["freshest_age_minutes"] = round(
                max(0.0, (datetime.now(timezone.utc) - max(t for t in times if t is not None)).total_seconds() / 60), 1
            )
        row["note"] = f"{tagged}/{len(articles)} articles with title+url"
    except Exception as exc:
        if row["latency_ms"] is None:
            row["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        name = type(exc).__name__
        if "Timeout" in name or "timed out" in str(exc).lower():
            row["timeout"] = True
        if "429" in str(exc):
            row["rate_limited_429"] = True
        row["note"] = f"{name}: {str(exc)[:160]}"
    return _evaluate(row)


def _probe_rss(client, timeout: float, feeds: list[str], deadline: float) -> dict:
    """RSS world wire: count items across feeds, tag = title+link present."""
    row = _blank("rss")
    t0 = time.perf_counter()
    total = 0
    tagged = 0
    statuses: list[str] = []
    try:
        def fetch_one(feed: str):
            resp = client.get(feed, timeout=timeout)
            resp.raise_for_status()
            return feed, resp

        dated: list[datetime] = []
        unique_urls: set[str] = set()
        healthy_feeds = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(feeds)) as pool:
            futures = {pool.submit(fetch_one, feed): feed for feed in feeds}
            for future in concurrent.futures.as_completed(futures):
                feed = futures[future]
                try:
                    _, resp = future.result()
                    statuses.append(f"{feed.split('/')[2]}={resp.status_code}")
                    root = ET.fromstring(resp.text)
                    healthy_feeds += 1
                    items = root.findall(".//item") or root.findall(".//{*}entry")
                    total += len(items)
                    for it in items:
                        title = ((it.findtext("title") or it.findtext("{*}title")) or "").strip()
                        link = ((it.findtext("link") or it.findtext("{*}link")) or "").strip()
                        if not link:
                            link_node = it.find("{*}link")
                            link = str(link_node.attrib.get("href") or "") if link_node is not None else ""
                        if title and link:
                            tagged += 1
                            unique_urls.add(link)
                        raw_date = (
                            it.findtext("pubDate") or it.findtext("{*}published")
                            or it.findtext("{*}updated") or ""
                        ).strip()
                        if raw_date:
                            try:
                                parsed = parsedate_to_datetime(raw_date)
                            except Exception:
                                try:
                                    parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                                except Exception:
                                    continue
                            if parsed.tzinfo is None:
                                parsed = parsed.replace(tzinfo=timezone.utc)
                            dated.append(parsed.astimezone(timezone.utc))
                except Exception as exc:
                    name = type(exc).__name__
                    row["timeout"] = row["timeout"] or "Timeout" in name or "timed out" in str(exc).lower()
                    row["rate_limited_429"] = row["rate_limited_429"] or "429" in str(exc)
                    statuses.append(f"{feed.split('/')[2]}:{name}")
        row["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        row["count"] = total
        row["feeds_healthy_count"] = healthy_feeds
        row["feeds_expected_count"] = len(feeds)
        row["tagged_ratio"] = round(tagged / total, 3) if total else 0.0
        row["field_complete_count"] = tagged
        row["timed_count"] = len(dated)
        row["undated_count"] = max(0, total - len(dated))
        row["unique_count"] = len(unique_urls)
        row["duplicate_count"] = max(0, tagged - len(unique_urls))
        if dated:
            row["freshest_age_minutes"] = round(
                max(0.0, (datetime.now(timezone.utc) - max(dated)).total_seconds() / 60), 1
            )
        row["note"] = (
            f"{tagged}/{total} title+link; freshest={row['freshest_age_minutes']}m; "
            f"feeds_healthy={healthy_feeds}/{len(feeds)}; " + "; ".join(statuses)
        )
    except Exception as exc:
        if row["latency_ms"] is None:
            row["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        row["note"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return _evaluate(row)


def _render(rows: list[dict], started: str, elapsed_ms: int, quick: bool) -> str:
    lines = [
        "# MEET probe report",
        "",
        f"- time (UTC): {started}",
        f"- mode: {'quick' if quick else 'full'} (single live round, informational — never gates)",
        f"- wall time: {elapsed_ms} ms (budget <60 s)",
        "",
        "| source | health | status | ms | rows | timed/undated | upcoming | unique/dup | complete | freshest min | 429 | timeout | threshold failures | note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['source']} | {'PASS' if r['ok'] else 'DEGRADED'} | {r['http_status']} | {r['latency_ms']} "
            f"| {r['count']} | {r['timed_count']}/{r['undated_count']} | {r['upcoming_count']} "
            f"| {r['unique_count']}/{r['duplicate_count']} | {r['field_complete_count']} "
            f"| {r['freshest_age_minutes']} | {r['rate_limited_429']} | {r['timeout']} "
            f"| {', '.join(r['threshold_failures']) or 'none'} | {r['note']} |"
        )
    down = [r["source"] for r in rows if not r["ok"]]
    lines += [
        "",
        ("All probed legs reachable." if not down
         else f"Degraded legs (informational only): {', '.join(down)}."),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="MEET live provider probe (never fails).")
    ap.add_argument("--quick", action="store_true", help="probe a single RSS feed")
    ap.add_argument("--out", default="meet-probe-report.md", help="report markdown path")
    ap.add_argument("--timeout", type=float, default=10.0, help="per-request timeout seconds")
    args = ap.parse_args()

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    wall0 = time.perf_counter()
    deadline = time.monotonic() + GLOBAL_BUDGET_S
    rows: list[dict] = []
    try:
        import httpx  # noqa: PLC0415  (workflow installs it; degrade gracefully without)

        feeds = RSS_FEEDS_QUICK if args.quick else RSS_FEEDS_FULL
        with httpx.Client(headers=UA, follow_redirects=True) as client:
            rows.append(_probe_ff(client, args.timeout))
            rows.append(_probe_fc(client, args.timeout))
            rows.append(_probe_gdelt(client, args.timeout, we.MEET_GDELT_LIMIT))
            rows.append(_probe_rss(client, args.timeout, feeds, deadline))
    except Exception as exc:  # e.g. httpx missing — still report, still exit 0
        note = f"{type(exc).__name__}: {str(exc)[:160]}"
        if not rows:
            for src in ("ff", "financecalendar", "gdelt", "rss"):
                blank = _blank(src)
                blank["note"] = note
                rows.append(blank)
    elapsed_ms = int((time.perf_counter() - wall0) * 1000)
    report = _render(rows, started, elapsed_ms, args.quick)
    try:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report)
    except Exception as exc:
        print(f"WARN: could not write {args.out}: {exc}", file=sys.stderr)
    print(report)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # absolute last resort — cron must stay green
        print(f"probe crashed (non-failing): {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(0)
