"""MICRO — Market microstructure (L2 depth, spread, microprice, imbalance).

Pulls a real L2 order-book snapshot from the keyless Binance spot REST depth
endpoint (``GET /api/v3/depth?symbol={SYMBOL}&limit={depth_levels}``) and derives:

  - Bid/ask top-of-book and the depth ladder (per-side levels + cumulative size)
  - Quoted spread + spread_bps
  - Microprice (size-weighted mid that better tracks the next trade)
  - Top-of-book queue imbalance in [-1, 1]
  - Cumulative-depth buckets and a Kyle's-lambda price-impact proxy

Only crypto (Binance) exposes a real L2 depth feed in our adapter set. Every
other asset class is surfaced as ``explicit_unavailable`` (empty ladder + a
next_action pointing to the QUOTE/GP pane) rather than rendering a synthetic
ladder, exactly as the manifest's
``micro_explicit_unavailable_when_no_depth_provider`` test pins.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx
import numpy as np

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument

_SPOT_DEPTH_URL = "https://api.binance.com/api/v3/depth"
_SPOT_KLINES_URL = "https://api.binance.com/api/v3/klines"

_FIELD_DICTIONARY: dict[str, str] = {
    "as_of": "UTC timestamp of the depth snapshot.",
    "symbol": "Canonical symbol with an L2 depth feed (Binance spot).",
    "bids[].price": "Bid level price (quote ccy), best first.",
    "bids[].size": "Bid level resting size (base ccy).",
    "asks[].price": "Ask level price (quote ccy), best first.",
    "asks[].size": "Ask level resting size (base ccy).",
    "spread_bps": "(best_ask - best_bid) / mid * 10000.",
    "microprice": "Size-weighted mid: (bid*ask_size + ask*bid_size)/(bid_size+ask_size).",
    "imbalance": "Top-of-book size imbalance (bid_size - ask_size)/(bid_size + ask_size) in [-1, 1].",
    "data_mode": "live_exchange | provider_unavailable | explicit_unavailable.",
    "rows[].side": "bid | ask for the ladder row.",
    "rows[].cum_size": "Cumulative size from best to this level.",
    "rows[].notional": "price * size for this level.",
    "kyle_lambda_proxy": "Local price-impact proxy from recent kline returns vs dollar volume (lower = more liquid).",
}

_NEXT_ACTIONS = [
    {"id": "save_screen", "label": "Save screen"},
    {"id": "export_csv", "label": "Export CSV"},
    {"id": "open_in_gp", "label": "Open in GP"},
]


@FunctionRegistry.register
class MICROFunction(BaseFunction):
    code = "MICRO"
    name = "Market Microstructure"
    asset_classes = (AssetClass.CRYPTO, AssetClass.EQUITY)
    category = "screen"
    description = "Live L2 order-book depth, spread, microprice, imbalance and Kyle's lambda proxy."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_unavailable_microstructure(
                    "",
                    data_mode="explicit_unavailable",
                    status="empty",
                    reason="instrument required",
                    next_action="Select a crypto symbol with an L2 depth feed such as BTCUSDT.",
                ),
                sources=["binance"],
                warnings=["instrument required"],
            )

        sym = instrument.symbol.upper()

        # Only crypto (Binance) exposes a real L2 depth feed in our adapter set.
        # Anything else is explicit_unavailable — never a synthetic ladder.
        if instrument.asset_class != AssetClass.CRYPTO:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_unavailable_microstructure(
                    sym,
                    data_mode="explicit_unavailable",
                    status="empty",
                    reason="No L2 depth provider is configured for this asset class.",
                    next_action="Open this symbol in the QUOTE/GP pane for top-of-book pricing, "
                    "or pick a Binance spot pair (e.g. BTCUSDT) for full L2 microstructure.",
                ),
                sources=["binance"],
                warnings=["L2 order-book depth is only available for crypto (Binance) in the local provider set."],
            )

        depth_limit = _normalize_depth_limit(
            params.get("depth_levels") or params.get("depth_limit") or params.get("limit") or 20
        )
        interval = str(params.get("interval") or "1m")
        kline_limit = max(50, min(int(params.get("kline_limit", 200) or 200), 1000))
        timeout = float(params.get("timeout", 8) or 8)

        try:
            async with httpx.AsyncClient(
                timeout=timeout, headers={"User-Agent": "showMe/1.0 (research; contact@example.com)"}
            ) as client:
                depth, klines = await asyncio.gather(
                    client.get(_SPOT_DEPTH_URL, params={"symbol": sym, "limit": depth_limit}),
                    client.get(
                        _SPOT_KLINES_URL,
                        params={"symbol": sym, "interval": interval, "limit": kline_limit},
                    ),
                    return_exceptions=True,
                )
        except Exception as exc:  # pragma: no cover - defensive
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_unavailable_microstructure(
                    sym,
                    data_mode="provider_unavailable",
                    status="provider_unavailable",
                    reason=f"binance depth request failed: {exc}",
                    next_action="Retry with a liquid Binance spot pair such as BTCUSDT.",
                ),
                sources=["binance"],
                warnings=[f"binance depth request failed: {exc}"],
            )

        if isinstance(depth, Exception) or getattr(depth, "status_code", None) != 200:
            reason = str(depth) if isinstance(depth, Exception) else f"binance depth status {depth.status_code}"
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_unavailable_microstructure(
                    sym,
                    data_mode="provider_unavailable",
                    status="provider_unavailable",
                    reason=reason,
                    next_action="Retry with a Binance spot pair or lower the depth limit.",
                ),
                sources=["binance"],
                warnings=[reason],
            )

        d = depth.json()
        raw_bids = [(float(p), float(q)) for p, q in (d.get("bids") or [])]
        raw_asks = [(float(p), float(q)) for p, q in (d.get("asks") or [])]
        if not raw_bids or not raw_asks:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_unavailable_microstructure(
                    sym,
                    data_mode="provider_unavailable",
                    status="provider_unavailable",
                    reason="empty order book from Binance",
                    next_action="Retry with a liquid Binance spot symbol.",
                ),
                sources=["binance"],
                warnings=["empty order book from Binance"],
            )

        # Binance returns bids best->worst (desc price) and asks best->worst (asc price).
        as_of = datetime.now(timezone.utc).isoformat()
        best_bid_p, best_bid_q = raw_bids[0]
        best_ask_p, best_ask_q = raw_asks[0]
        mid = (best_bid_p + best_ask_p) / 2
        spread = best_ask_p - best_bid_p
        spread_bps = (spread / mid) * 10_000 if mid else 0.0

        # Microprice: size-weighted mid (weights cross — bid weighted by ask size).
        size_sum = best_bid_q + best_ask_q
        microprice = (
            (best_bid_p * best_ask_q + best_ask_p * best_bid_q) / size_sum if size_sum else mid
        )
        imbalance = (best_bid_q - best_ask_q) / max(size_sum, 1e-12)

        # Structured per-side ladders for the chart/card contract.
        bid_levels = [{"price": p, "size": q} for p, q in raw_bids[:depth_limit]]
        ask_levels = [{"price": p, "size": q} for p, q in raw_asks[:depth_limit]]

        # Flat table rows (table_schema: side/price/size/cum_size/notional).
        rows: list[dict[str, Any]] = []
        cum = 0.0
        for lvl in bid_levels:
            cum += lvl["size"]
            rows.append(
                {
                    "side": "bid",
                    "price": lvl["price"],
                    "size": lvl["size"],
                    "cum_size": cum,
                    "notional": lvl["price"] * lvl["size"],
                }
            )
        cum = 0.0
        for lvl in ask_levels:
            cum += lvl["size"]
            rows.append(
                {
                    "side": "ask",
                    "price": lvl["price"],
                    "size": lvl["size"],
                    "cum_size": cum,
                    "notional": lvl["price"] * lvl["size"],
                }
            )

        # Cumulative-depth buckets (richer surface for the depth panel).
        depth_levels = [n for n in [5, 10, 20, 50, 100] if n <= depth_limit]
        if depth_limit not in depth_levels:
            depth_levels.append(depth_limit)
        depth_table = []
        for n in depth_levels:
            bid_q = sum(q for _, q in raw_bids[:n])
            ask_q = sum(q for _, q in raw_asks[:n])
            bid_notional = sum(p * q for p, q in raw_bids[:n])
            ask_notional = sum(p * q for p, q in raw_asks[:n])
            bucket_imb = (bid_q - ask_q) / max(bid_q + ask_q, 1e-9)
            depth_table.append(
                {
                    "bucket": f"Top {n}",
                    "levels": n,
                    "bid_qty": bid_q,
                    "ask_qty": ask_q,
                    "bid_notional": bid_notional,
                    "ask_notional": ask_notional,
                    "imbalance": bucket_imb,
                    "value": bucket_imb,
                }
            )

        # Kyle's lambda price-impact proxy from recent klines.
        kyle_lambda: float | None = None
        kyle_points = 0
        kyle_warning: str | None = None
        if not isinstance(klines, Exception) and getattr(klines, "status_code", None) == 200:
            try:
                krows = klines.json() or []
                if krows:
                    closes = np.array([float(r[4]) for r in krows])
                    vols = np.array([float(r[5]) for r in krows])
                    rets = np.diff(np.log(closes))
                    abs_rets = np.abs(rets)
                    vol_dollar = vols[1:] * closes[1:]
                    if len(abs_rets) > 30 and vol_dollar.sum() > 0:
                        beta = np.cov(abs_rets, vol_dollar)[0, 1] / max(np.var(vol_dollar), 1e-12)
                        kyle_lambda = abs(float(beta))
                        kyle_points = int(len(abs_rets))
            except Exception as exc:
                kyle_warning = str(exc)
        elif isinstance(klines, Exception):
            kyle_warning = str(klines)
        elif getattr(klines, "status_code", None) != 200:
            kyle_warning = f"binance klines status {getattr(klines, 'status_code', '??')}"

        warnings = [kyle_warning] if kyle_warning else []

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "data_mode": "live_exchange",
                "as_of": as_of,
                "symbol": sym,
                # Contract must-haves.
                "bids": bid_levels,
                "asks": ask_levels,
                "best_bid": best_bid_p,
                "best_ask": best_ask_p,
                "mid": mid,
                "spread": spread,
                "spread_bps": spread_bps,
                "microprice": microprice,
                "imbalance": imbalance,
                # Table + chart payloads.
                "rows": rows,
                "surface": depth_table,
                "depth_table": depth_table,
                "depth_ladder": rows,
                # Cards.
                "cards": {
                    "symbol": sym,
                    "bid": best_bid_p,
                    "ask": best_ask_p,
                    "spread_bps": spread_bps,
                    "microprice": microprice,
                    "imbalance": imbalance,
                    "data_mode": "live_exchange",
                    "as_of": as_of,
                },
                "summary": {
                    "symbol": sym,
                    "spread_bps": spread_bps,
                    "microprice": microprice,
                    "imbalance": imbalance,
                    "top10_imbalance": depth_table[1]["imbalance"] if len(depth_table) > 1 else None,
                },
                # Liquidity / impact proxy.
                "kyle_lambda_proxy": kyle_lambda,
                "kyle_lambda_bps_per_1m_usd": (
                    kyle_lambda * 1_000_000 * 10_000
                    if isinstance(kyle_lambda, (int, float))
                    else None
                ),
                "kyle_lambda_equation": "lambda = |slope(|delta log price| ~ dollar_volume)|",
                "kyle_lambda_scaled_equation": "bps per $1M = lambda * 1,000,000 * 10,000",
                "top10_imbalance": depth_table[1]["imbalance"] if len(depth_table) > 1 else None,
                "methodology": (
                    "Snapshot of the Binance spot L2 order book "
                    "(GET /api/v3/depth?symbol={SYMBOL}&limit={depth_levels}). "
                    "spread_bps = (best_ask - best_bid) / mid * 10000. "
                    "microprice = (best_bid*ask_size + best_ask*bid_size) / (bid_size + ask_size) — "
                    "the size-weighted mid. imbalance = (bid_size - ask_size)/(bid_size + ask_size) in [-1,1]. "
                    "Depth buckets sum per-side quantity/notional. Kyle's lambda is a local price-impact "
                    "proxy estimated from recent kline returns vs dollar volume (lower = more liquid). "
                    "Asset classes without an L2 provider are explicit_unavailable, never a synthetic ladder."
                ),
                "field_dictionary": _FIELD_DICTIONARY,
                "params": {
                    "depth_limit": depth_limit,
                    "depth_levels": depth_limit,
                    "interval": interval,
                    "kline_limit": kline_limit,
                },
                "next_actions": _NEXT_ACTIONS,
                "provider_notes": warnings,
            },
            sources=["binance"],
            warnings=warnings,
            metadata={
                "book_levels": len(rows),
                "depth_limit": depth_limit,
                "kyle_points": kyle_points,
                "latency_ms": None,
                "methodology": "binance_spot_l2_microstructure_v3",
            },
        )


def _normalize_depth_limit(raw: Any) -> int:
    try:
        requested = int(raw)
    except Exception:
        requested = 20
    allowed = [5, 10, 20, 50, 100, 500, 1000]
    for value in allowed:
        if requested <= value:
            return value
    return allowed[-1]


def _unavailable_microstructure(
    symbol: str,
    *,
    data_mode: str,
    status: str,
    reason: str,
    next_action: str,
) -> dict[str, Any]:
    """Honest empty payload — NO synthetic ladder is ever fabricated."""
    return {
        "status": status,
        "data_mode": data_mode,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "reason": reason,
        # Contract must-haves, all empty/None — never synthetic.
        "bids": [],
        "asks": [],
        "spread_bps": None,
        "microprice": None,
        "imbalance": None,
        "best_bid": None,
        "best_ask": None,
        "rows": [],
        "surface": [],
        "depth_table": [],
        "depth_ladder": [],
        "cards": {"symbol": symbol, "data_mode": data_mode},
        "next_actions": [
            {"id": "open_in_gp", "label": next_action},
            *_NEXT_ACTIONS,
        ],
        "methodology": (
            "Requires a live Binance spot L2 order-book depth feed. Only crypto symbols "
            "are supported; other asset classes are explicit_unavailable rather than synthetic."
        ),
        "field_dictionary": _FIELD_DICTIONARY,
    }


__all__ = ["MICROFunction"]
