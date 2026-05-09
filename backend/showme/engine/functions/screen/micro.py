"""MICRO — Market microstructure summary.

Per-symbol metrikler:
  - Bid/ask spread + spread_bps
  - Top-N levels cumulative depth (bid + ask)
  - Order book imbalance
  - Kyle's lambda (price impact per $ of net flow) — proxy hesabı
  - Effective spread vs quoted spread (last vs mid)

Yalnızca crypto (Binance order book) için çalışır; equity için L2 ücretli.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import numpy as np

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class MICROFunction(BaseFunction):
    code = "MICRO"
    name = "Market Microstructure"
    asset_classes = (AssetClass.CRYPTO, AssetClass.EQUITY)
    category = "screen"
    description = "Order-book depth, imbalance, spread and Kyle's lambda proxy."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_unavailable_microstructure(
                    "",
                    status="input_error",
                    reason="instrument required",
                    next_action="Select a crypto perpetual symbol such as BTCUSDT.",
                ),
                sources=["no_live_source"],
            )
        sym = instrument.symbol.upper()
        if instrument.asset_class != AssetClass.CRYPTO:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_unavailable_microstructure(
                    sym,
                    status="unsupported_asset",
                    reason="equity L2/order-book data is not available in the local provider set",
                    next_action="Use a Binance USDT perpetual symbol such as BTCUSDT, ETHUSDT, or SOLUSDT.",
                ),
                sources=["no_live_source"],
            )
        depth_limit = _normalize_depth_limit(params.get("depth_limit") or params.get("limit") or 50)
        interval = str(params.get("interval") or "1m")
        kline_limit = max(50, min(int(params.get("kline_limit", 200) or 200), 1000))
        timeout = float(params.get("timeout", 8) or 8)
        async with httpx.AsyncClient(timeout=timeout) as client:
            depth, klines = await asyncio.gather(
                client.get("https://fapi.binance.com/fapi/v1/depth",
                           params={"symbol": sym, "limit": depth_limit}),
                client.get("https://fapi.binance.com/fapi/v1/klines",
                           params={"symbol": sym, "interval": interval, "limit": kline_limit}),
                return_exceptions=True,
            )
        if isinstance(depth, Exception) or depth.status_code != 200:
            reason = str(depth) if isinstance(depth, Exception) else f"binance depth status {depth.status_code}"
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_unavailable_microstructure(
                    sym,
                    status="provider_unavailable",
                    reason=reason,
                    next_action="Retry with a Binance USDT perpetual pair or lower the depth limit.",
                ),
                sources=["no_live_source"],
            )
        d = depth.json()
        bids = [(float(p), float(q)) for p, q in (d.get("bids") or [])]
        asks = [(float(p), float(q)) for p, q in (d.get("asks") or [])]
        if not bids or not asks:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_unavailable_microstructure(
                    sym,
                    status="provider_unavailable",
                    reason="empty order book from Binance",
                    next_action="Retry with a liquid USDT perpetual symbol.",
                ),
                sources=["no_live_source"],
            )
        best_bid_p, _ = bids[0]
        best_ask_p, _ = asks[0]
        mid = (best_bid_p + best_ask_p) / 2
        spread = best_ask_p - best_bid_p
        spread_bps = (spread / mid) * 10_000 if mid else 0
        depth_levels = [n for n in [5, 10, 20, 50, 100] if n <= depth_limit]
        if depth_limit not in depth_levels:
            depth_levels.append(depth_limit)
        depth_table = []
        for n in depth_levels:
            bid_q = sum(q for _, q in bids[:n])
            ask_q = sum(q for _, q in asks[:n])
            bid_notional = sum(p * q for p, q in bids[:n])
            ask_notional = sum(p * q for p, q in asks[:n])
            imbalance = (bid_q - ask_q) / max(bid_q + ask_q, 1e-9)
            depth_table.append({
                "bucket": f"Top {n}",
                "levels": n,
                "bid_qty": bid_q,
                "ask_qty": ask_q,
                "bid_notional": bid_notional,
                "ask_notional": ask_notional,
                "imbalance": imbalance,
                "value": imbalance,
            })
        order_book = _order_book_ladder(bids, asks, mid=mid, levels=min(20, depth_limit))
        kyle_lambda = None
        kyle_points = 0
        kyle_warning = None
        if not isinstance(klines, Exception) and klines.status_code == 200:
            try:
                rows = klines.json() or []
                if rows:
                    closes = np.array([float(r[4]) for r in rows])
                    vols = np.array([float(r[5]) for r in rows])
                    rets = np.diff(np.log(closes))
                    abs_rets = np.abs(rets)
                    vol_dollar = vols[1:] * closes[1:]
                    if len(abs_rets) > 30 and vol_dollar.sum() > 0:
                        # Lambda is a local price-impact proxy: lower is more liquid.
                        beta = np.cov(abs_rets, vol_dollar)[0, 1] / max(np.var(vol_dollar), 1e-12)
                        kyle_lambda = abs(float(beta))
                        kyle_points = int(len(abs_rets))
            except Exception as exc:
                kyle_warning = str(exc)
        elif isinstance(klines, Exception):
            kyle_warning = str(klines)
        elif getattr(klines, "status_code", None) != 200:
            kyle_warning = f"binance klines status {klines.status_code}"
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "symbol": sym,
                "best_bid": best_bid_p,
                "best_ask": best_ask_p,
                "mid": mid,
                "spread": spread,
                "spread_bps": spread_bps,
                "surface": depth_table,
                "depth_table": depth_table,
                "order_book": order_book,
                "kyle_lambda_proxy": kyle_lambda,
                "kyle_lambda_bps_per_1m_usd": (
                    kyle_lambda * 1_000_000 * 10_000
                    if isinstance(kyle_lambda, (int, float))
                    else None
                ),
                "top10_imbalance": depth_table[1]["imbalance"] if len(depth_table) > 1 else None,
                "kyle_lambda_equation": "lambda = |slope(|delta log price| ~ dollar_volume)|",
                "kyle_lambda_scaled_equation": "bps per $1M = lambda * 1,000,000 * 10,000",
                "methodology": (
                    "Depth buckets sum Binance perpetual order-book quantity/notional on both sides. "
                    "Imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty). "
                    "Kyle lambda is a local price-impact proxy estimated from recent kline returns and dollar volume."
                ),
                "params": {"depth_limit": depth_limit, "interval": interval, "kline_limit": kline_limit},
                "provider_notes": [kyle_warning] if kyle_warning else [],
            },
            sources=["binance"],
            metadata={
                "book_levels": len(order_book),
                "depth_limit": depth_limit,
                "kyle_points": kyle_points,
                "methodology": "order_book_depth_and_kyle_lambda_proxy_v2",
            },
        )


def _normalize_depth_limit(raw: Any) -> int:
    try:
        requested = int(raw)
    except Exception:
        requested = 50
    allowed = [5, 10, 20, 50, 100, 500, 1000]
    for value in allowed:
        if requested <= value:
            return value
    return allowed[-1]


def _order_book_ladder(
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
    *,
    mid: float,
    levels: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    bid_cum_qty = 0.0
    ask_cum_qty = 0.0
    bid_cum_notional = 0.0
    ask_cum_notional = 0.0
    for idx, (price, qty) in enumerate(bids[:levels], start=1):
        notional = price * qty
        bid_cum_qty += qty
        bid_cum_notional += notional
        rows.append({
            "side": "bid",
            "level": idx,
            "price": price,
            "quantity": qty,
            "notional": notional,
            "cum_quantity": bid_cum_qty,
            "cum_notional": bid_cum_notional,
            "distance_bps": ((price - mid) / mid) * 10_000 if mid else None,
        })
    for idx, (price, qty) in enumerate(asks[:levels], start=1):
        notional = price * qty
        ask_cum_qty += qty
        ask_cum_notional += notional
        rows.append({
            "side": "ask",
            "level": idx,
            "price": price,
            "quantity": qty,
            "notional": notional,
            "cum_quantity": ask_cum_qty,
            "cum_notional": ask_cum_notional,
            "distance_bps": ((price - mid) / mid) * 10_000 if mid else None,
        })
    return rows


def _unavailable_microstructure(
    symbol: str,
    *,
    status: str,
    reason: str,
    next_action: str,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "status": status,
        "reason": reason,
        "rows": [],
        "surface": [],
        "depth_table": [],
        "order_book": [],
        "next_actions": [next_action],
        "methodology": "Requires live Binance futures order-book depth for crypto perpetuals.",
    }
