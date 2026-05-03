#!/usr/bin/env python3
"""Audit ShowMe public API/RSS sources for speed, fallback, and relevance."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"
sys.path.insert(0, str(ENGINE))

from src.core.base_data_source import DataKind, DataRequest  # noqa: E402
from src.core.instrument import AssetClass, Instrument  # noqa: E402
from src.functions.news.cn import CNFunction, _news_relevance_score, _crypto_specific_terms  # noqa: E402
from src.services.function_factory import FunctionFactory  # noqa: E402


KEY_ENVS = {
    "alphavantage": "ALPHAVANTAGE_API_KEY",
    "eia": "EIA_API_KEY",
    "finnhub": "FINNHUB_API_KEY",
    "finnhub_news": "FINNHUB_API_KEY",
    "fred": "FRED_API_KEY",
    "polygon": "POLYGON_API_KEY",
    "stooq": "STOOQ_API_KEY",
    "openweather": "OPENWEATHERMAP_API_KEY",
    "sentinelhub": "SENTINELHUB_CLIENT_ID",
}


@dataclass
class Check:
    name: str
    group: str
    status: str
    elapsed_ms: int
    source: str | None = None
    count: int | None = None
    reason: str = ""
    sample: str = ""


def now_ms() -> int:
    return int(time.perf_counter() * 1000)


def count_payload(value: Any) -> int | None:
    if value is None:
        return 0
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("rows", "articles", "Data", "data"):
            if isinstance(value.get(key), list):
                return len(value[key])
        return len(value)
    if hasattr(value, "empty"):
        return 0 if value.empty else len(value)
    return None


def sample_payload(value: Any) -> str:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("title") or first.get("symbol") or first.get("source") or first)[:160]
        return str(first)[:160]
    if isinstance(value, dict):
        return str(value.get("title") or value.get("symbol") or value.get("source") or value)[:160]
    if hasattr(value, "source"):
        return str(getattr(value, "source", ""))[:160]
    return str(value)[:160]


def payload_source(value: Any) -> str | None:
    if hasattr(value, "source"):
        return str(getattr(value, "source", ""))
    if isinstance(value, dict):
        return str(value.get("source") or value.get("provider") or "") or None
    if isinstance(value, list) and value and isinstance(value[0], dict):
        sources = sorted({str(x.get("source") or x.get("provider") or "") for x in value if isinstance(x, dict)})
        return ",".join(s for s in sources if s)[:160] or None
    return None


async def timed(
    name: str,
    group: str,
    call: Callable[[], Awaitable[Any]],
    timeout: float = 12.0,
) -> tuple[Check, Any | None]:
    start = now_ms()
    try:
        payload = await asyncio.wait_for(call(), timeout=timeout)
        elapsed = now_ms() - start
        count = count_payload(payload)
        status = "PASS" if count is None or count > 0 else "WARN"
        reason = "" if status == "PASS" else "empty payload"
        return Check(
            name=name,
            group=group,
            status=status,
            elapsed_ms=elapsed,
            source=payload_source(payload),
            count=count,
            reason=reason,
            sample=sample_payload(payload),
        ), payload
    except Exception as exc:  # noqa: BLE001
        return Check(
            name=name,
            group=group,
            status="FAIL",
            elapsed_ms=now_ms() - start,
            reason=f"{type(exc).__name__}: {exc}",
        ), None


def missing_key(adapter_name: str) -> bool:
    env = KEY_ENVS.get(adapter_name)
    return bool(env and not os.environ.get(env))


async def audit_adapter_cases(factory: FunctionFactory) -> list[Check]:
    deps = factory.deps
    cases: list[tuple[str, str, str, Callable[[], Awaitable[Any]], float]] = []

    def add(adapter_name: str, name: str, group: str, call: Callable[[], Awaitable[Any]], timeout: float = 12) -> None:
        if missing_key(adapter_name):
            env = KEY_ENVS[adapter_name]
            cases.append((
                name,
                group,
                adapter_name,
                lambda env=env: _skip(f"missing {env}"),
                0.1,
            ))
            return
        cases.append((name, group, adapter_name, call, timeout))

    btc = Instrument("BTCUSDT", AssetClass.CRYPTO)
    eth = Instrument("ETHUSDT", AssetClass.CRYPTO)
    aapl = Instrument("AAPL", AssetClass.EQUITY)
    eurusd = Instrument("EURUSD", AssetClass.FX)
    xau = Instrument("GC=F", AssetClass.COMMODITY)

    add("ccxt_failover", "ccxt_failover.quote.BTCUSDT", "crypto", lambda: deps.ccxt_failover.fetch(DataRequest(kind=DataKind.QUOTE, instrument=btc)))
    add("coingecko", "coingecko.quote.BTCUSDT", "crypto", lambda: deps.coingecko.fetch(DataRequest(kind=DataKind.QUOTE, instrument=btc)))
    add("cryptocompare", "cryptocompare.quote.BTCUSDT", "crypto", lambda: deps.cryptocompare.fetch(DataRequest(kind=DataKind.QUOTE, instrument=btc)))
    add("yfinance", "yfinance.quote.AAPL", "equity", lambda: deps.yfinance.fetch(DataRequest(kind=DataKind.QUOTE, instrument=aapl, extra={"timeout": 6})))
    add("yfinance", "yfinance.news.AAPL", "news", lambda: deps.yfinance.fetch(DataRequest(kind=DataKind.NEWS, instrument=aapl, limit=10, extra={"timeout": 6})))
    add("yfinance", "yfinance.news.BTCUSDT", "news", lambda: deps.yfinance.fetch(DataRequest(kind=DataKind.NEWS, instrument=btc, limit=10, extra={"timeout": 6})))
    add("stooq", "stooq.ohlcv.AAPL", "equity", lambda: deps.stooq.fetch(DataRequest(kind=DataKind.OHLCV, instrument=aapl, limit=30)))
    add("ecb", "ecb.quote.EURUSD", "fx", lambda: deps.ecb.fetch(DataRequest(kind=DataKind.QUOTE, instrument=eurusd)))
    add("exchangerate_host", "exchangerate_host.quote.EURUSD", "fx", lambda: deps.exchangerate_host.fetch(DataRequest(kind=DataKind.QUOTE, instrument=eurusd)))
    add("eia", "eia.quote.GC=F", "commodity", lambda: deps.eia.fetch(DataRequest(kind=DataKind.QUOTE, instrument=xau)))
    add("rss", "rss.crypto.BTC", "news", lambda: deps.rss.fetch(DataRequest(kind=DataKind.NEWS, instrument=btc, limit=10, extra={"feed_group": "crypto", "asset_class": "CRYPTO", "terms": ["BTC", "Bitcoin"]})))
    add("rss", "rss.crypto.ETH", "news", lambda: deps.rss.fetch(DataRequest(kind=DataKind.NEWS, instrument=eth, limit=10, extra={"feed_group": "crypto", "asset_class": "CRYPTO", "terms": ["ETH", "Ethereum", "Ether"]})))
    add("rss", "rss.market.AAPL", "news", lambda: deps.rss.fetch(DataRequest(kind=DataKind.NEWS, instrument=aapl, limit=10, extra={"feed_group": "market", "terms": ["AAPL"]})))
    add("gdelt", "gdelt.news.Bitcoin", "news", lambda: deps.gdelt.fetch(DataRequest(kind=DataKind.NEWS, limit=5, extra={"query": '"Bitcoin"'})), timeout=15)

    checks: list[Check] = []
    for name, group, _adapter_name, call, timeout in cases:
        check, _ = await timed(name, group, call, timeout=timeout)
        if name.startswith("gdelt.") and check.status == "FAIL":
            check.status = "WARN"
            check.reason = f"optional deep source degraded; default path uses RSS/Nasdaq: {check.reason}"
        if name.startswith("yfinance.news.") and check.status == "FAIL":
            check.status = "WARN"
            check.reason = f"optional replaced source degraded; default CN path uses RSS/Nasdaq: {check.reason}"
        checks.append(check)
    return checks


async def _skip(reason: str) -> Any:
    raise RuntimeError(f"SKIP: {reason}")


async def audit_rss_feeds(factory: FunctionFactory) -> list[Check]:
    feeds = list(dict.fromkeys([*factory.deps.rss.market_feeds, *factory.deps.rss.crypto_feeds]))
    checks: list[Check] = []
    async with httpx.AsyncClient(headers={"User-Agent": "showMe-source-audit/1.0"}, follow_redirects=True) as client:
        async def one(url: str) -> Check:
            start = now_ms()
            try:
                response = await client.get(url, timeout=8)
                elapsed = now_ms() - start
                text = response.text
                count = 0
                try:
                    import feedparser
                    count = len(feedparser.parse(text).entries)
                except Exception:
                    pass
                return Check(
                    name=url,
                    group="rss-feed",
                    status="PASS" if response.status_code < 400 and count else "FAIL",
                    elapsed_ms=elapsed,
                    count=count,
                    reason="" if response.status_code < 400 else str(response.status_code),
                    sample=response.headers.get("content-type", "")[:80],
                )
            except Exception as exc:  # noqa: BLE001
                return Check(
                    name=url,
                    group="rss-feed",
                    status="FAIL",
                    elapsed_ms=now_ms() - start,
                    reason=f"{type(exc).__name__}: {exc}",
                )
        checks = await asyncio.gather(*(one(url) for url in feeds))
    return list(checks)


def news_key(item: dict[str, Any]) -> str:
    return str(item.get("url") or item.get("link") or item.get("title") or item)


async def audit_news_relevance(factory: FunctionFactory) -> dict[str, Any]:
    fn = CNFunction(factory.deps)
    symbols = [
        Instrument("BTCUSDT", AssetClass.CRYPTO),
        Instrument("ETHUSDT", AssetClass.CRYPTO),
    ]
    out: dict[str, Any] = {}
    for inst in symbols:
        start = now_ms()
        result = await fn.execute(inst, limit=20, news_timeout=6)
        elapsed = now_ms() - start
        terms = _crypto_specific_terms(inst.symbol)
        rows = [row for row in (result.data or []) if isinstance(row, dict)]
        relevant = [row for row in rows if _news_relevance_score(row, terms) > 0]
        out[inst.symbol] = {
            "elapsed_ms": elapsed,
            "sources": result.sources,
            "terms": terms,
            "count": len(rows),
            "relevant_count": len(relevant),
            "relevance_ratio": round(len(relevant) / max(len(rows), 1), 3),
            "titles": [str(row.get("title") or "")[:180] for row in rows[:8]],
            "keys": [news_key(row) for row in rows],
        }
    btc_keys = set(out["BTCUSDT"]["keys"])
    eth_keys = set(out["ETHUSDT"]["keys"])
    overlap = btc_keys & eth_keys
    out["overlap"] = {
        "count": len(overlap),
        "ratio_vs_smaller_set": round(len(overlap) / max(min(len(btc_keys), len(eth_keys)), 1), 3),
        "items": sorted(overlap)[:10],
    }
    return out


def status_from_reason(check: Check) -> str:
    if check.reason.startswith("RuntimeError: SKIP:"):
        return "SKIP"
    return check.status


def replaced_or_fallback_source(check: Check) -> bool:
    return (
        check.name.startswith("gdelt.")
        or check.name.startswith("ecb.")
        or check.name.startswith("yfinance.news.")
    )


def write_report(checks: list[Check], relevance: dict[str, Any]) -> Path:
    stamp = datetime.now(timezone.utc).isoformat().replace(":", "-").replace(".", "-")
    out_dir = ROOT / "artifacts" / "data-source-audit" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": [asdict(check) for check in checks],
        "news_relevance": relevance,
    }
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    counts: dict[str, int] = {}
    for check in checks:
        counts[status_from_reason(check)] = counts.get(status_from_reason(check), 0) + 1
    slow_primary = [
        c for c in checks
        if c.status == "PASS" and c.elapsed_ms > 2500 and not replaced_or_fallback_source(c)
    ]
    slow_replaced = [
        c for c in checks
        if c.status == "PASS" and c.elapsed_ms > 2500 and replaced_or_fallback_source(c)
    ]
    lines = [
        "# ShowMe Data Source Audit",
        "",
        f"- generated: {payload['generated_at']}",
        f"- pass: {counts.get('PASS', 0)}",
        f"- warn: {counts.get('WARN', 0)}",
        f"- fail: {counts.get('FAIL', 0)}",
        f"- skip_missing_key: {counts.get('SKIP', 0)}",
        f"- slow_primary_over_2500ms: {len(slow_primary)}",
        f"- slow_replaced_or_fallback_over_2500ms: {len(slow_replaced)}",
        "",
        "## Checks",
        "",
        "| group | name | status | ms | count | source | reason |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for check in checks:
        lines.append(
            "| "
            + " | ".join([
                check.group,
                check.name.replace("|", "\\|"),
                status_from_reason(check),
                str(check.elapsed_ms),
                "" if check.count is None else str(check.count),
                (check.source or "").replace("|", "\\|"),
                check.reason.replace("|", "\\|"),
            ])
            + " |"
        )
    lines.extend([
        "",
        "## Crypto News Relevance",
        "",
        f"- BTCUSDT: {relevance['BTCUSDT']['relevant_count']}/{relevance['BTCUSDT']['count']} relevant; sources={', '.join(relevance['BTCUSDT']['sources'])}",
        f"- ETHUSDT: {relevance['ETHUSDT']['relevant_count']}/{relevance['ETHUSDT']['count']} relevant; sources={', '.join(relevance['ETHUSDT']['sources'])}",
        f"- overlap: {relevance['overlap']['count']} shared items; ratio={relevance['overlap']['ratio_vs_smaller_set']}",
        "",
        "### BTCUSDT Titles",
        "",
        *[f"- {title}" for title in relevance["BTCUSDT"]["titles"]],
        "",
        "### ETHUSDT Titles",
        "",
        *[f"- {title}" for title in relevance["ETHUSDT"]["titles"]],
        "",
        f"Raw JSON: {out_dir / 'results.json'}",
    ])
    summary = out_dir / "summary.md"
    summary.write_text("\n".join(lines), encoding="utf-8")
    return summary


async def main() -> None:
    factory = FunctionFactory(ROOT / "engine" / "config" / "data_sources.yaml")
    adapter_checks = await audit_adapter_cases(factory)
    rss_checks = await audit_rss_feeds(factory)
    relevance = await audit_news_relevance(factory)
    summary = write_report([*adapter_checks, *rss_checks], relevance)
    print(summary)


if __name__ == "__main__":
    asyncio.run(main())
