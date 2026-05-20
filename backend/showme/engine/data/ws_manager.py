"""WebSocket Stream Manager (per plan §4.2).

Single async manager that maintains multiple sharded connections to
wss://fstream.binance.com/stream. Subscribes to:
  - <symbol>@kline_<tf> for all (symbol, tf) pairs
  - <symbol>@aggTrade for CVD
  - <symbol>@openInterest for OI tracking
  - !markPrice@arr@1s for funding rate (single global stream, all symbols)
  - !forceOrder@arr for liquidations (single global stream)

Auto-reconnect with exponential backoff and gap-fill via REST on reconnect.
Writes to MarketCache (live) and MarketStore (closed candles only).
"""

import asyncio
import json
import time
from typing import Any, Optional

import websockets

from showme.engine.api.binance_client import BinanceClient
from showme.engine.data.market_cache import MarketCache
from showme.engine.data.market_store import MarketStore
from showme.engine.utils.logger import get_logger

logger = get_logger("data.ws_manager")

WS_BASE = "wss://fstream.binance.com/stream"
MAX_STREAMS_PER_CONN = 1024
TF_TO_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "6h": 21_600_000, "8h": 28_800_000, "12h": 43_200_000, "1d": 86_400_000,
}


class WSManager:
    """Async manager for combined-stream WebSocket connections."""

    def __init__(
        self,
        symbols: list[str],
        timeframes: list[str],
        cache: MarketCache,
        store: Optional[MarketStore] = None,
        rest_client: Optional[BinanceClient] = None,
        max_streams_per_conn: int = MAX_STREAMS_PER_CONN,
    ) -> None:
        self.symbols = list(symbols)
        self.timeframes = list(timeframes)
        self.cache = cache
        self.store = store
        self.rest_client = rest_client
        self.max_streams_per_conn = max_streams_per_conn

        self.shards = self._build_shards()
        self.last_kline_ms: dict[tuple[str, str], int] = {}
        self.health = {
            "shards": len(self.shards),
            "connected": 0,
            "messages": 0,
            "reconnects": 0,
            "gap_fills": 0,
            "started_at": time.time(),
            "last_msg_ts": 0,
        }
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    def _build_shards(self) -> list[list[str]]:
        all_streams: list[str] = []
        for sym in self.symbols:
            sl = sym.lower()
            for tf in self.timeframes:
                all_streams.append(f"{sl}@kline_{tf}")
            all_streams.append(f"{sl}@aggTrade")
            all_streams.append(f"{sl}@openInterest")
        # Global single subscriptions
        all_streams.append("!markPrice@arr@1s")
        all_streams.append("!forceOrder@arr")
        return [
            all_streams[i : i + self.max_streams_per_conn]
            for i in range(0, len(all_streams), self.max_streams_per_conn)
        ]

    async def run(self) -> None:
        """Launch all shards concurrently. Returns when stop() is called."""
        if not self.shards:
            logger.warning("WSManager: no shards to run")
            return
        self._tasks = [
            asyncio.create_task(self._run_shard(streams, idx))
            for idx, streams in enumerate(self.shards)
        ]
        try:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        except Exception as e:
            logger.error("WSManager run error: %s", e)

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run_shard(self, streams: list[str], shard_id: int) -> None:
        url = f"{WS_BASE}?streams={'/'.join(streams)}"
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    url, ping_interval=180, ping_timeout=600,
                    max_size=2**24, close_timeout=10,
                ) as ws:
                    self.health["connected"] += 1
                    logger.info("WS shard #%s connected (%s streams)", shard_id, len(streams))
                    backoff = 1.0
                    await self._gap_fill_on_reconnect(streams)
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        await self._dispatch(msg)
                        self.health["messages"] += 1
                        self.health["last_msg_ts"] = int(time.time() * 1000)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.health["reconnects"] += 1
                logger.warning(
                    f"WS shard #{shard_id} disconnected: {e}; backing off {backoff:.1f}s"
                )
                try:
                    await asyncio.sleep(min(backoff, 60))
                except asyncio.CancelledError:
                    break
                backoff *= 2

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        stream = msg.get("stream", "")
        data = msg.get("data", {})
        if not stream:
            return

        if "@kline_" in stream:
            self._handle_kline(data)
        elif "@aggTrade" in stream:
            self._handle_agg_trade(data)
        elif stream == "!markPrice@arr@1s":
            self._handle_mark_prices(data)
        elif stream == "!forceOrder@arr":
            self._handle_liquidation(data)
        elif "@openInterest" in stream:
            # Note: Binance does not expose openInterest as a websocket stream.
            # Some users access via futures_open_interest_hist (REST). We keep
            # the dispatch path for future compatibility.
            self._handle_oi(data)

    # ── handlers ───────────────────────────────────────────

    def _handle_kline(self, data: dict[str, Any]) -> None:
        try:
            k = data["k"]
            sym = data["s"]
            tf = k["i"]
            row = {
                "symbol": sym, "timeframe": tf,
                "open_time": int(k["t"]),
                "open": float(k["o"]), "high": float(k["h"]),
                "low": float(k["l"]), "close": float(k["c"]),
                "volume": float(k["v"]), "quote_volume": float(k["q"]),
                "trades": int(k.get("n", 0) or 0),
                "taker_buy_base": float(k["V"]), "taker_buy_quote": float(k["Q"]),
                "is_closed": bool(k["x"]),
            }
            self.cache.update_candle(sym, tf, row)
            if k["x"] and self.store is not None:
                try:
                    self.store.write_candle(row)
                except Exception as e:
                    logger.debug("store write_candle failed: %s", e)
                self.last_kline_ms[(sym, tf)] = int(k["t"])
        except Exception as e:
            logger.debug("_handle_kline parse error: %s", e)

    def _handle_agg_trade(self, data: dict[str, Any]) -> None:
        try:
            trade = {
                "symbol": data["s"],
                "trade_time": int(data["T"]),
                "price": float(data["p"]),
                "quantity": float(data["q"]),
                "is_buyer_maker": bool(data["m"]),
                "agg_trade_id": int(data["a"]),
            }
            self.cache.update_agg_trade(trade["symbol"], trade)
        except Exception as e:
            logger.debug("_handle_agg_trade parse error: %s", e)

    def _handle_mark_prices(self, data: Any) -> None:
        """!markPrice@arr@1s sends a list of dicts, one per symbol."""
        if not isinstance(data, list):
            return
        for entry in data:
            try:
                sym = entry["s"]
                rate = float(entry.get("r", 0))
                mark = float(entry.get("p", 0))
                t = int(entry.get("E", time.time() * 1000))
                self.cache.update_funding(sym, rate, mark, t)
            except Exception:
                continue

    def _handle_liquidation(self, data: dict[str, Any]) -> None:
        """!forceOrder@arr sends one liquidation event."""
        try:
            o = data.get("o", {})
            sym = o["s"]
            liq = {
                "liq_time": int(o["T"]),
                "side": o["S"],
                "quantity": float(o["q"]),
                "price": float(o.get("ap", o.get("p", 0))),
                "order_type": o.get("o", "MARKET"),
            }
            self.cache.update_liquidation(sym, liq)
            if self.store is not None:
                try:
                    self.store.write_liquidation(
                        sym, liq["liq_time"], liq["side"],
                        liq["quantity"], liq["price"], liq["order_type"],
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.debug("_handle_liquidation parse error: %s", e)

    def _handle_oi(self, data: dict[str, Any]) -> None:
        try:
            sym = data.get("s") or data.get("symbol")
            oi = float(data.get("o", data.get("openInterest", 0)))
            oi_value = float(data.get("oV", data.get("openInterestValue", 0)))
            t = int(data.get("E", time.time() * 1000))
            if sym:
                self.cache.update_oi(sym, oi, oi_value, t)
        except Exception:
            pass

    # ── gap-fill ───────────────────────────────────────────

    async def _gap_fill_on_reconnect(self, streams: list[str]) -> None:
        """If we have last_kline_ms and reconnect happens later, REST-fill missing candles."""
        if self.rest_client is None or self.store is None:
            return
        now_ms = int(time.time() * 1000)
        for stream in streams:
            if "@kline_" not in stream:
                continue
            sym = stream.split("@")[0].upper()
            tf = stream.split("@kline_")[1]
            last_ms = self.last_kline_ms.get((sym, tf))
            if last_ms is None:
                continue
            tf_ms = TF_TO_MS.get(tf, 0)
            if tf_ms == 0:
                continue
            missing = (now_ms - last_ms) // tf_ms
            if missing <= 1:
                continue
            try:
                klines = self.rest_client.get_klines(symbol=sym, interval=tf, limit=min(int(missing) + 5, 1000))
                if not klines:
                    continue
                rows = []
                for k in klines:
                    rows.append({
                        "symbol": sym, "timeframe": tf,
                        "open_time": int(k[0]),
                        "open": float(k[1]), "high": float(k[2]),
                        "low": float(k[3]), "close": float(k[4]),
                        "volume": float(k[5]), "quote_volume": float(k[7]),
                        "trades": int(k[8]),
                        "taker_buy_base": float(k[9]),
                        "taker_buy_quote": float(k[10]),
                        "is_closed": True,
                    })
                for r in rows:
                    self.cache.update_candle(sym, tf, r)
                    self.store.write_candle(r)
                self.health["gap_fills"] += 1
                logger.info("Gap-filled %s candles for %s/%s", len(rows), sym, tf)
            except Exception as e:
                logger.warning("Gap-fill failed for %s/%s: %s", sym, tf, e)

    def get_health(self) -> dict[str, Any]:
        h = dict(self.health)
        h["uptime_sec"] = int(time.time() - h["started_at"])
        return h
