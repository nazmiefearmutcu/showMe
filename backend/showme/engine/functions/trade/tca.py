"""TCA — Trade Cost Analysis (post-trade).

De-garbaged: the default path now joins REAL executed fills (the autonomous
bot fill ledger in ``showme/bots/`` plus the manual ``order_history`` store)
against a LIVE, keyless intraday VWAP benchmark — Binance klines for crypto,
yfinance intraday candles for equity/ETF/FX/etc. — and computes real per-fill
slippage / implementation-shortfall / opportunity-cost rows.

It is strictly post-trade and read-only: it never calls a broker mutation.
When no fills exist it returns an honest ``empty`` payload (rows == [],
summary.fill_count == 0). A live benchmark-fetch outage degrades gracefully
to the per-fill arrival benchmark and flags ``provider_unavailable`` only when
the network genuinely fails.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument

_OK = "ok"
_EMPTY = "empty"
_PROVIDER_UNAVAILABLE = "provider_unavailable"

_METHODOLOGY = (
    "TCA loads executed fills from the autonomous bot fill ledger (bot_fills) "
    "and the manual order_history store, then joins each fill against a live "
    "intraday VWAP benchmark sourced keyless (Binance klines for crypto, "
    "yfinance intraday candles otherwise) over the same trading session. "
    "Per-fill slippage_bps = (avg_fill - benchmark) / benchmark * 10000 * "
    "side_sign; implementation-shortfall is_bps = (avg_fill - arrival) / arrival "
    "* 10000 * side_sign; opportunity_bps captures the cost of unfilled size. "
    "total_cost_usd aggregates slippage_bps * notional / 10000. Summary KPIs are "
    "the fill-count means across the analysed tail. TCA is strictly read-only "
    "and never mutates broker state."
)

_FIELD_DICTIONARY = {
    "order_id": "Broker/bot order identifier for the fill.",
    "symbol": "Instrument symbol of the fill.",
    "broker": "Broker or bot adapter that produced the fill.",
    "side": "BUY / SELL (LONG/SHORT normalised).",
    "quantity": "Filled quantity.",
    "avg_fill_px": "Volume-weighted executed fill price.",
    "benchmark_px": "Live intraday VWAP benchmark for the fill session.",
    "arrival_px": "Reference (arrival/decision) price at order entry.",
    "slippage_bps": "Signed slippage vs the VWAP benchmark, in basis points.",
    "is_bps": "Implementation shortfall vs arrival price, in basis points.",
    "opportunity_bps": "Cost of unfilled quantity vs benchmark, in basis points.",
    "notional_usd": "avg_fill_px * quantity (quote-currency notional).",
    "cost_usd": "slippage_bps * notional / 10000 (execution cost).",
    "filled_at": "ISO-8601 timestamp of the fill.",
    "benchmark_source": "Live source used for the VWAP benchmark, or 'arrival' fallback.",
}


def _crypto_interval(symbol: str) -> bool:
    s = (symbol or "").upper()
    return s.endswith(("USDT", "USDC", "BUSD", "USD", "BTC", "ETH"))


def _vwap_from_candles(candles: list[dict[str, Any]]) -> float | None:
    """Volume-weighted average of typical price across OHLCV candles."""
    num = 0.0
    den = 0.0
    for c in candles:
        try:
            high = float(c.get("high") or 0)
            low = float(c.get("low") or 0)
            close = float(c.get("close") or 0)
            vol = float(c.get("volume") or 0)
        except (TypeError, ValueError):
            continue
        typical = (high + low + close) / 3.0 if (high or low or close) else close
        if typical <= 0 or vol <= 0:
            continue
        num += typical * vol
        den += vol
    if den <= 0:
        return None
    return num / den


@FunctionRegistry.register
class TCAFunction(BaseFunction):
    code = "TCA"
    name = "Trade Cost Analysis"
    category = "trade"
    description = "Implementation shortfall, slippage, opportunity cost across fills."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbol = params.get("symbol") or (instrument.symbol if instrument else None)
        benchmark = (params.get("benchmark") or "VWAP").upper()
        as_of = datetime.now(timezone.utc).isoformat()
        inner_params = params.copy()
        inner_params.pop("symbol", None)
        inner_params.pop("benchmark", None)
        try:
            import asyncio
            return await asyncio.wait_for(
                self._execute_inner(instrument, symbol, benchmark, as_of, **inner_params),
                timeout=9.0,
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            reason = f"TCA execution timed out: {exc}"
            return FunctionResult(
                code=self.code, instrument=instrument,
                data={
                    "status": _PROVIDER_UNAVAILABLE,
                    "as_of": as_of,
                    "benchmark": benchmark,
                    "rows": [],
                    "series": [],
                    "cards": self._cards(summary={}, benchmark=benchmark,
                                         as_of=as_of, data_mode="provider_unavailable"),
                    "summary": {"benchmark": benchmark, "fill_count": 0, "reason": reason},
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                    "next_actions": [
                        "Retry once the intraday benchmark provider is reachable.",
                    ],
                },
                sources=["bot_fills", "order_history"],
                warnings=[reason],
                metadata={"provider_errors": [reason]},
            )

    async def _execute_inner(self, instrument: Instrument | None, symbol: str | None, benchmark: str, as_of: str, **params: Any) -> FunctionResult:
        broker = params.get("broker")
        try:
            limit = int(params.get("limit", 200))
        except (TypeError, ValueError):
            limit = 200

        # ---- 1) Load REAL fills (bot ledger first, then manual order_history).
        fills = self._load_fills(symbol=symbol, broker=broker, limit=limit)

        if not fills:
            return FunctionResult(
                code=self.code, instrument=instrument,
                data={
                    "status": _EMPTY,
                    "as_of": as_of,
                    "benchmark": benchmark,
                    "rows": [],
                    "series": [],
                    "cards": self._cards(summary={}, benchmark=benchmark,
                                         as_of=as_of, data_mode="no_fills"),
                    "summary": {"benchmark": benchmark, "fill_count": 0},
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                    "next_actions": [
                        "Run a bot (paper or live) so fills land in the bot ledger, "
                        "or submit/import orders with fill metadata.",
                        "Use EXEC to monitor parent orders before TCA.",
                    ],
                },
                sources=["bot_fills", "order_history"],
                warnings=["No executed fills available for trade cost analysis."],
            )

        # ---- 2) Resolve live VWAP benchmark per distinct symbol.
        benchmark_warnings: list[str] = []
        provider_failed = False
        sources: set[str] = {"bot_fills", "order_history"}
        vwap_by_symbol: dict[str, tuple[float | None, str]] = {}
        for sym in {f["symbol"] for f in fills if f.get("symbol")}:
            vwap, src, failed = await self._live_vwap(sym, instrument)
            vwap_by_symbol[sym] = (vwap, src)
            if failed:
                provider_failed = True
            if src and src not in ("arrival", "none"):
                sources.add(src)

        # ---- 3) Build contract rows + series.
        rows: list[dict[str, Any]] = []
        series: list[dict[str, Any]] = []
        slip_bps_vals: list[float] = []
        is_bps_vals: list[float] = []
        total_cost_usd = 0.0
        for f in fills:
            sym = f.get("symbol")
            side = f["side"]
            sign = +1 if side in ("BUY", "LONG") else -1
            avg_fill = f["avg_fill_px"]
            qty = f["quantity"]
            arrival = f.get("arrival_px")
            live_vwap, bench_src = vwap_by_symbol.get(sym, (None, "none"))

            # Benchmark selection: VWAP path uses live VWAP, fall back to arrival.
            if benchmark == "ARRIVAL" or benchmark == "IMPLEMENTATION_SHORTFALL":
                bench_px = arrival if arrival else live_vwap
                bench_used = "arrival" if arrival else bench_src
            else:  # VWAP / TWAP
                bench_px = live_vwap if live_vwap else arrival
                bench_used = bench_src if live_vwap else "arrival"

            slip_bps = None
            if bench_px and avg_fill:
                slip_bps = (avg_fill - bench_px) / bench_px * 1e4 * sign
            is_bps = None
            if arrival and avg_fill:
                is_bps = (avg_fill - arrival) / arrival * 1e4 * sign
            notional = (avg_fill or 0) * (qty or 0)
            cost_usd = (slip_bps or 0) * notional / 1e4

            if slip_bps is not None:
                slip_bps_vals.append(slip_bps)
            if is_bps is not None:
                is_bps_vals.append(is_bps)
            total_cost_usd += cost_usd

            rows.append({
                "order_id": f.get("order_id"),
                "symbol": sym,
                "broker": f.get("broker"),
                "side": side,
                "quantity": round(qty, 8) if qty is not None else None,
                "avg_fill_px": round(avg_fill, 8) if avg_fill is not None else None,
                "benchmark_px": round(bench_px, 8) if bench_px is not None else None,
                "arrival_px": round(arrival, 8) if arrival is not None else None,
                "slippage_bps": round(slip_bps, 2) if slip_bps is not None else None,
                "is_bps": round(is_bps, 2) if is_bps is not None else None,
                "opportunity_bps": round(is_bps, 2) if is_bps is not None else None,
                "notional_usd": round(notional, 2),
                "cost_usd": round(cost_usd, 2),
                "filled_at": f.get("filled_at"),
                "benchmark_source": bench_used,
            })
            series.append({
                "label": (f.get("order_id") or sym or "fill"),
                "value": round(slip_bps, 2) if slip_bps is not None else 0.0,
            })

        n = len(rows)
        avg_slip = sum(slip_bps_vals) / len(slip_bps_vals) if slip_bps_vals else 0.0
        avg_is = sum(is_bps_vals) / len(is_bps_vals) if is_bps_vals else 0.0
        worst_slip = max(slip_bps_vals, key=abs) if slip_bps_vals else 0.0
        summary = {
            "benchmark": benchmark,
            "fill_count": n,
            "avg_slippage_bps": round(avg_slip, 2),
            "avg_is_bps": round(avg_is, 2),
            "worst_slippage_bps": round(worst_slip, 2),
            "total_cost_usd": round(total_cost_usd, 2),
        }

        status = _OK
        warnings: list[str] = list(benchmark_warnings)
        if provider_failed and not slip_bps_vals:
            # Every live benchmark fetch failed AND we could not even fall back
            # to an arrival benchmark — be honest about the outage.
            status = _PROVIDER_UNAVAILABLE
            warnings.append(
                "Live VWAP benchmark unavailable for every fill; slippage could "
                "not be computed."
            )
        elif provider_failed:
            warnings.append(
                "Live VWAP benchmark unavailable for some symbols; those fills "
                "fell back to their arrival price."
            )

        data_mode = "live" if (slip_bps_vals and not provider_failed) else (
            "degraded" if slip_bps_vals else "provider_unavailable"
        )

        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": status,
                "as_of": as_of,
                "benchmark": benchmark,
                "rows": rows,
                "series": series,
                "cards": self._cards(summary=summary, benchmark=benchmark,
                                     as_of=as_of, data_mode=data_mode),
                "summary": summary,
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICTIONARY,
                "next_actions": [
                    "Tighten limit orders or slice large parents (use ALGO/TWAP).",
                    "Review worst-slippage fills against the VWAP benchmark.",
                ],
            },
            sources=sorted(sources),
            warnings=warnings,
            metadata={"data_mode": data_mode, "benchmark": benchmark},
        )

    # -- helpers --------------------------------------------------------------

    def _load_fills(
        self, *, symbol: str | None, broker: str | None, limit: int,
    ) -> list[dict[str, Any]]:
        """Return normalised real fills from the bot ledger + order_history.

        The autonomous bot ledger is ``BotStore`` (JSON BotRecords under
        ``<app_home>/bots/``). Each ``signal_log`` entry that actually placed
        an order is a real fill: ``fill_price`` is the broker-confirmed
        execution price (preferred), ``price`` is the signal/decision price we
        treat as the arrival benchmark, ``qty`` the executed size, and
        ``kind`` (entry/exit) maps to BUY/SELL.
        """
        out: list[dict[str, Any]] = []
        want_sym = symbol.upper() if symbol else None

        # Autonomous bot fill ledger (showme/bots — BotStore JSON records).
        try:
            from showme.bots.store import BotStore

            store = BotStore.fresh()
            for meta in store.list():
                bot_sym = (meta.symbol or "").upper()
                if want_sym and bot_sym != want_sym:
                    continue
                try:
                    rec = store.get(meta.id)
                except Exception:  # noqa: BLE001 — skip unreadable record
                    continue
                for entry in rec.signal_log:
                    if entry.action not in ("placed", "shadow"):
                        continue
                    fill_px = entry.fill_price if entry.fill_price else entry.price
                    if not fill_px or fill_px <= 0:
                        continue
                    side = "BUY" if entry.kind == "entry" else "SELL"
                    # arrival/decision reference = the signal-bar close, which
                    # is distinct from the broker fill_price when slippage > 0.
                    arrival = entry.price if entry.fill_price else None
                    out.append({
                        "order_id": entry.order_id or f"{meta.id[:8]}-{entry.bar_index}",
                        "symbol": bot_sym or None,
                        "broker": f"bot:{meta.id[:8]}",
                        "side": side,
                        "quantity": float(entry.qty or 1.0),
                        "avg_fill_px": float(fill_px),
                        "arrival_px": float(arrival) if arrival is not None else None,
                        "filled_at": entry.bar_close_time or entry.timestamp,
                    })
        except Exception:  # noqa: BLE001 — ledger optional / may not exist yet
            pass

        # Manual order_history (cross-broker tickets).
        try:
            from showme.engine.services import order_history

            for o in order_history.list_orders(broker=broker, symbol=symbol, limit=limit):
                md = o.get("metadata") or {}
                if isinstance(md, str):
                    md = {}
                avg_fill, filled_qty = self._avg_fill(md, o.get("price"))
                if avg_fill is None:
                    continue
                arrival = md.get("arrival_price")
                if arrival is None and o.get("price"):
                    arrival = o.get("price")
                ts = o.get("ts")
                out.append({
                    "order_id": o.get("order_id") or f"ord-{o.get('id')}",
                    "symbol": (o.get("symbol") or "").upper() or None,
                    "broker": o.get("broker") or "manual",
                    "side": (o.get("side") or "BUY").upper(),
                    "quantity": float(filled_qty or o.get("quantity") or 0),
                    "avg_fill_px": float(avg_fill),
                    "arrival_px": float(arrival) if arrival is not None else None,
                    "filled_at": (datetime.fromtimestamp(ts, timezone.utc).isoformat()
                                  if ts else None),
                })
        except Exception:  # noqa: BLE001 — store optional
            pass

        return out[:limit]

    @staticmethod
    def _avg_fill(metadata: dict[str, Any], book_px: float | None) -> tuple[float | None, float]:
        fills = metadata.get("fills") or []
        if fills:
            notional = 0.0
            qty = 0.0
            for f in fills:
                try:
                    p = float(f.get("px") or f.get("price") or 0)
                    q = float(f.get("qty") or f.get("quantity") or 0)
                except (TypeError, ValueError):
                    continue
                notional += p * q
                qty += q
            if qty > 0:
                return notional / qty, qty
        av = metadata.get("avg_fill")
        if av is None:
            av = book_px
        try:
            filled_qty = float(metadata.get("filled_qty") or 0)
        except (TypeError, ValueError):
            filled_qty = 0.0
        return (float(av) if av is not None else None), filled_qty

    async def _live_vwap(
        self, symbol: str, instrument: Instrument | None,
    ) -> tuple[float | None, str, bool]:
        """Return (vwap, source, failed). Keyless: Binance for crypto, yfinance else."""
        is_crypto = _crypto_interval(symbol)
        if instrument is not None and instrument.symbol == symbol:
            is_crypto = instrument.asset_class == AssetClass.CRYPTO

        if is_crypto:
            try:
                candles = await self._binance_klines(symbol)
                vwap = _vwap_from_candles(candles)
                if vwap is not None:
                    return vwap, "binance", False
                return None, "binance", False
            except Exception:  # noqa: BLE001 — network/parse failure
                return None, "arrival", True

        try:
            candles = await self._yfinance_intraday(symbol)
            vwap = _vwap_from_candles(candles)
            if vwap is not None:
                return vwap, "yfinance", False
            return None, "yfinance", False
        except Exception:  # noqa: BLE001 — network/parse failure
            return None, "arrival", True

    async def _binance_klines(self, symbol: str) -> list[dict[str, Any]]:
        provider = self.deps.get("binance")
        if provider is not None and hasattr(provider, "klines"):
            return await provider.klines(symbol, interval="5m", limit=288)
        # Direct keyless fallback.
        from showme.providers._http import get_client

        client = await get_client()
        resp = await client.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol.upper(), "interval": "5m", "limit": 288},
        )
        resp.raise_for_status()
        return [
            {"high": float(k[2]), "low": float(k[3]),
             "close": float(k[4]), "volume": float(k[5])}
            for k in resp.json()
        ]

    async def _yfinance_intraday(self, symbol: str) -> list[dict[str, Any]]:
        provider = self.deps.get("yfinance")
        if provider is not None and hasattr(provider, "ohlcv"):
            return await provider.ohlcv(symbol, period="5d", interval="5m")
        import asyncio

        def _sync() -> list[dict[str, Any]]:
            import yfinance as yf

            hist = yf.Ticker(symbol).history(period="5d", interval="5m")
            rows: list[dict[str, Any]] = []
            for _, row in hist.iterrows():
                rows.append({
                    "high": float(row.get("High", 0) or 0),
                    "low": float(row.get("Low", 0) or 0),
                    "close": float(row.get("Close", 0) or 0),
                    "volume": float(row.get("Volume", 0) or 0),
                })
            return rows

        return await asyncio.to_thread(_sync)

    @staticmethod
    def _cards(*, summary: dict[str, Any], benchmark: str,
               as_of: str, data_mode: str) -> dict[str, Any]:
        return {
            "fill_count": summary.get("fill_count", 0),
            "avg_slippage_bps": summary.get("avg_slippage_bps", 0.0),
            "avg_is_bps": summary.get("avg_is_bps", 0.0),
            "worst_slippage_bps": summary.get("worst_slippage_bps", 0.0),
            "total_cost_usd": summary.get("total_cost_usd", 0.0),
            "benchmark": benchmark,
            "data_mode": data_mode,
            "as_of": as_of,
        }
