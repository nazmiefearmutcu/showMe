"""Summarizer — turns the search payload into prose + structured highlights.

Round 19 ships a deterministic narrative builder. When the ShowMe
`llm_router` is available the orchestrator can call ``summarize_with_llm``
(future round); the deterministic path here is always the floor.
"""
from __future__ import annotations

from typing import Any

from .planner import Plan


def summarize(plan: Plan, search_result: dict[str, Any]) -> dict[str, Any]:
    kind = search_result.get("kind")
    warnings = list(search_result.get("warnings") or [])
    if kind == "fanout":
        return _summarize_fanout(plan, search_result, warnings)
    if kind == "scan":
        return _summarize_scan(plan, search_result, warnings)
    if kind == "function":
        return _summarize_function(plan, search_result, warnings)
    if kind == "compare":
        return _summarize_compare(plan, search_result, warnings)
    if kind == "noop":
        return {
            "narrative": (
                "I couldn't classify your query — try asking about a scan, "
                "a portfolio, a single ticker, or a function code."
            ),
            "highlights": [],
            "warnings": warnings,
        }
    return {
        "narrative": "(no result payload)",
        "highlights": [],
        "warnings": warnings,
    }


def _summarize_scan(
    plan: Plan, sr: dict[str, Any], warnings: list[str],
) -> dict[str, Any]:
    data = sr.get("data") or {}
    rows = data.get("rows") or []
    asset_class = data.get("asset_class") or plan.args.get("asset_class") or "?"
    universe = data.get("universe_key") or "?"
    top = rows[:5]
    longs = [r for r in rows if r.get("direction") == "LONG"]
    shorts = [r for r in rows if r.get("direction") == "SHORT"]
    overext = [r for r in rows if (r.get("fine") or {}).get("overextension", {}).get("overextended")]
    held = [r for r in rows if (r.get("position_overlap") or {}).get("held")]

    parts: list[str] = []
    parts.append(
        f"Scanner produced {len(rows)} candidates from **{universe}** "
        f"({asset_class})."
    )
    if longs:
        parts.append(f"{len(longs)} LONG bias, {len(shorts)} SHORT bias.")
    if held:
        held_syms = ", ".join(h["symbol"] for h in held[:3])
        parts.append(f"Currently held: {held_syms}.")
    if overext:
        oe_syms = ", ".join(r["symbol"] for r in overext[:3])
        parts.append(f"Overextended: {oe_syms}.")
    if top:
        peek = ", ".join(
            f"{r['symbol']} ({r.get('direction', '?')[0:1] or '?'} "
            f"{r.get('confidence', 0):.0f})"
            for r in top
        )
        parts.append(f"Top: {peek}.")
    narrative = " ".join(parts)

    highlights = [
        {
            "label": "rows", "value": len(rows),
            "tone": "neutral",
        },
        {
            "label": "long", "value": len(longs),
            "tone": "positive" if longs else "muted",
        },
        {
            "label": "short", "value": len(shorts),
            "tone": "negative" if shorts else "muted",
        },
        {
            "label": "overextended", "value": len(overext),
            "tone": "warn" if overext else "muted",
        },
        {
            "label": "held in book", "value": len(held),
            "tone": "muted",
        },
    ]
    return {"narrative": narrative, "highlights": highlights, "warnings": warnings}


def _summarize_function(
    plan: Plan, sr: dict[str, Any], warnings: list[str],
) -> dict[str, Any]:
    code = sr.get("code", plan.args.get("code") or "?")
    payload = sr.get("data") or {}
    data_blob = payload.get("data")
    elapsed = payload.get("elapsed_ms")
    sources = payload.get("sources") or []
    label = code.upper()
    parts = [f"Ran {label}"]
    sym = (plan.args.get("symbols") or [None])[0]
    if sym:
        parts[0] += f" on {sym}"
    parts[0] += "."
    if elapsed:
        parts.append(f"Took {elapsed:.0f} ms.")
    if sources:
        parts.append(f"Sources: {', '.join(sources)}.")
    if isinstance(data_blob, list):
        parts.append(f"{len(data_blob)} record(s) returned.")
    elif isinstance(data_blob, dict):
        keys = list(data_blob.keys())[:5]
        if keys:
            parts.append(f"Top keys: {', '.join(keys)}.")
    elif data_blob is None:
        parts.append("No payload — function returned warnings only.")
    narrative = " ".join(parts)
    highlights: list[dict[str, Any]] = []
    if isinstance(data_blob, list):
        highlights.append({"label": "rows", "value": len(data_blob), "tone": "neutral"})
    if elapsed:
        highlights.append({"label": "ms", "value": int(elapsed), "tone": "muted"})
    if warnings:
        highlights.append({"label": "warn", "value": len(warnings), "tone": "warn"})
    return {"narrative": narrative, "highlights": highlights, "warnings": warnings}


