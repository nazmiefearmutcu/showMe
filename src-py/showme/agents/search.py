"""Search Agent — pulls structured data based on the planner's intent.

For scan intents it calls the Scanner Agent. For function intents it
runs the requested ShowMe function via FunctionRegistry. Lookup intents
land on DES. Everything else returns an empty payload that the
summarizer can still narrate.
"""
from __future__ import annotations

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


async def _function(plan: Plan, deps: Any, *, code: str,
                    instrument_symbol: str | None = None) -> dict[str, Any]:
    """Execute any ShowMe function by code, optionally with an instrument."""
    try:
        from src.core.base_function import FunctionRegistry
        from src.core.instrument import AssetClass, Instrument
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
    except Exception:
        payload = {"data": getattr(res, "data", None)}
    payload = _jsonify(payload)
    return {
        "kind": "function",
        "code": code,
        "data": payload,
        "warnings": list(getattr(res, "warnings", []) or []),
    }


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
        except Exception:
            return str(value)
    # numpy scalar
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _jsonify(item())
        except Exception:
            pass
    # datetime-like
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            pass
    return str(value)
