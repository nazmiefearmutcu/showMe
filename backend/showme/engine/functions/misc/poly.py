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

# status -> (Gamma active flag, Gamma closed flag). None = do not send the flag.
_STATUS_API: dict[str, tuple[bool | None, bool | None]] = {
    "open": (True, False),
    "closed": (None, True),
    "resolved": (None, True),
    "all": (None, None),
}


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
        if status not in _STATUS_API:
            status = "open"
        if include_closed and status == "open":
            status = "all"
        # Gamma query flags per status. `closed` is a hard server-side filter:
        # `all` must send neither flag, or every open market disappears.
        api_active, api_closed = _STATUS_API[status]
        include_closed = status != "open"
        try:
            limit = int(params.get("limit", 100))
        except (TypeError, ValueError):
            limit = 100
        limit = max(1, min(limit, 100))
        # Gamma window the adapter scans (mirrors fetch_markets' target cap).
        resolved_scan_window = min(max(limit * 4, 100), 400)
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
                    adapter.search(query, limit=max(limit * 4, 100), active=api_active,
                                   closed=api_closed, min_liquidity=min_liq),
                    timeout=timeout,
                )
            except Exception as e:  # noqa: BLE001 - fall through to keyless HTTP
                provider_errors.append(f"polymarket_adapter: {e}")
                raw_rows = None

        # 2) DEFAULT keyless path: fetch the public Gamma markets directly.
        if raw_rows is None:
            try:
                raw_rows = await asyncio.wait_for(
                    _fetch_gamma_markets(query, limit=limit, active=api_active,
                                         closed=api_closed, min_liquidity=min_liq),
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
        for r in raw_rows:
            row = _shape_market(r)
            if status == "open" and (r.get("closed") is True or _is_past(row.get("end_date"))):
                continue
            if status == "closed" and r.get("closed") is not True:
                continue
            # `closed` alone is not resolution: resolved needs the UMA status.
            if status == "resolved" and not row["resolved"]:
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

        # Honesty: an empty success must say WHY it is empty. A topic filter
        # that removed every market is an answer, not an outage — surface it
        # so the pane never shows a bare "0 markets" with no reason.
        result_warnings: list[str] = []
        if provider_errors:
            result_warnings.append(f"adapter fell back to keyless Gamma: {provider_errors[0]}")
        if not compact and query:
            result_warnings.append(
                f"Gamma returned open markets, but none matched the topic filter {str(query)!r}."
            )
        if not compact and status == "resolved" and raw_rows:
            result_warnings.append(
                "Gamma returned closed markets, but none carried umaResolutionStatus=resolved."
            )
        # The resolved (UMA) filter runs client-side over the Gamma window the
        # adapter fetched. A saturated window can hide resolved markets beyond
        # it, so say so instead of reporting a complete ok result.
        if status == "resolved":
            if len(raw_rows) >= resolved_scan_window:
                result_warnings.append(
                    f"status=resolved filters only the first {resolved_scan_window} closed markets "
                    "by 24h volume; resolved markets beyond that window are not listed."
                )

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
                # Market-level totals, computed once per market (rows repeat
                # the market liquidity per outcome, so rows must not be summed).
                "market_count": len(compact),
                "total_liquidity_usd": total_liquidity,
                "methodology": (
                    "POLY reads the keyless Polymarket Gamma /markets endpoint. status=open keeps active, "
                    "unclosed, not-past-end markets; status=closed keeps Gamma closed=true markets; "
                    "status=resolved keeps closed markets whose umaResolutionStatus is 'resolved' (closed is "
                    "not the same as resolved); status=all sends no closed filter. It parses raw "
                    "outcomes/outcomePrices JSON into per-outcome rows, computes implied_prob = price * 100, "
                    "and keeps slugs/end dates visible for source inspection. "
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
            warnings=result_warnings,
            metadata={"query": query, "matched": len(compact), "provider_errors": provider_errors,
                      "fetched": len(raw_rows), "limit": limit, "min_liquidity_usd": min_liq,
                      **({"resolved_scan_window": resolved_scan_window} if status == "resolved" else {})},
        )


async def _fetch_gamma_markets(
    query: Any, *, limit: int, active: bool | None, closed: bool | None, min_liquidity: float = 0
) -> list[dict[str, Any]]:
    """Fetch live markets from the keyless Polymarket Gamma API."""
    from showme.providers._http import get_client
    from showme.engine.data_sources.alt.polymarket_adapter import fetch_markets

    client = await get_client()
    return await fetch_markets(client, query, limit=max(limit * 4, 100),
                               active=active, closed=closed, min_liquidity=min_liquidity)


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
        "uma_resolution_status": row.get("umaResolutionStatus"),
        "resolved": str(row.get("umaResolutionStatus") or "").strip().lower() == "resolved",
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