def _summarize_compare(
    plan: Plan, sr: dict[str, Any], warnings: list[str],
) -> dict[str, Any]:
    syms = sr.get("symbols") or plan.args.get("symbols") or []
    if not syms:
        return {
            "narrative": "Compare needs at least two symbols — none parsed.",
            "highlights": [],
            "warnings": warnings,
        }
    head = " vs. ".join(syms[:4])
    return {
        "narrative": (
            f"Open DES + GP for {head}. Round 19 keeps the data fetch lazy — "
            "click 'Open DES' on the suggested layout to materialize."
        ),
        "highlights": [
            {"label": "symbols", "value": len(syms), "tone": "neutral"},
        ],
        "warnings": warnings,
    }


def _summarize_fanout(
    plan: Plan, sr: dict[str, Any], warnings: list[str],
) -> dict[str, Any]:
    branches = sr.get("branches") or {}
    parts: list[str] = ["Briefing:"]
    highlights: list[dict[str, Any]] = []

    # Portfolio leg.
    p = (branches.get("portfolio") or {}).get("data") or {}
    p_data = (p.get("data") or {}) if isinstance(p, dict) else {}
    totals = p_data.get("totals") if isinstance(p_data, dict) else None
    if totals:
        n = totals.get("n_positions") or 0
        mv = totals.get("market_value")
        parts.append(f"portfolio = {n} position(s)" + (f", MV ≈ ${mv:,.0f}" if isinstance(mv, (int, float)) and mv else "") + ".")
        highlights.append({"label": "positions", "value": n, "tone": "neutral"})

    # Scan leg.
    s = (branches.get("scan") or {}).get("data") or {}
    rows = s.get("rows") or [] if isinstance(s, dict) else []
    if rows:
        long_n = sum(1 for r in rows if r.get("direction") == "LONG")
        short_n = sum(1 for r in rows if r.get("direction") == "SHORT")
        oext = sum(1 for r in rows if (r.get("fine") or {}).get("overextension", {}).get("overextended"))
        top = ", ".join(r.get("symbol", "?") for r in rows[:3])
        parts.append(
            f"scanner picked {len(rows)} candidates ({long_n}L/{short_n}S, {oext} overextended): {top}."
        )
        highlights.append({"label": "scan rows", "value": len(rows), "tone": "neutral"})
        if long_n:
            highlights.append({"label": "long", "value": long_n, "tone": "positive"})
        if short_n:
            highlights.append({"label": "short", "value": short_n, "tone": "negative"})
        if oext:
            highlights.append({"label": "overextended", "value": oext, "tone": "warn"})

    # News leg.
    n_branch = (branches.get("news") or {}).get("data") or {}
    n_data = (n_branch.get("data") or {}) if isinstance(n_branch, dict) else {}
    n_count = None
    if isinstance(n_data, list):
        n_count = len(n_data)
    elif isinstance(n_data, dict):
        items = n_data.get("items") or n_data.get("news")
        if isinstance(items, list):
            n_count = len(items)
    if n_count is not None:
        parts.append(f"news pulled {n_count} headline(s).")
        highlights.append({"label": "headlines", "value": n_count, "tone": "muted"})

    return {
        "narrative": " ".join(parts) if len(parts) > 1 else "Briefing produced no usable branches.",
        "highlights": highlights,
        "warnings": warnings,
    }
