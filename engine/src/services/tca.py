"""Trade Cost Analysis — post-trade fill quality metrics.

Compute per-order:
- Implementation shortfall (IS) = arrival_px → avg_fill_px (signed by side).
- Slippage vs arrival, slippage vs VWAP, slippage vs close.
- Market impact = avg_fill - arrival (size-normalized in bp/share or notional).
- Opportunity cost = (close - arrival) × unfilled_qty.
- Realized spread = round-trip vs mid-point (where data permits).

Inputs: order_history rows (must contain `metadata.fills[]` or
`metadata.arrival_price` etc.). Per-order metadata fields used (best-effort,
all optional with sensible defaults):
    arrival_price (float)
    avg_fill (float)            # if fills missing
    fills (list[{px, qty, ts}]) # preferred
    vwap (float)                # session VWAP at order completion
    close (float)               # close on fill day
    benchmark (str)             # "arrival" (default) | "vwap" | "close"
"""

from __future__ import annotations

import json
import math
from typing import Any

from src.services import order_history


def _safe(d: dict, key: str, default=None):
    v = d.get(key)
    return v if v is not None else default


def _avg_fill(metadata: dict[str, Any], fallback: float | None) -> tuple[float | None, float]:
    fills = metadata.get("fills") or []
    if fills:
        notional = 0.0
        qty = 0.0
        for f in fills:
            try:
                p = float(f.get("px") or f.get("price") or 0)
                q = float(f.get("qty") or f.get("quantity") or 0)
            except Exception:
                continue
            notional += p * q
            qty += q
        if qty > 0:
            return notional / qty, qty
    av = metadata.get("avg_fill") or fallback
    return (float(av) if av is not None else None,
            float(metadata.get("filled_qty") or 0))


def _bps(numerator: float, base: float) -> float:
    if base in (0, None):
        return 0.0
    return (numerator / base) * 1e4


def analyze_order(order: dict[str, Any]) -> dict[str, Any]:
    """Return a TCA dict for a single order_history row (or order-like dict)."""
    md = order.get("metadata") or {}
    if isinstance(md, str):
        try:
            md = json.loads(md)
        except Exception:
            md = {}
    side = (order.get("side") or "BUY").upper()
    sign = +1 if side in ("BUY", "LONG") else -1
    qty = float(order.get("quantity") or 0)
    px_book = float(order.get("price") or 0) or None
    arrival = float(_safe(md, "arrival_price", px_book) or 0) or None
    avg_fill, filled_qty = _avg_fill(md, fallback=px_book)
    vwap = _safe(md, "vwap")
    close = _safe(md, "close")
    benchmark = (_safe(md, "benchmark", "arrival") or "arrival").lower()
    bench_px = arrival if benchmark == "arrival" else (
        vwap if benchmark == "vwap" else close
    )
    out: dict[str, Any] = {
        "id": order.get("id"), "order_id": order.get("order_id"),
        "broker": order.get("broker"), "symbol": order.get("symbol"),
        "side": side, "quantity": qty, "filled_qty": filled_qty,
        "arrival_price": arrival, "avg_fill": avg_fill,
        "vwap": vwap, "close": close, "benchmark": benchmark,
    }
    if avg_fill is None or arrival is None:
        out["warning"] = "missing prices"
        return out
    is_per_share = sign * (avg_fill - arrival)
    is_notional = is_per_share * (filled_qty or qty)
    out["implementation_shortfall_per_share"] = is_per_share
    out["implementation_shortfall_notional"] = is_notional
    out["implementation_shortfall_bps"] = _bps(is_per_share, arrival)
    if vwap is not None:
        out["slippage_vs_vwap_per_share"] = sign * (avg_fill - vwap)
        out["slippage_vs_vwap_bps"] = _bps(sign * (avg_fill - vwap), vwap)
    if close is not None:
        out["slippage_vs_close_per_share"] = sign * (avg_fill - close)
        out["slippage_vs_close_bps"] = _bps(sign * (avg_fill - close), close)
    # Opportunity cost on unfilled qty (vs close).
    unfilled = max(qty - (filled_qty or 0), 0)
    if unfilled and close is not None and arrival:
        out["opportunity_cost_notional"] = sign * (close - arrival) * unfilled
        out["unfilled_qty"] = unfilled
    # Side-aware verdict
    if benchmark == "arrival":
        out["score"] = "BETTER" if is_per_share < 0 else (
            "EVEN" if abs(is_per_share) < 1e-9 else "WORSE")
    return out


def analyze_orders(
    *, broker: str | None = None, symbol: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    rows = order_history.list_orders(broker=broker, symbol=symbol, limit=limit)
    analyses = [analyze_order(o) for o in rows]
    # Aggregate metrics on filled orders only.
    filled = [a for a in analyses if a.get("avg_fill") is not None
              and a.get("arrival_price") is not None]
    if not filled:
        return {"orders": analyses, "summary": {}, "n": 0}
    n = len(filled)
    is_per_share = [a["implementation_shortfall_per_share"] for a in filled]
    is_bps = [a.get("implementation_shortfall_bps", 0) for a in filled]
    is_notional = [a.get("implementation_shortfall_notional", 0) for a in filled]
    by_symbol: dict[str, dict[str, Any]] = {}
    for a in filled:
        s = a["symbol"]
        slot = by_symbol.setdefault(s, {"symbol": s, "n": 0,
                                        "total_is": 0.0, "avg_is_bps": 0.0})
        slot["n"] += 1
        slot["total_is"] += a.get("implementation_shortfall_notional", 0)
        slot["avg_is_bps"] += a.get("implementation_shortfall_bps", 0)
    for slot in by_symbol.values():
        slot["avg_is_bps"] /= max(slot["n"], 1)
    return {
        "orders": analyses, "n": n,
        "summary": {
            "n_filled": n,
            "mean_is_bps": sum(is_bps) / n,
            "median_is_bps": sorted(is_bps)[n // 2],
            "stdev_is_bps": math.sqrt(sum((x - sum(is_bps)/n) ** 2 for x in is_bps) / n) if n > 1 else 0,
            "total_is_notional": sum(is_notional),
            "mean_is_per_share": sum(is_per_share) / n,
            "by_symbol": list(by_symbol.values()),
        },
    }
