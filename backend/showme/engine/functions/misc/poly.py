"""POLY — Polymarket prediction-market snapshot.

Default: live active markets sorted by volume, fetched KEYLESS from the
public Polymarket Gamma API (https://gamma-api.polymarket.com/markets).
``query`` param ile arama: 'election', 'fed cuts', 'btc 100k' ...

The manifest seed claims this surfaces real prediction-market prices on
real-world events. The Gamma ``/markets`` endpoint is fully public (no
key), so the DEFAULT path returns real live questions, outcome prices,
implied probabilities, volume and liquidity. A graceful, clearly-labeled
provider_unavailable fallback fires ONLY on a real network failure.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument

_GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"


@FunctionRegistry.register
class POLYFunction(BaseFunction):
    code = "POLY"
    name = "Polymarket"
    category = "misc"
    description = "Prediction-market odds (Polymarket public Gamma markets)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        query = params.get("query")
        include_closed = _truthy(params.get("include_closed") or params.get("closed"))
        # manifest `status` select: open | closed | resolved | all
        status = str(params.get("status") or ("all" if include_closed else "open")).strip().lower()
        if status in {"closed", "resolved", "all"}:
            include_closed = True
        active = not include_closed
        try:
            limit = int(params.get("limit", 25))
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 100))
        timeout = float(params.get("timeout", 8))
        try:
            min_liq = float(params.get("min_liquidity_usd") or 0)
        except (TypeError, ValueError):
            min_liq = 0.0

        # 1) Preferred path: an injected polymarket adapter, when present.
        adapter = getattr(self.deps, "polymarket", None)
        raw_rows: list[dict[str, Any]] | None = None
        provider_errors: list[str] = []
        if adapter is not None and hasattr(adapter, "search"):
            try:
                raw_rows = await asyncio.wait_for(
                    adapter.search(query, limit=limit, active=active, closed=include_closed),
                    timeout=timeout,
                )
            except Exception as e:  # noqa: BLE001 - fall through to keyless HTTP
                provider_errors.append(f"polymarket_adapter: {e}")
                raw_rows = None

        # 2) DEFAULT keyless path: fetch the public Gamma markets directly.
        if raw_rows is None:
            try:
                raw_rows = await asyncio.wait_for(
                    _fetch_gamma_markets(query, limit=limit, active=active, closed=include_closed),
                    timeout=timeout,
                )
            except Exception as e:  # noqa: BLE001 - real network outage
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data=_fallback_markets(query, reason=str(e)),
                    sources=["polymarket"],
                    warnings=[
                        "Polymarket Gamma feed unavailable; showing no markets rather than fabricated odds."
                    ],
                    metadata={"provider_errors": provider_errors + [f"gamma: {e}"], "query": query},
                )

        compact: list[dict[str, Any]] = []
        for r in raw_rows[:100]:
            row = _shape_market(r)
            if not include_closed and _is_past(row.get("end_date")):
                continue
            if min_liq and (row.get("liquidity") is None or row["liquidity"] < min_liq):
                continue
            if query and not _matches_query(r, query):
                continue
            compact.append({**row, "question": r.get("question")})

        compact.sort(key=lambda x: (x.get("volume") or 0.0), reverse=True)
        compact = compact[:limit]

        # Expand to one row PER OUTCOME to match the manifest table_schema
        # (market_id, question, outcome, price, implied_prob, liquidity_usd, end_date, source).
        table_rows = _expand_outcome_rows(compact)
        total_liquidity = round(sum(x.get("liquidity") or 0.0 for x in compact), 2)
        top_market = compact[0].get("question") if compact else None
        status_label = "ok" if compact else "empty"
        as_of = datetime.now(timezone.utc).isoformat()

        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": status_label,
                "data_mode": "delayed_reference" if compact else "cached_snapshot",
                "query": query,
                "rows": table_rows,
                "markets": compact,
                "series": [],
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
                    {"key": "market_count", "label": "Markets", "value": len(compact)},
                    {"key": "total_liquidity_usd", "label": "Liquidity", "value": total_liquidity, "unit": "USD"},
                    {"key": "top_market", "label": "Top Market", "value": _short(top_market)},
                    {"key": "data_mode", "label": "Mode", "value": "delayed_reference" if compact else "cached_snapshot"},
                    {"key": "as_of", "label": "As of", "value": as_of},
                ],
                "as_of": as_of,
                "methodology": (
                    "POLY reads the keyless Polymarket Gamma /markets endpoint, filters closed/past-end markets "
                    "by default (status=open), parses raw outcomes/outcomePrices JSON into per-outcome rows, "
                    "computes implied_prob = price * 100, and keeps slugs/end dates visible for source inspection. "
                    "On a network outage it returns provider_unavailable with empty rows — never synthetic odds."
                ),
                "field_dictionary": {
                    "market_id": "Polymarket market slug / id.",
                    "question": "Market question.",
                    "outcome": "Outcome label (Yes / No / candidate).",
                    "price": "On-chain mid price in [0, 1] for the outcome.",
                    "implied_prob": "price * 100 (percent).",
                    "liquidity_usd": "Reported Polymarket liquidity (USD).",
                    "volume": "Reported Polymarket volume.",
                    "end_date": "Market end date.",
                    "source": "Origin feed (polymarket_gamma).",
                },
            },
            sources=["polymarket"],
            warnings=provider_errors and [f"adapter fell back to keyless Gamma: {provider_errors[0]}"] or [],
            metadata={"query": query, "matched": len(compact), "provider_errors": provider_errors},
        )


async def _fetch_gamma_markets(
    query: Any, *, limit: int, active: bool, closed: bool
) -> list[dict[str, Any]]:
    """Fetch live markets from the keyless Polymarket Gamma API."""
    from showme.providers._http import get_client

    client = await get_client()
    # Over-fetch so client-side query/liquidity filtering still yields `limit` rows.
    params: dict[str, Any] = {
        "limit": max(limit * 4, 100),
        "order": "volume24hr",
        "ascending": "false",
        "archived": "false",
    }
    if active and not closed:
        params["active"] = "true"
        params["closed"] = "false"
    elif closed and not active:
        params["closed"] = "true"
    resp = await client.get(_GAMMA_MARKETS_URL, params=params)
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, dict):
        payload = payload.get("data") or payload.get("markets") or []
    return [row for row in payload if isinstance(row, dict)]


def _matches_query(row: dict[str, Any], query: Any) -> bool:
    q = str(query or "").strip().lower()
    if not q:
        return True
    hay = " ".join(
        str(row.get(k) or "")
        for k in ("question", "title", "slug", "description", "groupItemTitle")
    ).lower()
    return all(token in hay for token in q.split())


def _expand_outcome_rows(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for m in markets:
        outcomes = [s.strip() for s in str(m.get("outcomes") or "").split(",") if s.strip()]
        prices = [_to_float(s) for s in str(m.get("outcome_prices") or "").split(",")]
        if not outcomes:
            continue
        for outcome, price in zip(outcomes, prices, strict=False):
            if price is None:
                continue
            rows.append(
                {
                    "market_id": m.get("slug"),
                    "question": m.get("question"),
                    "outcome": outcome,
                    "price": price,
                    "implied_prob": round(price * 100.0, 6),
                    "liquidity_usd": m.get("liquidity"),
                    "volume": m.get("volume"),
                    "end_date": m.get("end_date"),
                    "source": "polymarket_gamma",
                }
            )
    return rows


def _fallback_markets(query: Any, reason: str | None = None) -> dict[str, Any]:
    detail = reason or "feed unavailable"
    return {
        "status": "provider_unavailable",
        "data_mode": "not_configured",
        "reason": f"Prediction market feed unavailable{f' for {query}' if query else ''}: {detail}",
        "rows": [],
        "markets": [],
        "cards": [
            {"key": "data_mode", "label": "Mode", "value": "not_configured"},
        ],
        "methodology": (
            "POLY reads the keyless Polymarket Gamma /markets endpoint. This response indicates a real "
            "network outage reaching gamma-api.polymarket.com — no odds are fabricated."
        ),
        "field_dictionary": {},
        "next_actions": [
            "Check network access to gamma-api.polymarket.com or reduce the search query.",
        ],
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
