"""POLY — Polymarket prediction-market snapshot.

Default: active markets sorted by volume.
``query`` param ile arama: 'election', 'fed cuts', 'btc 100k' ...
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


@FunctionRegistry.register
class POLYFunction(BaseFunction):
    code = "POLY"
    name = "Polymarket"
    category = "misc"
    description = "Prediction-market odds (Polymarket public CLOB markets)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        adapter = getattr(self.deps, "polymarket", None)
        query = params.get("query")
        if adapter is None:
            return FunctionResult(code=self.code, instrument=None,
                                  data=_fallback_markets(query),
                                  sources=["prediction_market_model"])
        try:
            rows = await asyncio.wait_for(
                adapter.search(query, limit=int(params.get("limit", 25))),
                timeout=float(params.get("timeout", 8)),
            )
        except Exception as e:
            return FunctionResult(code=self.code, instrument=None,
                                  data=_fallback_markets(query),
                                  sources=["prediction_market_model"],
                                  metadata={"provider_errors": [f"polymarket: {e}"]})
        compact = []
        for r in rows[:50]:
            compact.append({
                "question": r.get("question"),
                "slug": r.get("slug"),
                "volume": r.get("volume"),
                "liquidity": r.get("liquidity"),
                "outcome_prices": r.get("outcomePrices"),
                "outcomes": r.get("outcomes"),
                "end_date": r.get("endDate"),
                "category": (r.get("category") or {}) if isinstance(r.get("category"), dict) else r.get("category"),
            })
        return FunctionResult(
            code=self.code, instrument=None, data=compact,
            sources=["polymarket"],
            metadata={"query": query, "matched": len(compact)},
        )


def _fallback_markets(query: Any) -> list[dict[str, Any]]:
    return [{
        "question": f"Prediction market feed unavailable{f' for {query}' if query else ''}",
        "slug": None,
        "volume": 0,
        "liquidity": 0,
        "outcome_prices": [],
        "outcomes": [],
        "end_date": None,
        "category": "provider_unavailable",
    }]
