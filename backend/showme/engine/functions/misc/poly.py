"""POLY — Polymarket prediction-market snapshot.

Default: active markets sorted by volume.
``query`` param ile arama: 'election', 'fed cuts', 'btc 100k' ...
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


@FunctionRegistry.register
class POLYFunction(BaseFunction):
    code = "POLY"
    name = "Polymarket"
    category = "misc"
    description = "Prediction-market odds (Polymarket public CLOB markets)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        adapter = getattr(self.deps, "polymarket", None)
        query = params.get("query")
        include_closed = _truthy(params.get("include_closed") or params.get("closed"))
        active = not include_closed
        limit = int(params.get("limit", 25))
        if adapter is None:
            return FunctionResult(code=self.code, instrument=None,
                                  data=_fallback_markets(query),
                                  sources=["prediction_market_reference"])
        try:
            rows = await asyncio.wait_for(
                adapter.search(query, limit=limit, active=active, closed=include_closed),
                timeout=float(params.get("timeout", 8)),
            )
        except Exception as e:
            return FunctionResult(code=self.code, instrument=None,
                                  data=_fallback_markets(query),
                                  sources=["prediction_market_reference"],
                                  metadata={"provider_errors": [f"polymarket: {e}"]})
        compact = []
        for r in rows[:50]:
            row = _shape_market(r)
            if not include_closed and _is_past(row.get("end_date")):
                continue
            compact.append({
                **row,
                "question": r.get("question"),
            })
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "live",
                "query": query,
                "rows": compact,
                "surface": [
                    {
                        "market": _short(row.get("question")),
                        "volume": row.get("volume"),
                        "value": row.get("volume"),
                    }
                    for row in compact
                    if row.get("volume") is not None
                ],
                "cards": [
                    {"label": "Markets", "value": len(compact)},
                    {"label": "Closed", "value": include_closed},
                ],
                "methodology": (
                    "POLY reads Polymarket public Gamma markets, filters closed/past-end markets by default, "
                    "parses raw outcomes/outcomePrices JSON into best-outcome and yes/no probability fields, "
                    "and keeps slugs/end dates visible for source inspection."
                ),
                "field_dictionary": {
                    "question": "Market question.",
                    "yes_price": "Parsed first yes-style outcome price when available.",
                    "best_outcome": "Outcome with highest displayed price.",
                    "volume": "Reported Polymarket volume.",
                    "liquidity": "Reported Polymarket liquidity.",
                    "end_date": "Market end date.",
                },
            },
            sources=["polymarket"],
            metadata={"query": query, "matched": len(compact)},
        )


def _fallback_markets(query: Any) -> list[dict[str, Any]]:
    return {
        "status": "provider_unavailable",
        "reason": f"Prediction market feed unavailable{f' for {query}' if query else ''}",
        "rows": [],
        "next_actions": ["Check network access to gamma-api.polymarket.com or reduce the search query."],
    }


def _shape_market(row: dict[str, Any]) -> dict[str, Any]:
    outcomes = _parse_jsonish(row.get("outcomes"))
    prices = [_to_float(item) for item in _parse_jsonish(row.get("outcomePrices"))]
    pairs = [
        {"outcome": str(outcome), "price": price}
        for outcome, price in zip(outcomes, prices, strict=False)
        if price is not None
    ]
    best = max(pairs, key=lambda item: item["price"], default={})
    yes_price = None
    no_price = None
    for item in pairs:
        label = item["outcome"].lower()
        if label in {"yes", "up", "true"} and yes_price is None:
            yes_price = item["price"]
        if label in {"no", "down", "false"} and no_price is None:
            no_price = item["price"]
    category = row.get("category")
    if isinstance(category, dict):
        category = category.get("label") or category.get("name") or category.get("slug")
    return {
        "slug": row.get("slug"),
        "volume": _to_float(row.get("volume")),
        "liquidity": _to_float(row.get("liquidity")),
        "yes_price": yes_price,
        "no_price": no_price,
        "best_outcome": best.get("outcome"),
        "best_price": best.get("price"),
        "outcomes": ", ".join(map(str, outcomes[:6])),
        "outcome_prices": ", ".join(str(price) for price in prices[:6] if price is not None),
        "end_date": row.get("endDate"),
        "active": row.get("active"),
        "closed": row.get("closed"),
        "category": category,
        "source_mode": "polymarket_gamma",
    }


def _parse_jsonish(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return [part.strip() for part in value.strip("[]").split(",") if part.strip()]
    return []


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _is_past(value: Any) -> bool:
    if not value:
        return False
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt < datetime.now(timezone.utc)
    except Exception:
        return False


def _short(value: Any) -> str:
    text = str(value or "")
    return text if len(text) <= 48 else text[:45] + "..."


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
