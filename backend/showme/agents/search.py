"""Search Agent — pulls structured data based on the planner's intent.

For scan intents it calls the Scanner Agent. For function intents it
runs the requested ShowMe function via FunctionRegistry. Lookup intents
land on DES. Everything else returns an empty payload that the
summarizer can still narrate.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .planner import Plan
from ..scanner import ScanRequest, run_scan

LOG = logging.getLogger("showme.agents.search")


async def search(plan: Plan, deps: Any) -> dict[str, Any]:
    """Returns a `{kind, data, warnings}` envelope for the summarizer."""
    if plan.intent == "scan":
        return await _scan(plan, deps)
    if plan.intent == "portfolio_overview":
        return await _function(plan, deps, code="PORT")
    if plan.intent == "function":
        code = plan.args.get("code", "PORT")
        sym = (plan.args.get("symbols") or [None])[0]
        return await _function(plan, deps, code=code, instrument_symbol=sym)
    if plan.intent == "lookup":
        sym = (plan.args.get("symbols") or [None])[0]
        return await _function(plan, deps, code="DES",
                                instrument_symbol=sym)
    if plan.intent == "compare":
        symbols = plan.args.get("symbols") or []
        return {"kind": "compare", "symbols": symbols, "warnings": []}
    if plan.intent == "news":
        return await _function(plan, deps, code="TOP")
    return {"kind": "noop", "warnings": [f"unhandled intent: {plan.intent}"]}


async def _scan(plan: Plan, deps: Any) -> dict[str, Any]:
    args = plan.args or {}
    if args.get("quick") or args.get("fast"):
        return await _quick_scan(plan, deps)
    req = ScanRequest(
        intent=plan.action,
        asset_class=args.get("asset_class"),
        top_n=int(args.get("top_n", 12)),
        phases=str(args.get("phases", "A,B,C,D")),
        fine_top_k=int(args.get("fine_top_k") or 6),
    )
    result = await run_scan(req, deps)
    direction = (args.get("direction") or "").upper() or None
    rows = list(result.rows)
    if direction:
        rows = [r for r in rows if r.get("direction") == direction]
    return {
        "kind": "scan",
        "data": {
            "intent": result.intent,
            "universe_key": result.universe_key,
            "asset_class": result.asset_class,
            "timeframes": result.timeframes,
            "rows": rows,
            "phases": [{
                "name": p.name, "elapsed_ms": p.elapsed_ms,
                "output": p.output,
            } for p in result.phases],
            "warnings": result.warnings,
            "elapsed_ms": result.elapsed_ms,
        },
        "warnings": result.warnings,
    }


async def _quick_scan(plan: Plan, deps: Any) -> dict[str, Any]:
    """Bounded live scan for the ASK briefing fan-out leg.

    HNT-14: this used to return synthetic LONG/SHORT rows keyed off the
    symbol list's index — fabricated directions and confidences with no
    relation to market data. It now runs the REAL scanner under a hard
    8s timeout; on timeout/error the leg degrades to an honest
    ``provider_unavailable`` envelope with zero rows instead of invented
    signals.
    """
    args = plan.args or {}
    req = ScanRequest(
        intent=plan.action,
        asset_class=args.get("asset_class"),
        top_n=int(args.get("top_n", 8)),
        phases=str(args.get("phases", "A")),
        fine_top_k=int(args.get("fine_top_k") or 4),
    )
    try:
        result = await asyncio.wait_for(run_scan(req, deps), timeout=8.0)
    except asyncio.TimeoutError:
        return _quick_scan_unavailable(plan, "scan timed out after 8.0s")
    except Exception as exc:  # noqa: BLE001
        LOG.warning("briefing quick scan failed: %r", exc)
        return _quick_scan_unavailable(plan, f"scan failed: {exc}")
    direction = (args.get("direction") or "").upper() or None
    rows = list(result.rows)
    if direction:
        rows = [r for r in rows if r.get("direction") == direction]
    return {
        "kind": "scan",
        "data": {
            "intent": result.intent,
            "universe_key": result.universe_key,
            "asset_class": result.asset_class,
            "timeframes": result.timeframes,
            "rows": rows,
            "phases": [{
                "name": p.name, "elapsed_ms": p.elapsed_ms,
                "output": p.output,
            } for p in result.phases],
            "warnings": result.warnings,
            "elapsed_ms": result.elapsed_ms,
            "mode": "live_quick_scan",
            "sources": ["showme_scanner"],
        },
        "warnings": result.warnings,
        "evidence": [{
            "code": "SCAN",
            "sources": ["showme_scanner"],
            "status": "live_quick_scan",
            "rows": len(rows),
            "top": [row.get("symbol") for row in rows[:5]],
            "elapsed_ms": result.elapsed_ms,
            "reason": "ASK briefing runs the live scanner under a hard 8s bound.",
        }],
    }


def _quick_scan_unavailable(plan: Plan, reason: str) -> dict[str, Any]:
    """Honest degradation envelope for the briefing scan leg (no rows)."""
    warning = f"scan provider unavailable: {reason}"
    return {
        "kind": "scan",
        "data": {
            "intent": plan.action,
            "universe_key": None,
            "asset_class": (plan.args or {}).get("asset_class"),
            "timeframes": [],
            "rows": [],
            "phases": [{
                "name": "fast_briefing_scan",
                "elapsed_ms": 0.0,
                "output": {
                    "mode": "provider_unavailable",
                    "n_evaluated": 0,
                    "n_with_signal": 0,
                },
            }],
            "warnings": [warning],
            "elapsed_ms": 0.0,
            "mode": "provider_unavailable",
            "sources": [],
        },
        "warnings": [warning],
        "evidence": [{
            "code": "SCAN",
            "sources": [],
            "status": "provider_unavailable",
            "rows": 0,
            "top": [],
            "elapsed_ms": 0.0,
            "reason": warning,
        }],
    }


async def _function(plan: Plan, deps: Any, *, code: str,
                    instrument_symbol: str | None = None) -> dict[str, Any]:
    """Execute any ShowMe function by code, optionally with an instrument."""
    try:
        from showme.engine.core.base_function import FunctionRegistry
        from showme.engine.core.instrument import AssetClass, Instrument
    except Exception as exc:  # noqa: BLE001
        return {"kind": "function", "warnings": [f"showme-import: {exc}"]}
    cls = FunctionRegistry.get(code.upper())
    if cls is None:
        return {"kind": "function", "warnings": [f"unknown code {code}"]}
    instrument = None
    if instrument_symbol:
        ac_hint = (plan.args.get("asset_class") or "EQUITY").upper()
        ac = getattr(AssetClass, ac_hint, AssetClass.EQUITY)
        instrument = Instrument(symbol=instrument_symbol.upper(), asset_class=ac)
    fn = cls(deps=deps)
    try:
        res = await fn.execute_timed(instrument=instrument)
    except TypeError as exc:
        return {"kind": "function", "code": code,
                "warnings": [f"argument error: {exc}"]}
    except Exception as exc:  # noqa: BLE001
        LOG.exception("function execute failed")
        return {"kind": "function", "code": code, "warnings": [str(exc)]}
    try:
        payload = res.to_dict()
    except Exception:  # noqa: BLE001
        # QA-fix: surface the conversion failure so silent fallback to a
        # data-only dict is visible in the rotating log.
        LOG.exception("function %s result.to_dict() failed", code)
        payload = {"data": getattr(res, "data", None)}
    payload = _jsonify(payload)
    evidence = _function_evidence(code, payload)
    return {
        "kind": "function",
        "code": code,
        "data": payload,
        "warnings": list(getattr(res, "warnings", []) or []),
        "evidence": evidence,
    }


def _function_evidence(code: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = _extract_rows(data)
    top = [_row_label(row) for row in rows[:5]]
    if not rows and isinstance(data, dict):
        top = [str(k) for k in list(data.keys())[:5]]
    return [{
        "code": code.upper(),
        "sources": list(payload.get("sources") or []),
        "status": payload.get("status") or (data.get("status") if isinstance(data, dict) else None) or "ok",
        "rows": len(rows),
        "top": [item for item in top if item],
        "elapsed_ms": payload.get("elapsed_ms"),
        "reason": payload.get("reason") or (data.get("reason") if isinstance(data, dict) else None),
    }]


def _extract_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("rows", "items", "news", "articles", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            if isinstance(value, dict):
                nested = _extract_rows(value)
                if nested:
                    return nested
    return []


def _row_label(row: dict[str, Any]) -> str:
    for key in ("symbol", "title", "headline", "name", "event", "code"):
        value = row.get(key)
        if value:
            return str(value)
    return ", ".join(f"{k}={v}" for k, v in list(row.items())[:2])


def _jsonify(value: Any) -> Any:
    """Recursively coerce pandas / numpy / datetime to JSON-safe primitives.

    Keeps strings, ints, floats, bools, and None untouched. Lists and dicts
    walk recursively. Anything else gets `str(value)` as a last resort so the
    response is always serializable — failures here would surface as 500s
    out of the FastAPI response model.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        # JSON has no NaN/Inf; clamp to None.
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    # pandas Series / DataFrame
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            try:
                converted = to_dict(orient="records")  # DataFrame
            except TypeError:
                converted = to_dict()  # Series, plain mapping
            return _jsonify(converted)
        except Exception:  # noqa: BLE001
            # QA-fix: structured-conversion failure observable at debug
            # level. Falling back to str() keeps the response serializable.
            LOG.debug("_jsonify pandas conversion failed for %r", type(value), exc_info=True)
            return str(value)
    # numpy scalar
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _jsonify(item())
        except Exception:  # noqa: BLE001
            LOG.debug("_jsonify numpy item() failed for %r", type(value), exc_info=True)
    # datetime-like
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            pass
    return str(value)
