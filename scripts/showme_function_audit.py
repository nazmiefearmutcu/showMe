#!/usr/bin/env python3
"""Contract audit for the ShowMe function catalog.

Outputs the artifact shape requested by ``ShowMe_Execution_Belgesi_Coder``:
``summary.md``, ``function_audit.json``, per-function request/response JSON,
and ``provider_matrix.md`` under ``artifacts/showme-function-audit/<timestamp>``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audit_functions import params_for, primary_assets, request_json


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_STATUSES = {"ok", "empty", "input_error", "provider_unavailable", "calc_error"}
WARN_STATUSES = {"empty", "provider_unavailable"}
FAIL_STATUSES = {"input_error", "calc_error"}
DENY_SENTINELS = (
    "No rows",
    "No ratios",
    "function did not return",
    "undefined",
    "NaN",
    "null table",
    "NONE source",
)
NATIVE_ENTRIES = [
    {"code": "AGENT", "name": "Best Symbol Agent", "category": "agent", "asset_classes": []},
    {"code": "ASK", "name": "Ask ShowMe", "category": "agent", "asset_classes": []},
    {"code": "WATCH", "name": "Watchlist", "category": "portfolio", "asset_classes": []},
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url")
    parser.add_argument("--base", dest="base_url")
    parser.add_argument("--port")
    parser.add_argument("--catalog", default="/api/function-index")
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "showme-function-audit"))
    parser.add_argument("--timeout", type=float, default=18)
    parser.add_argument("--freeze-snapshot", action="store_true")
    args = parser.parse_args()

    base = (args.base_url or f"http://127.0.0.1:{args.port}").rstrip("/")
    if not args.base_url and not args.port:
        parser.error("--base-url/--base or --port is required")

    health_status, health = request_json(f"{base}/api/health", timeout=args.timeout)
    if health_status >= 400 or not isinstance(health, dict) or not health.get("ok"):
        raise SystemExit(f"health failed: {health_status} {health}")

    entries = load_catalog(args.catalog, base, args.timeout)
    entries = merge_native_entries(entries)

    stamp = datetime.now(timezone.utc).isoformat().replace(":", "-").replace(".", "-")
    out_dir = Path(args.out) / stamp
    requests_dir = out_dir / "requests"
    responses_dir = out_dir / "responses"
    screenshots_dir = out_dir / "screenshots"
    for directory in (requests_dir, responses_dir, screenshots_dir):
        directory.mkdir(parents=True, exist_ok=True)

    if args.freeze_snapshot:
        snapshot = ROOT / "tests" / "fixtures" / "function-index.snapshot.json"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rows: list[dict[str, Any]] = []
    for entry in entries:
        code = str(entry.get("code", "")).upper()
        if code in {"AGENT", "ASK", "WATCH"}:
            started = time.perf_counter()
            status_code, body, error = run_native_function(base, code, args.timeout)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            result = validate_native_result(code, status_code, body, error)
            case_id = f"{code}-GLOBAL"
            request_path = requests_dir / f"{case_id}.json"
            response_path = responses_dir / f"{case_id}.json"
            request_path.write_text(
                json.dumps(native_request_payload(code), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            response_path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            rows.append({
                "code": code,
                "name": entry.get("name", ""),
                "category": entry.get("category", ""),
                "asset": "GLOBAL",
                "input": native_request_payload(code),
                "httpStatus": status_code,
                "status": result["contractStatus"],
                "outcome": result["outcome"],
                "reason": result["reason"],
                "payloadKeys": result["payloadKeys"],
                "rowCount": result["rowCount"],
                "seriesCount": result["seriesCount"],
                "cardCount": result["cardCount"],
                "sourceCount": result["sourceCount"],
                "warnings": result["warnings"],
                "requestPath": str(request_path),
                "responsePath": str(response_path),
                "screenshotPath": None,
                "networkErrors": [],
                "consoleErrors": [],
                "elapsedMs": elapsed_ms,
            })
            print(f"{result['outcome']:<4} {code:<10} {'GLOBAL':<9} {elapsed_ms:>6}ms {result['reason']}")
            continue

        for asset in primary_assets(entry):
            params = params_for(entry, asset)
            started = time.perf_counter()
            status_code = 0
            body: Any = None
            error: str | None = None
            try:
                status_code, body = request_json(
                    f"{base}/api/fn/{urllib.parse.quote(code)}",
                    params,
                    timeout=args.timeout,
                )
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            result = validate_function_result(entry, asset or "GLOBAL", status_code, body, error)

            case_id = f"{code}-{asset or 'GLOBAL'}"
            request_path = requests_dir / f"{case_id}.json"
            response_path = responses_dir / f"{case_id}.json"
            request_path.write_text(json.dumps(params, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            response_path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

            rows.append({
                "code": code,
                "name": entry.get("name", ""),
                "category": entry.get("category", ""),
                "asset": asset or "GLOBAL",
                "input": params,
                "httpStatus": status_code,
                "status": result["contractStatus"],
                "outcome": result["outcome"],
                "reason": result["reason"],
                "payloadKeys": result["payloadKeys"],
                "rowCount": result["rowCount"],
                "seriesCount": result["seriesCount"],
                "cardCount": result["cardCount"],
                "sourceCount": result["sourceCount"],
                "warnings": result["warnings"],
                "requestPath": str(request_path),
                "responsePath": str(response_path),
                "screenshotPath": None,
                "networkErrors": [],
                "consoleErrors": [],
                "elapsedMs": elapsed_ms,
            })
            print(f"{result['outcome']:<4} {code:<10} {asset or 'GLOBAL':<9} {elapsed_ms:>6}ms {result['reason']}")

    write_artifacts(out_dir, rows, entries, base)
    counts = Counter(row["outcome"] for row in rows)
    print(f"summary: {out_dir / 'summary.md'}")
    return 1 if counts["FAIL"] else 0


def load_catalog(catalog: str, base: str, timeout: float) -> list[dict[str, Any]]:
    path = Path(catalog)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise SystemExit(f"catalog file is not a list: {path}")
        return data
    catalog_url = catalog if catalog.startswith("http") else f"{base}{catalog}"
    catalog_status, entries = request_json(catalog_url, timeout=timeout)
    if catalog_status >= 400 or not isinstance(entries, list):
        raise SystemExit(f"function-index failed: {catalog_status} {entries}")
    return entries


def merge_native_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {str(entry.get("code", "")).upper() for entry in entries}
    merged = list(entries)
    for entry in NATIVE_ENTRIES:
        if entry["code"] not in seen:
            merged.append(entry)
            seen.add(entry["code"])
    return sorted(merged, key=lambda row: (str(row.get("category", "")), str(row.get("code", ""))))


def validate_function_result(
    entry: dict[str, Any],
    asset: str,
    http_status: int,
    body: Any,
    error: str | None,
) -> dict[str, Any]:
    if error:
        return fail("request_error", error)
    if http_status >= 400:
        return fail("http_error", f"http {http_status}: {body}")
    if not isinstance(body, dict):
        return fail("contract_error", "response is not a JSON object")

    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    status = str(body.get("status") or data.get("status") or "").lower()
    reason = str(body.get("reason") or data.get("reason") or "").strip()
    next_action = str(body.get("nextAction") or data.get("nextAction") or "").strip()
    payload = body.get("payload")
    payload_keys = sorted(payload.keys()) if isinstance(payload, dict) else []
    rows = body.get("rows") if isinstance(body.get("rows"), list) else []
    series = body.get("series") if isinstance(body.get("series"), list) else []
    cards = body.get("cards") if isinstance(body.get("cards"), list) else []
    sources = body.get("sourceDetails") if isinstance(body.get("sourceDetails"), list) else body.get("sources") or []
    warnings = body.get("warnings") if isinstance(body.get("warnings"), list) else []

    sentinel = sentinel_hit(body)
    if sentinel:
        return fail(status or "contract_error", f"sentinel text in payload: {sentinel}")
    if status not in ALLOWED_STATUSES:
        return fail(status or "missing_status", "missing or invalid contract status")
    if status == "ok":
        specific = validate_ok_payload(str(entry.get("code", "")).upper(), body, rows, series, cards)
        if specific:
            return fail(status, specific)
        return {
            "outcome": "PASS",
            "contractStatus": status,
            "reason": "ok",
            "payloadKeys": payload_keys,
            "rowCount": len(rows),
            "seriesCount": len(series),
            "cardCount": len(cards),
            "sourceCount": len(sources),
            "warnings": warnings,
        }
    if not reason:
        return fail(status, f"{status} missing reason")
    if not next_action and not data.get("next_actions"):
        return fail(status, f"{status} missing nextAction")
    outcome = "FAIL" if status in FAIL_STATUSES else "WARN"
    if status in WARN_STATUSES:
        outcome = "WARN"
    return {
        "outcome": outcome,
        "contractStatus": status,
        "reason": reason,
        "payloadKeys": payload_keys,
        "rowCount": len(rows),
        "seriesCount": len(series),
        "cardCount": len(cards),
        "sourceCount": len(sources),
        "warnings": warnings,
    }


def run_native_function(
    base: str,
    code: str,
    timeout: float,
) -> tuple[int, Any, str | None]:
    try:
        if code == "AGENT":
            status, body = request_json(
                f"{base}/api/agent/best-symbol",
                native_request_payload(code),
                timeout=timeout,
            )
        elif code == "ASK":
            status, body = request_json(
                f"{base}/api/ask",
                native_request_payload(code),
                timeout=timeout,
            )
        elif code == "WATCH":
            status, body = request_json(f"{base}/api/quote/AAPL", timeout=timeout)
        else:
            return 0, None, f"unknown native function {code}"
        return status, body, None
    except Exception as exc:  # noqa: BLE001
        return 0, None, f"{type(exc).__name__}: {exc}"


def native_request_payload(code: str) -> dict[str, Any]:
    if code == "AGENT":
        return {
            "candidates": [
                {"symbol": "AAPL", "asset_class": "EQUITY"},
                {"symbol": "MSFT", "asset_class": "EQUITY"},
                {"symbol": "BTCUSDT", "asset_class": "CRYPTO"},
            ],
            "execute_functions": False,
        }
    if code == "ASK":
        return {"query": "AAPL için risk, haber ve portföy etkisi nedir?"}
    if code == "WATCH":
        return {"symbol": "AAPL"}
    return {}


def validate_native_result(
    code: str,
    http_status: int,
    body: Any,
    error: str | None,
) -> dict[str, Any]:
    if error:
        return fail("request_error", error)
    if http_status >= 400:
        return fail("http_error", f"http {http_status}: {body}")
    if not isinstance(body, dict):
        return fail("contract_error", "native response is not a JSON object")
    if code == "AGENT":
        ok = bool(body.get("best") or body.get("ranked"))
        keys = sorted(body.keys())
    elif code == "ASK":
        ok = bool(body.get("answer") or body.get("narrative") or body.get("plan"))
        keys = sorted(body.keys())
    elif code == "WATCH":
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        ok = bool(body.get("ok")) and any(data.get(key) is not None for key in ("last", "price", "close", "regularMarketPrice"))
        keys = sorted(data.keys())
    else:
        ok = False
        keys = []
    if not ok:
        reason = ""
        if isinstance(body, dict):
            reason = str(body.get("error") or body.get("detail") or "").strip()
        return warn("provider_unavailable", reason or "native endpoint returned no usable payload")
    return {
        "outcome": "PASS",
        "contractStatus": "ok",
        "reason": "ok",
        "payloadKeys": keys,
        "rowCount": 1,
        "seriesCount": 0,
        "cardCount": 1,
        "sourceCount": 1,
        "warnings": [],
    }


def validate_ok_payload(
    code: str,
    body: dict[str, Any],
    rows: list[Any],
    series: list[Any],
    cards: list[Any],
) -> str | None:
    payload = body.get("payload")
    if code == "FA":
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        ratios = data.get("ratios") if isinstance(data.get("ratios"), dict) else {}
        if not ratios:
            return "FA ok without ratios payload"
    if code == "LOTS" and not rows:
        return "LOTS ok without tax lot rows"
    if not rows and not series and not cards and not meaningful_payload(payload):
        return "ok status without rows, series, cards, or payload"
    sources = body.get("sourceDetails") if isinstance(body.get("sourceDetails"), list) else []
    if not sources:
        return "ok status without source details"
    return None


def meaningful_payload(value: Any) -> bool:
    if isinstance(value, dict):
        return any(meaningful_payload(v) for v in value.values())
    if isinstance(value, list):
        return bool(value)
    return value not in (None, "")


def sentinel_hit(value: Any) -> str | None:
    text = json.dumps(value, ensure_ascii=False, default=str)
    for sentinel in DENY_SENTINELS:
        if sentinel in text:
            return sentinel
    return None


def fail(status: str, reason: str) -> dict[str, Any]:
    return {
        "outcome": "FAIL",
        "contractStatus": status,
        "reason": reason,
        "payloadKeys": [],
        "rowCount": 0,
        "seriesCount": 0,
        "cardCount": 0,
        "sourceCount": 0,
        "warnings": [],
    }


def warn(status: str, reason: str) -> dict[str, Any]:
    return {
        "outcome": "WARN",
        "contractStatus": status,
        "reason": reason,
        "payloadKeys": [],
        "rowCount": 0,
        "seriesCount": 0,
        "cardCount": 0,
        "sourceCount": 0,
        "warnings": [reason] if reason else [],
    }


def write_artifacts(
    out_dir: Path,
    rows: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    base: str,
) -> None:
    counts = Counter(row["outcome"] for row in rows)
    status_counts = Counter(row["status"] for row in rows)
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_category[row["category"]][row["outcome"]] += 1

    (out_dir / "function_audit.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_provider_matrix(out_dir / "provider_matrix.md", rows)

    lines = [
        "# ShowMe Function Contract Audit",
        "",
        f"- base: {base}",
        f"- generated: {datetime.now(timezone.utc).isoformat()}",
        f"- catalog_functions: {len(entries)}",
        f"- total_cases: {len(rows)}",
        f"- pass: {counts['PASS']}",
        f"- warn: {counts['WARN']}",
        f"- fail: {counts['FAIL']}",
        f"- status_counts: {dict(status_counts)}",
        "",
        "## By Category",
        "",
        "| category | pass | warn | fail |",
        "|---|---:|---:|---:|",
    ]
    for category in sorted(by_category):
        bucket = by_category[category]
        lines.append(f"| {category} | {bucket['PASS']} | {bucket['WARN']} | {bucket['FAIL']} |")
    lines.extend(["", "## Red List", "", "| code | asset | status | reason |", "|---|---|---|---|"])
    red = [row for row in rows if row["outcome"] != "PASS"]
    if red:
        lines.extend(
            f"| {row['code']} | {row['asset']} | {row['status']} | {md_escape(row['reason'])} |"
            for row in red
        )
    else:
        lines.append("| - | - | - | - |")
    lines.extend([
        "",
        "## Artifacts",
        "",
        f"- function_audit.json: {out_dir / 'function_audit.json'}",
        f"- provider_matrix.md: {out_dir / 'provider_matrix.md'}",
        f"- requests: {out_dir / 'requests'}",
        f"- responses: {out_dir / 'responses'}",
        f"- screenshots: {out_dir / 'screenshots'}",
        "",
        "Note: screenshots are produced by the Playwright suite; this backend audit never fabricates screenshot paths.",
    ])
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_provider_matrix(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Provider Matrix",
        "",
        "| code | asset | status | sourceCount | provider_unavailable message | cache policy | fallback |",
        "|---|---|---|---:|---|---|---|",
    ]
    for row in rows:
        message = row["reason"] if row["status"] == "provider_unavailable" else ""
        lines.append(
            f"| {row['code']} | {row['asset']} | {row['status']} | {row['sourceCount']} | "
            f"{md_escape(message)} | function-level cache/provider default | explicit status state |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def md_escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    sys.exit(main())
