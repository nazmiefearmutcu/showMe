#!/usr/bin/env python3
"""Run a quality audit against the live ShowMe Python sidecar.

The audit is asset-aware: it does not push BTCUSDT into an equity, bond, FX,
commodity, or standalone derivative function. Each function is called with the
smallest representative input that should exercise its advertised behavior.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEOUT = float(os.environ.get("SHOWME_AUDIT_TIMEOUT_SECONDS", "18"))

SYMBOL_BY_ASSET = {
    "CRYPTO": "BTCUSDT",
    "EQUITY": "AAPL",
    "ETF": "SPY",
    "FX": "EURUSD",
    "COMMODITY": "GC=F",
    "INDEX": "^GSPC",
    "BOND": "US10Y",
}

SYMBOL_FIRST_CODES = {
    "ANR",
    "BETA",
    "CACT",
    "CN",
    "DARK",
    "DCF",
    "DCFS",
    "DDM",
    "DES",
    "DPF",
    "DVD",
    "EE",
    "EVTS",
    "ESG",
    "FA",
    "FORM4",
    "FRD",
    "FTS",
    "FXIP",
    "GEX",
    "GP",
    "HDS",
    "HFS",
    "HP",
    "HVT",
    "IVOL",
    "LITM",
    "MICRO",
    "NALRT",
    "NI",
    "OMON",
    "PIB",
    "RV",
    "SPLC",
    "SOSC",
    "TECH",
    "TRAN",
    "WACC",
    "YAS",
    "BTFW",
    "BTUNE",
    "PORT_WHATIF",
    "TRA",
    "BBGT",
    "EMSX",
    "FXGO",
    "TSOX",
}
SYMBOL_FIRST_CATEGORIES = {"chart", "equity"}
STANDALONE_DERIVATIVES = {"OVME", "OSA"}


def request_json(url: str, payload: dict[str, Any] | None = None, timeout: float = DEFAULT_TIMEOUT) -> tuple[int, Any]:
    data = None
    headers = {"accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8")
            return res.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except Exception:
            body = raw
        return exc.code, body


def entry_uses_symbol(entry: dict[str, Any]) -> bool:
    code = str(entry.get("code", "")).upper()
    category = str(entry.get("category", "")).lower()
    if code in STANDALONE_DERIVATIVES:
        return False
    return code in SYMBOL_FIRST_CODES or category in SYMBOL_FIRST_CATEGORIES


def primary_assets(entry: dict[str, Any]) -> list[str | None]:
    code = str(entry.get("code", "")).upper()
    supported = [str(x).upper() for x in entry.get("asset_classes") or []]
    if code in STANDALONE_DERIVATIVES:
        return [None]
    if code in {"FRD", "FXIP", "FXGO"}:
        return ["FX"]
    if code in {"YAS", "TSOX"}:
        return ["BOND"]
    if code in {"EVTS", "SOSC", "TRAN", "TRA", "EMSX", "BBGT"}:
        return ["EQUITY"]
    if code == "MICRO":
        return ["CRYPTO", "EQUITY"]
    if not entry_uses_symbol(entry):
        return [None]
    if "CRYPTO" in supported and "EQUITY" in supported:
        return ["CRYPTO", "EQUITY"]
    if "EQUITY" in supported:
        return ["EQUITY"]
    if "ETF" in supported:
        return ["ETF"]
    if "CRYPTO" in supported:
        return ["CRYPTO"]
    if "FX" in supported:
        return ["FX"]
    if "COMMODITY" in supported:
        return ["COMMODITY"]
    if "INDEX" in supported:
        return ["INDEX"]
    if "BOND" in supported:
        return ["BOND"]
    if "DERIVATIVE" in supported:
        return ["EQUITY"]
    category = str(entry.get("category", "")).lower()
    if category == "news":
        return ["CRYPTO", "EQUITY"]
    if category == "fx":
        return ["FX"]
    if category == "commodity":
        return ["COMMODITY"]
    if category == "bond":
        return ["BOND"]
    return ["CRYPTO"]


def params_for(entry: dict[str, Any], asset: str | None) -> dict[str, Any]:
    code = str(entry.get("code", "")).upper()
    category = str(entry.get("category", "")).lower()
    params: dict[str, Any] = {
        "limit": 10,
        "days": 45,
        "range": "1M",
        "interval": "1d",
        "live": True,
        "timeout": 4,
        "quote_timeout": 4,
        "news_timeout": 4,
        "yfinance_timeout": 4,
        "max_positions": 10,
    }
    if asset:
        symbol = SYMBOL_BY_ASSET.get(asset, "AAPL")
        params.update({"symbol": symbol, "asset_class": asset, "topic": symbol})
    if asset == "CRYPTO":
        params.update({
            "query": "bitcoin cryptocurrency",
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "universe": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
            "targets": {"BTCUSDT": 0.6, "ETHUSDT": 0.4},
            "exchange": "BINANCE",
        })
    elif asset == "EQUITY" or category == "equity":
        params.update({
            "query": "Apple stock",
            "symbols": ["AAPL", "MSFT", "GOOGL"],
            "universe": ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA"],
            "targets": {"AAPL": 0.5, "MSFT": 0.3, "GOOGL": 0.2},
            "exchange": "NASDAQ",
        })
    elif asset == "FX":
        params.update({
            "query": "euro dollar foreign exchange",
            "symbols": ["EURUSD", "GBPUSD=X", "USDJPY=X"],
            "exchange": "FX",
        })
    elif asset == "COMMODITY":
        params.update({
            "query": "gold futures commodity",
            "symbols": ["GC=F", "SI=F", "CL=F"],
            "exchange": "COMEX",
        })
    elif asset == "BOND":
        params.update({"query": "US treasury", "country": "US"})
    else:
        params.update({"query": "market news", "symbols": ["AAPL", "BTCUSDT"]})

    if code == "OVME":
        params = {
            "spot": 100,
            "strike": 105,
            "years_to_expiry": 0.25,
            "vol": 0.28,
            "rate": 0.045,
            "type": "CALL",
        }
    elif code == "OSA":
        params = {
            "spot": 100,
            "rate": 0.045,
            "legs": [
                {"qty": 1, "strike": 100, "type": "CALL", "expiry": 0.25, "vol": 0.25},
                {"qty": -1, "strike": 110, "type": "CALL", "expiry": 0.25, "vol": 0.25},
            ],
        }
    elif code == "BQL":
        sym = params.get("symbol", "AAPL")
        params["query"] = f"get(close, volume) for(['{sym}']) with(period='1mo', interval='1d') by(date)"
    elif code in {"EQS", "SECF", "SRCH", "FSRC", "CSRC"}:
        if code == "SRCH":
            params["query"] = "yield >= 0"
        elif code == "FSRC":
            params["query"] = "expenseRatio < 0.05"
        elif code == "CSRC":
            params["query"] = 'sector = "Energy"'
        else:
            params["query"] = "marketCap > 0"
    elif code == "FTS":
        params["form_type"] = "8-K"
    elif code == "FLDS":
        params["query"] = "price"
    elif code == "ISIN":
        params["query"] = params.get("symbol", "AAPL")
    elif code in {"NSE", "NI", "READ", "TOP", "POLY"}:
        params["limit"] = 10
    elif code == "TSAR":
        params.update({"query": "revenue", "limit": 10})
    elif code == "TRQA":
        params["questions"] = ["What changed?", "What are the risks?"]
    elif code == "ICX":
        params["index"] = "SPX"
    elif code == "SAT":
        today = datetime.now(timezone.utc).date()
        params.update({
            "bbox": "-122.55,37.70,-122.30,37.85",
            "date_from": (today - timedelta(days=7)).isoformat(),
            "date_to": today.isoformat(),
        })
    elif code in {"CDE", "ALRT", "LOTS"}:
        params["action"] = "list"
    elif code in {"MEET", "PEOP"}:
        params["query"] = "Satoshi Nakamoto" if asset == "CRYPTO" else "Apple"
    elif code in {"BTFW", "BMTX", "MLSIG"}:
        params.update({"strategy": "buy_and_hold", "days": 90})
    elif code == "BTUNE":
        params.update({"strategy": "sma_crossover", "days": 90})
    elif code == "MGN":
        params["refresh_prices"] = False
    elif code == "DCFS":
        params.update({"wacc_range": [0.07, 0.09, 0.11], "g_range": [0.02, 0.03]})
    elif code in {"DCF", "DDM"}:
        params.update({
            "fcfe": 1_000_000_000,
            "shares_outstanding": 1_000_000_000,
            "dividend_ttm": 1.0,
            "growth_rate": 0.03,
            "required_return": 0.08,
            "wacc": 0.09,
        })
    elif code == "WACC":
        params.update({"erp": 0.05, "beta_timeout": 2})
    elif code == "TAUC":
        params.update({"live": True, "horizon_days": 7, "limit": 6, "auction_timeout": 5})
    elif code == "GREEKS":
        params["positions"] = [{
            "symbol": params.get("symbol", "AAPL"),
            "option_type": "CALL",
            "qty": 1,
            "spot": 100,
            "strike": 105,
            "expiry": 0.25,
            "vol": 0.35,
            "rate": 0.04,
        }]
    elif code in {"EMSX", "BBGT", "TSOX", "FXGO"}:
        params.update({"quantity": 1.0, "price": 100.0, "side": "BUY", "submit": True})
    return params


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, bytes)):
        return not value
    if isinstance(value, list):
        return len(value) == 0
    if isinstance(value, dict):
        if not value:
            return True
        if isinstance(value.get("rows"), list) and value.get("status"):
            return value.get("status") in {"provider_unavailable", "unsupported_asset", "empty_portfolio"}
        return all(is_empty(v) for v in value.values())
    return False


def shape(value: Any) -> str:
    if isinstance(value, list):
        return f"array({len(value)})"
    if isinstance(value, dict):
        return "object(" + ",".join(list(value)[:8]) + ")"
    return type(value).__name__


def classify(entry: dict[str, Any], status_code: int, body: Any, elapsed_ms: int, error: str | None) -> tuple[str, str]:
    if error:
        return "FAIL", error
    if status_code >= 400:
        return "FAIL", f"http {status_code}: {body}"
    if not isinstance(body, dict):
        return "FAIL", "non-object payload"
    data = body.get("data")
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    sources = [str(x) for x in body.get("sources") or []]
    warnings = [str(x) for x in body.get("warnings") or []]
    provider_errors = [str(x) for x in metadata.get("provider_errors") or []]
    data_status = str(data.get("status", "")).lower() if isinstance(data, dict) else ""
    if data_status == "unsupported_asset":
        return "FAIL", data.get("reason") or "unsupported asset returned for selected audit asset"
    if metadata.get("exception_type") or metadata.get("fallback") or data_status in {"provider_unavailable", "empty_portfolio", "not_configured"}:
        reason = provider_errors[0] if provider_errors else (data.get("reason") if isinstance(data, dict) else data_status)
        return "WARN", str(reason or "provider unavailable")
    synthetic = [s for s in sources if any(x in s.lower() for x in ("template", "sample", "synthetic", "continuity"))]
    if synthetic or metadata.get("synthetic"):
        return "WARN", "synthetic source: " + ", ".join(synthetic[:4])
    if warnings:
        return "WARN", " | ".join(warnings[:4])
    if is_empty(data):
        return "WARN", "empty data"
    if elapsed_ms > 8_000:
        return "WARN", f"slow: {elapsed_ms}ms"
    return "PASS", f"{elapsed_ms}ms"


def run_native_checks(base: str, timeout: float) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = [
        {
            "code": "AGENT",
            "name": "Best Symbol Agent",
            "category": "native",
            "asset": "GLOBAL",
            "url": f"{base}/api/agent/best-symbol",
            "payload": {
                "candidates": [
                    {"symbol": "BTCUSDT", "asset_class": "CRYPTO"},
                    {"symbol": "AAPL", "asset_class": "EQUITY"},
                ],
                "execute_functions": False,
            },
            "validator": lambda body: isinstance(body, dict) and bool(body.get("best")),
        },
        {
            "code": "ASK",
            "name": "Ask Agent",
            "category": "native",
            "asset": "GLOBAL",
            "url": f"{base}/api/ask",
            "payload": {"query": "Compare BTCUSDT and AAPL using CN and GP."},
            "validator": lambda body: isinstance(body, dict) and bool(body.get("narrative") or body.get("answer") or body.get("markdown") or body.get("text")),
        },
        {
            "code": "WATCH",
            "name": "Watchlist Quote",
            "category": "native",
            "asset": "CRYPTO",
            "url": f"{base}/api/quote/BTCUSDT",
            "payload": None,
            "validator": _valid_quote_response,
        },
        {
            "code": "WATCH",
            "name": "Watchlist Quote",
            "category": "native",
            "asset": "EQUITY",
            "url": f"{base}/api/quote/AAPL",
            "payload": None,
            "validator": _valid_quote_response,
        },
    ]
    rows: list[dict[str, Any]] = []
    for check in checks:
        started = time.perf_counter()
        error = None
        body: Any = None
        status_code = 0
        try:
            status_code, body = request_json(check["url"], check["payload"], timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if error:
            status, reason = "FAIL", error
        elif status_code >= 400:
            status, reason = "FAIL", f"http {status_code}: {body}"
        elif not check["validator"](body):
            status, reason = "WARN", "native endpoint returned no usable payload"
        elif elapsed_ms > 8_000:
            status, reason = "WARN", f"slow: {elapsed_ms}ms"
        else:
            status, reason = "PASS", f"{elapsed_ms}ms"
        rows.append({
            "code": check["code"],
            "name": check["name"],
            "category": check["category"],
            "asset": check["asset"],
            "status": status,
            "reason": reason,
            "elapsed_ms": elapsed_ms,
            "shape": shape(body),
            "sources": ["native_sidecar"],
            "params": check["payload"] or {},
        })
        print(f"{status:4} {check['code']:<10} {check['asset']:<9} {elapsed_ms:>6}ms {reason}")
    return rows


def _valid_quote_response(body: Any) -> bool:
    if not isinstance(body, dict) or not body.get("ok"):
        return False
    data = body.get("data")
    if not isinstance(data, dict):
        return False
    return any(data.get(key) is not None for key in ("last", "price", "close", "regularMarketPrice"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url")
    parser.add_argument("--port")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()
    base = (args.base_url or f"http://127.0.0.1:{args.port}").rstrip("/")
    if not args.base_url and not args.port:
        parser.error("--port or --base-url is required")

    health_status, health = request_json(f"{base}/api/health", timeout=args.timeout)
    if health_status >= 400 or not isinstance(health, dict) or not health.get("ok"):
        raise SystemExit(f"health failed: {health_status} {health}")
    index_status, entries = request_json(f"{base}/api/function-index", timeout=args.timeout)
    if index_status >= 400 or not isinstance(entries, list):
        raise SystemExit(f"function-index failed: {index_status} {entries}")

    stamp = datetime.now(timezone.utc).isoformat().replace(":", "-").replace(".", "-")
    out_dir = ROOT / "artifacts" / "function-audit-python" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "results.jsonl"
    summary_path = out_dir / "summary.md"

    rows: list[dict[str, Any]] = []
    print(f"python audit start: {len(entries)} functions, base={base}")
    with jsonl_path.open("w", encoding="utf-8") as fp:
        for entry in entries:
            assets = primary_assets(entry)
            for asset in assets:
                params = params_for(entry, asset)
                started = time.perf_counter()
                error = None
                status_code = 0
                body: Any = None
                try:
                    status_code, body = request_json(
                        f"{base}/api/fn/{urllib.parse.quote(str(entry['code']).upper())}",
                        params,
                        timeout=args.timeout,
                    )
                except Exception as exc:  # noqa: BLE001
                    error = f"{type(exc).__name__}: {exc}"
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                status, reason = classify(entry, status_code, body, elapsed_ms, error)
                row = {
                    "code": str(entry.get("code", "")).upper(),
                    "name": entry.get("name", ""),
                    "category": entry.get("category", ""),
                    "asset": asset or "GLOBAL",
                    "status": status,
                    "reason": reason,
                    "elapsed_ms": elapsed_ms,
                    "shape": shape(body.get("data") if isinstance(body, dict) else body),
                    "sources": body.get("sources", []) if isinstance(body, dict) else [],
                    "params": params,
                }
                rows.append(row)
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"{status:4} {row['code']:<10} {row['asset']:<9} {elapsed_ms:>6}ms {reason}")
        native_rows = run_native_checks(base, args.timeout)
        for row in native_rows:
            rows.append(row)
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")

    counts = Counter(row["status"] for row in rows)
    logical_functions = len({str(entry.get("code", "")).upper() for entry in entries}) + 3
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_category[row["category"]][row["status"]] += 1
    lines = [
        "# ShowMe Python Function Quality Audit",
        "",
        f"- base: {base}",
        f"- generated: {datetime.now(timezone.utc).isoformat()}",
        f"- backend_functions: {len(entries)}",
        "- native_functions: 3",
        f"- logical_functions: {logical_functions}",
        f"- total_cases: {len(rows)}",
        f"- pass: {counts['PASS']}",
        f"- warn: {counts['WARN']}",
        f"- fail: {counts['FAIL']}",
        "",
        "## By Category",
        "",
        "| category | pass | warn | fail |",
        "|---|---:|---:|---:|",
    ]
    for category in sorted(by_category):
        bucket = by_category[category]
        lines.append(f"| {category} | {bucket['PASS']} | {bucket['WARN']} | {bucket['FAIL']} |")
    lines.extend([
        "",
        "## Failures",
        "",
        "| code | asset | category | reason | ms |",
        "|---|---|---|---|---:|",
    ])
    failures = []
    for r in rows:
        if r["status"] == "FAIL":
            reason = str(r["reason"]).replace('|', '\\|')
            failures.append(f"| {r['code']} | {r['asset']} | {r['category']} | {reason} | {r['elapsed_ms']} |")
    lines.extend(failures)
    lines.extend([
        "",
        "## Warnings",
        "",
        "| code | asset | category | reason | ms |",
        "|---|---|---|---|---:|",
    ])
    warnings_list = []
    for r in rows:
        if r["status"] == "WARN":
            reason = str(r["reason"]).replace('|', '\\|')
            warnings_list.append(f"| {r['code']} | {r['asset']} | {r['category']} | {reason} | {r['elapsed_ms']} |")
    lines.extend(warnings_list)
    lines.extend(["", f"Raw JSONL: {jsonl_path}"])
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"python audit summary: PASS={counts['PASS']} WARN={counts['WARN']} FAIL={counts['FAIL']}")
    print(f"summary: {summary_path}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
