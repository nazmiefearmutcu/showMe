"""Viz Agent — picks the chart/table shape best suited to the result."""
from __future__ import annotations

from typing import Any

from .planner import Plan


def pick_viz(plan: Plan, search_result: dict[str, Any]) -> dict[str, Any]:
    kind = search_result.get("kind")
    data = search_result.get("data") or {}

    if kind == "fanout":
        # Suggest a 3-pane split: PORT + SCAN + TOP.
        return {
            "kind": "split",
            "panes": [
                {"code": "PORT"},
                {"code": "SCAN"},
                {"code": "TOP"},
            ],
        }
    if kind == "scan":
        rows = data.get("rows") or []
        return {
            "kind": "table",
            "title": f"Scanner — {data.get('universe_key', '?')}",
            "rows_n": len(rows),
            "open_pane_hint": {"code": "SCAN"},
        }
    if kind == "function":
        code = (search_result.get("code") or plan.args.get("code") or "").upper()
        # Charts for price-shaped functions, table otherwise.
        if code in ("GP", "TECH"):
            return {"kind": "chart", "code": code,
                    "open_pane_hint": {"code": code,
                                       "symbol": (plan.args.get("symbols") or [None])[0]}}
        if code == "PORT":
            return {"kind": "table", "title": "Portfolio",
                    "open_pane_hint": {"code": "PORT"}}
        # Lookup / DES → cards.
        if code in ("DES", "FA"):
            return {"kind": "cards", "code": code,
                    "open_pane_hint": {"code": code,
                                       "symbol": (plan.args.get("symbols") or [None])[0]}}
        return {"kind": "metric", "code": code}
    if kind == "compare":
        sym = (plan.args.get("symbols") or [None])[0]
        return {
            "kind": "split",
            "panes": [
                {"code": "DES", "symbol": s} for s in plan.args.get("symbols") or [sym]
            ][:2],
        }
    return {"kind": "none"}
