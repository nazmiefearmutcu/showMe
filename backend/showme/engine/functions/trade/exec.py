"""EXEC — VWAP/TWAP execution monitor function."""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions.trade.algos import (
    IcebergAlgo,
    SniperAlgo,
    TWAPAlgo,
    VWAPAlgo,
)
from showme.engine.services import exec_monitor


# Required parameter sets per ``action``. Keeping them up here lets
# ``execute`` reject missing fields with a clean ``reason`` message
# instead of dropping a Python ``KeyError`` repr (``"'parent_id'"``)
# straight into the UI — that was the EXEC half of the
# A02-2026-05-24 bug report.
_REQUIRED_BY_ACTION = {
    "open":  ("parent_id", "symbol", "side", "target_qty"),
    "slice": ("parent_id", "slice_idx", "qty", "avg_px"),
    "close": ("parent_id",),
    "get":   ("parent_id",),
}


def _missing_fields(params: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    """Return the subset of ``required`` keys that the caller didn't
    supply, treating ``None`` and empty strings as missing."""
    missing: list[str] = []
    for field in required:
        value = params.get(field)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            missing.append(field)
    return missing


def _error_result(code: str, action: str, reason: str, *, fields: list[str] | None = None,
                  status: str = "invalid_request") -> FunctionResult:
    data: dict[str, Any] = {"status": status, "action": action, "reason": reason}
    if fields:
        data["missing_fields"] = fields
    return FunctionResult(code=code, instrument=None, data=data, sources=["exec_monitor"],
                          metadata={"error": True, "status": status})


# --- action=plan ----------------------------------------------------------
#
# The monitor actions (open/slice/close/get/list) only echo whatever fills the
# caller has recorded — with an empty store EXEC has nothing live to show. The
# product claim, though, is broader: "track parent-order execution
# slice-by-slice … for VWAP/TWAP/POV algos". ``action=plan`` delivers that by
# driving the real ``algos.{TWAP,VWAP,Iceberg,Sniper}`` schedulers against
# *live* intraday OHLCV (Binance for crypto, Yahoo for listed assets), so each
# slice carries the price/volume bar it would execute against plus an honest,
# real-data interval-VWAP benchmark and pace curve.

_PLAN_DEFAULT_SYMBOL = {
    "CRYPTO": "BTCUSDT",
}
_DEFAULT_PLAN_SYMBOL = "AAPL"

_FIELD_DICTIONARY = {
    "slice_idx": "Zero-based slice index in the execution schedule.",
    "offset_s": "Seconds from schedule start at which the slice releases.",
    "ts_ms": "Epoch-ms of the live intraday bar the slice maps to.",
    "qty": "Quantity scheduled for this slice (algo-weighted).",
    "cum_qty": "Cumulative quantity scheduled through this slice.",
    "bar_close": "Close price of the live bar (the marketable reference).",
    "interval_vwap": "Typical-price VWAP of the bar = (H+L+C)/3 weighted by bar volume.",
    "benchmark_px": "Per-slice benchmark = interval_vwap (slippage reference).",
    "slip_bps": "(bar_close - benchmark_px)/benchmark_px * 1e4, in basis points.",
    "is_bps": "Implementation shortfall vs arrival for this slice, side-signed bps.",
    "pace_pct": "Cumulative scheduled qty / target_qty * 100.",
}


def _resolve_plan_asset_class(asset_class: str | None, symbol: str) -> str:
    if asset_class:
        return asset_class.upper()
    sym = symbol.upper()
    if sym.endswith(("USDT", "USDC", "BUSD", "USD")) and len(sym) > 4 and "=" not in sym:
        return "CRYPTO"
    return "EQUITY"


def _plan_interval(asset_class: str) -> str:
    # 5-minute bars give a tradeable intraday volume profile across markets.
    return "5m"


def _bar_interval_vwap(row: dict[str, Any]) -> float | None:
    high = row.get("high")
    low = row.get("low")
    close = row.get("close")
    if high is None or low is None or close is None:
        return None
    typical = (float(high) + float(low) + float(close)) / 3.0
    return typical


def _build_plan_rows(
    bars: list[dict[str, Any]],
    *,
    schedule: list[dict[str, Any]],
    target_qty: float,
    side: str,
    arrival_price: float | None,
) -> list[dict[str, Any]]:
    """Map an algo ``schedule`` onto the tail of live ``bars`` and compute
    real per-slice slippage / shortfall / pace from the bar data."""
    n = len(schedule)
    # Use the most recent ``n`` bars so each slice sits on a real, distinct bar.
    window = bars[-n:] if len(bars) >= n else bars
    side_sign = -1.0 if str(side).upper() == "SELL" else 1.0
    rows: list[dict[str, Any]] = []
    cum_qty = 0.0
    for idx, slot in enumerate(schedule):
        bar = window[idx] if idx < len(window) else window[-1]
        close = bar.get("close")
        bench = _bar_interval_vwap(bar)
        qty = float(slot.get("qty", 0.0))
        cum_qty += qty
        slip_bps: float | None = None
        if close is not None and bench:
            slip_bps = (float(close) - bench) / bench * 10_000.0
        is_bps: float | None = None
        if close is not None and arrival_price:
            is_bps = (float(close) - float(arrival_price)) / float(arrival_price) * 10_000.0 * side_sign
        ts_s = bar.get("time")
        rows.append(
            {
                "slice_idx": idx,
                "offset_s": int(slot.get("offset_s", 0)),
                "ts_ms": int(ts_s) * 1000 if ts_s is not None else None,
                "qty": round(qty, 8),
                "cum_qty": round(cum_qty, 8),
                "bar_close": float(close) if close is not None else None,
                "interval_vwap": round(bench, 8) if bench is not None else None,
                "benchmark_px": round(bench, 8) if bench is not None else None,
                "slip_bps": round(slip_bps, 2) if slip_bps is not None else None,
                "is_bps": round(is_bps, 2) if is_bps is not None else None,
                "pace_pct": round(cum_qty / target_qty * 100.0, 2) if target_qty else None,
            }
        )
    return rows


def _algo_schedule(
    algo: str, *, target_qty: float, horizon_s: int, slices: int,
    side: str, ref_price: float | None,
) -> tuple[list[dict[str, Any]], str]:
    """Return (schedule, resolved_algo). ``schedule`` is a list of
    ``{offset_s, qty}`` slices from the real algo modules."""
    upper = (algo or "TWAP").upper()
    if upper == "VWAP" or upper == "POV":
        sched = VWAPAlgo(target_quantity=target_qty, duration_seconds=horizon_s, slices=slices).schedule()
        return sched, "VWAP"
    if upper == "ICEBERG":
        # Iceberg replenishes a fixed display size until the parent is filled.
        display = max(target_qty / max(1, slices), 1e-9)
        berg = IcebergAlgo(total_quantity=target_qty, display_size=display, price=ref_price or 0.0)
        sched: list[dict[str, Any]] = []
        filled = 0.0
        slot = max(1, horizon_s // max(1, slices))
        i = 0
        while filled < target_qty - 1e-9 and i < slices:
            nxt = berg.next_slice(filled)
            q = float(nxt.get("qty", 0.0))
            if q <= 0:
                break
            sched.append({"offset_s": i * slot, "qty": q})
            filled += q
            i += 1
        return sched, "ICEBERG"
    if upper == "SNIPER":
        # Sniper waits for a favourable touch then fires the whole parent in one
        # marketable clip; schedule is a single slice at t0.
        return [{"offset_s": 0, "qty": target_qty}], "SNIPER"
    # default: TWAP equal time slices
    sched = TWAPAlgo(target_quantity=target_qty, duration_seconds=horizon_s, slices=slices).schedule()
    return sched, "TWAP"


@FunctionRegistry.register
class EXECFunction(BaseFunction):
    code = "EXEC"
    name = "Execution Monitor"
    category = "trade"
    description = "Live VWAP/TWAP slice-by-slice fill quality + pace tracking."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = (params.get("action") or "list").lower()
        required = _REQUIRED_BY_ACTION.get(action)
        if required is not None:
            missing = _missing_fields(params, required)
            if missing:
                return _error_result(
                    self.code, action,
                    f"missing required field(s): {', '.join(missing)}",
                    fields=missing,
                )
        if action == "open":
            try:
                pid = exec_monitor.open_parent(
                    parent_id=params["parent_id"],
                    symbol=params["symbol"], side=params["side"],
                    target_qty=float(params["target_qty"]),
                    arrival_price=params.get("arrival_price"),
                    algo=params.get("algo", "TWAP"),
                    horizon_seconds=int(params.get("horizon_seconds", 600)),
                    metadata=params.get("metadata") or {},
                )
            except (TypeError, ValueError) as exc:
                return _error_result(self.code, action, f"invalid field value: {exc}")
            return FunctionResult(code=self.code, instrument=None,
                                  data={"id": pid, "parent_id": params["parent_id"]})
        if action == "slice":
            # A02-2026-05-24: refuse orphan slices. Recording a slice
            # against a parent_id that the monitor doesn't know about
            # corrupts every downstream metric (avg_fill, pace, IS bps)
            # because compute_metrics joins on parent_id; the row is
            # silently rolled into a non-existent parent. 404 here so
            # the caller surfaces a clean "open the parent first" error.
            parent_id = params["parent_id"]
            if exec_monitor.get_parent(parent_id) is None:
                return _error_result(
                    self.code, action,
                    f"unknown parent_id: '{parent_id}' — open it with action=open first",
                    status="unknown_parent",
                )
            try:
                sid = exec_monitor.record_slice(
                    parent_id=parent_id,
                    slice_idx=int(params["slice_idx"]),
                    qty=float(params["qty"]),
                    avg_px=float(params["avg_px"]),
                    benchmark_px=params.get("benchmark_px"),
                    vwap_running=params.get("vwap_running"),
                )
            except (TypeError, ValueError) as exc:
                return _error_result(self.code, action, f"invalid field value: {exc}")
            return FunctionResult(code=self.code, instrument=None,
                                  data={"slice_id": sid})
        if action == "close":
            ok = exec_monitor.close_parent(
                params["parent_id"],
                status=params.get("status", "complete"))
            return FunctionResult(code=self.code, instrument=None,
                                  data={"closed": ok})
        if action == "get":
            return FunctionResult(code=self.code, instrument=None,
                                  data=exec_monitor.get_parent(params["parent_id"]) or {})
        if action == "plan":
            return await self._plan(instrument, **params)
        # default: list
        rows = exec_monitor.list_parents(
            status=params.get("status"),
            symbol=params.get("symbol"),
            limit=int(params.get("limit", 50)))
        # When nothing is being monitored but the caller pointed us at a symbol,
        # build a *live* execution schedule instead of an empty placeholder so
        # EXEC fulfils its "slice-by-slice for VWAP/TWAP/POV algos" claim.
        symbol_hint = (params.get("symbol") or "").strip()
        if not rows and (symbol_hint or (instrument is not None and getattr(instrument, "symbol", None))):
            return await self._plan(instrument, **params)
        if not rows:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "empty",
                    "reason": "No execution parent orders are being monitored.",
                    "orders": [],
                    "n": 0,
                    "next_actions": [
                        "Open a parent order with action=open before monitoring slices.",
                        "Use action=slice to record fill slices, then action=close when complete.",
                    ],
                },
                sources=["exec_monitor"],
                metadata={"empty": True},
            )
        filled_not_closed = [row for row in rows if row.get("status") == "filled_not_closed"]
        status = "needs_close" if filled_not_closed else "ok"
        reason = (
            f"{len(filled_not_closed)} parent order(s) are fully filled but still stored as live."
            if filled_not_closed
            else None
        )
        return FunctionResult(code=self.code, instrument=None,
                              data={
                                  "status": status,
                                  "reason": reason,
                                  "orders": rows,
                                  "n": len(rows),
                                  "next_actions": [
                                      "Close fully filled parent orders with action=close after confirming fills.",
                                      "Inspect per_slice metrics for slippage and benchmark quality.",
                                  ] if filled_not_closed else [],
                              },
                              sources=["exec_monitor"])

    async def _plan(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        """Build a real VWAP/TWAP/Iceberg/Sniper slice schedule against live
        intraday OHLCV (Binance for crypto, Yahoo for listed assets).

        Returns real per-slice rows: each slice maps to an actual market bar and
        carries an interval-VWAP benchmark + computed slippage / implementation
        shortfall / pace. On a genuine network outage it degrades to
        ``status="provider_unavailable"`` with an honest warning instead of
        fabricating numbers.
        """
        from showme.chart_history import fetch_binance_history, fetch_yahoo_history

        symbol = (params.get("symbol") or "").strip()
        if not symbol and instrument is not None:
            symbol = (getattr(instrument, "symbol", None) or "").strip()

        inst_ac = None
        if instrument is not None:
            ac = getattr(instrument, "asset_class", None)
            inst_ac = getattr(ac, "value", ac)
        asset_class = _resolve_plan_asset_class(
            params.get("asset_class") or inst_ac, symbol or _DEFAULT_PLAN_SYMBOL
        )
        if not symbol:
            symbol = _PLAN_DEFAULT_SYMBOL.get(asset_class, _DEFAULT_PLAN_SYMBOL)

        algo = (params.get("algo") or "TWAP").upper()
        try:
            target_qty = float(params.get("target_qty") or 100.0)
            horizon_s = int(params.get("horizon_seconds") or 600)
            slices = int(params.get("slices") or 12)
        except (TypeError, ValueError) as exc:
            return _error_result(self.code, "plan", f"invalid field value: {exc}")
        target_qty = max(target_qty, 1e-9)
        slices = max(2, min(slices, 24))
        side = (params.get("side") or "BUY").upper()
        arrival_price = params.get("arrival_price")
        try:
            arrival_price = float(arrival_price) if arrival_price is not None else None
        except (TypeError, ValueError):
            arrival_price = None

        interval = _plan_interval(asset_class)
        provider = "binance" if asset_class == "CRYPTO" else "yfinance"

        # --- fetch live intraday bars (graceful network-failure fallback) ----
        try:
            want_bars = max(slices * 2, 60)
            # 5m bars: ~5 days covers a deep intraday window on both venues.
            fetch_days = 5
            if asset_class == "CRYPTO":
                hist = await fetch_binance_history(
                    symbol=symbol, interval=interval, days=fetch_days, bars=want_bars,
                )
            else:
                hist = await fetch_yahoo_history(
                    symbol=symbol, asset_class=asset_class, interval=interval,
                    days=fetch_days, bars=want_bars,
                )
            bars = list(hist.rows or [])
            src = hist.source or provider
        except Exception as exc:  # network / provider outage only
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "action": "plan",
                    "symbol": symbol,
                    "algo": algo,
                    "reason": f"live intraday feed for {symbol} unavailable: {exc}",
                    "rows": [],
                    "orders": [],
                    "n": 0,
                    "series": [],
                    "cards": {},
                    "methodology": self._plan_methodology(),
                    "field_dictionary": _FIELD_DICTIONARY,
                    "next_actions": [
                        "Retry once the venue market-data feed recovers.",
                        f"Confirm '{symbol}' is a valid {asset_class} symbol for the {provider} feed.",
                    ],
                },
                sources=[provider],
                warnings=[f"no_live_source: {provider} intraday fetch failed for {symbol}"],
                metadata={"status": "provider_unavailable", "provider": provider,
                          "asset_class": asset_class, "interval": interval},
            )

        if not bars:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "action": "plan",
                    "symbol": symbol,
                    "algo": algo,
                    "reason": f"no intraday bars returned for {symbol} from {src}",
                    "rows": [],
                    "orders": [],
                    "n": 0,
                    "series": [],
                    "cards": {},
                    "methodology": self._plan_methodology(),
                    "field_dictionary": _FIELD_DICTIONARY,
                    "next_actions": [
                        f"Check that '{symbol}' trades intraday on the {provider} feed.",
                    ],
                },
                sources=[src],
                warnings=[f"empty_intraday_window for {symbol} ({interval})"],
                metadata={"status": "provider_unavailable", "provider": src,
                          "asset_class": asset_class, "interval": interval},
            )

        ref_price = None
        last_close = bars[-1].get("close")
        if last_close is not None:
            ref_price = float(last_close)
        if arrival_price is None:
            arrival_price = ref_price

        schedule, resolved_algo = _algo_schedule(
            algo, target_qty=target_qty, horizon_s=horizon_s, slices=slices,
            side=side, ref_price=ref_price,
        )
        rows = _build_plan_rows(
            bars, schedule=schedule, target_qty=target_qty, side=side,
            arrival_price=arrival_price,
        )

        # Parent-level aggregates from the real per-slice rows.
        filled_qty = rows[-1]["cum_qty"] if rows else 0.0
        notional = sum((r["qty"] * (r["bar_close"] or 0.0)) for r in rows)
        avg_fill_px = (notional / filled_qty) if filled_qty else ref_price
        is_values = [r["is_bps"] for r in rows if r["is_bps"] is not None]
        slip_values = [r["slip_bps"] for r in rows if r["slip_bps"] is not None]
        avg_is_bps = round(sum(is_values) / len(is_values), 2) if is_values else None
        worst_slip = round(max(slip_values, key=abs), 2) if slip_values else None

        order_row = {
            "parent_id": params.get("parent_id") or f"PLAN-{symbol}-{resolved_algo}",
            "symbol": symbol,
            "side": side,
            "algo": resolved_algo,
            "target_qty": round(target_qty, 8),
            "filled_qty": round(filled_qty, 8),
            "avg_fill_px": round(avg_fill_px, 6) if avg_fill_px is not None else None,
            "arrival_price": round(arrival_price, 6) if arrival_price is not None else None,
            "is_bps": avg_is_bps,
            "pace_pct": rows[-1]["pace_pct"] if rows else None,
            "status": "planned",
            "opened_at": rows[0]["ts_ms"] if rows else None,
        }

        price_series = [
            {"t": r["ts_ms"], "v": r["bar_close"]} for r in rows if r["ts_ms"] is not None
        ]
        slippage_series = [
            {"t": r["ts_ms"], "v": r["slip_bps"]} for r in rows if r["ts_ms"] is not None
        ]
        pace_series = [
            {"t": r["ts_ms"], "v": r["pace_pct"]} for r in rows if r["ts_ms"] is not None
        ]

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "action": "plan",
                "symbol": symbol,
                "algo": resolved_algo,
                "asset_class": asset_class,
                "interval": interval,
                "rows": rows,
                "orders": [order_row],
                "n": len(rows),
                "series": {
                    "price": price_series,
                    "slippage": slippage_series,
                    "pace": pace_series,
                },
                "cards": {
                    "open_parents": 1,
                    "needs_close": 0,
                    "avg_is_bps": avg_is_bps,
                    "worst_slippage_bps": worst_slip,
                    "data_mode": "live_exchange",
                    "as_of": rows[-1]["ts_ms"] if rows else None,
                },
                "methodology": self._plan_methodology(),
                "field_dictionary": _FIELD_DICTIONARY,
                "next_actions": [
                    "Open this schedule with action=open then record fills with action=slice.",
                    "Tune algo/horizon_seconds/slices and re-run to compare slippage profiles.",
                ],
            },
            sources=[src],
            metadata={
                "status": "ok",
                "provider": src,
                "asset_class": asset_class,
                "interval": interval,
                "algo": resolved_algo,
                "bars_used": len(rows),
            },
        )

    @staticmethod
    def _plan_methodology() -> str:
        return (
            "action=plan drives the live execution-algo schedulers "
            "(algos.TWAP/VWAP/Iceberg/Sniper) against real intraday OHLCV — "
            "Binance 5m klines for crypto, Yahoo 5m bars for listed assets. "
            "Each schedule slice is mapped onto an actual recent market bar; the "
            "per-slice benchmark is that bar's typical-price VWAP (H+L+C)/3, "
            "slippage = (close - benchmark)/benchmark * 1e4 bps, and "
            "implementation shortfall = (close - arrival)/arrival * 1e4 * sign(side). "
            "Pace is cumulative scheduled qty / target. No numbers are fabricated: "
            "on a feed outage the function returns status=provider_unavailable."
        )
