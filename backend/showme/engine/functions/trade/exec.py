"""EXEC — TWAP/VWAP/ICEBERG/SNIPER execution monitor and schedule replay."""

from __future__ import annotations

import math
import time
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
# slice-by-slice … for TWAP/VWAP/ICEBERG/SNIPER algos". ``action=plan`` delivers that by
# driving the real ``algos.{TWAP,VWAP,Iceberg,Sniper}`` schedulers against
# recent intraday OHLCV (Binance for crypto, Yahoo for listed assets), so each
# slice carries the price/volume bar it would execute against plus an honest,
# real-data bar typical-price benchmark and schedule curve.

_PLAN_DEFAULT_SYMBOL = {
    "CRYPTO": "BTCUSDT",
}
_DEFAULT_PLAN_SYMBOL = "AAPL"
_PLAN_SUPPORTED_ALGOS = ("TWAP", "VWAP", "ICEBERG", "SNIPER")

_FIELD_DICTIONARY = {
    "slice_idx": "Zero-based slice index in the execution schedule.",
    "offset_s": "Seconds from schedule start at which the slice releases.",
    "release_ts_ms": "Epoch-ms at which the slice releases (schedule start + offset_s).",
    "ts_ms": "Epoch-ms of the historical bar in effect at the release instant (the bar that contains it).",
    "qty": "Quantity scheduled for this slice (algo-weighted).",
    "cum_qty": "Cumulative quantity scheduled through this slice.",
    "bar_close": "Close price of the historical bar in effect at the release instant (replayed reference from stored bars).",
    # EXEC#5: the bar's TYPICAL price, not a volume-weighted VWAP. A true bar VWAP
    # needs sub-bar trade data, which the intraday OHLCV feed does not carry.
    "benchmark_px": "Per-slice benchmark = the bar's typical price (H+L+C)/3 (slippage reference; not volume-weighted).",
    "slip_bps": "(bar_close - benchmark_px)/benchmark_px * 1e4, in basis points.",
    "is_bps": "Implementation shortfall vs arrival for this slice, side-signed bps.",
    "schedule_pct": "Cumulative scheduled qty / target_qty * 100 (schedule progress; a plan fills nothing).",
    "execution_mode": "'planned' — a hypothetical schedule replayed over historical interval bars; no order was sent.",
}


def _resolve_plan_asset_class(asset_class: str | None, symbol: str) -> str:
    if asset_class:
        return asset_class.upper()
    sym = symbol.upper()
    if sym.endswith(("USDT", "USDC", "BUSD", "USD")) and len(sym) > 4 and "=" not in sym:
        return "CRYPTO"
    return "EQUITY"


_BAR_SECONDS = {"1m": 60, "5m": 300}


def _plan_interval(asset_class: str, slot_s: float) -> str:
    """Pick the bar interval for a schedule whose slices are ``slot_s`` apart.

    EXEC#3: a fixed 5m bar cannot resolve sub-5-minute slices. Use the finest
    supported bar (1m) when slices are closer than 5 minutes; otherwise 5m
    bars give a tradeable intraday volume profile. The asset class does not
    change the choice (both venues serve 1m and 5m klines).
    """
    return "1m" if slot_s < 300 else "5m"


def _drop_forming_bar(bars: list[dict[str, Any]], bar_s: float, now_s: float) -> list[dict[str, Any]]:
    """Keep only completed bars: a bar opening at ``t`` is complete once
    ``t + bar_s <= now_s``. The intraday feeds can return the bar still forming
    at the request instant, which must not be replayed or set the window end."""
    return [b for b in bars if float(b["time"]) + bar_s <= now_s]


def _median_spacing(times: list[float]) -> float | None:
    """Median gap between consecutive bar opens (the bar length actually served)."""
    gaps = sorted(b - a for a, b in zip(times, times[1:]) if b > a)
    if not gaps:
        return None
    return gaps[len(gaps) // 2]


def _bar_index_at(times: list[float], instant_s: float) -> int:
    """Index of the bar in effect at ``instant_s``: the last bar opening at or
    before the instant (clamped to the first bar before the window)."""
    lo, hi = 0, len(times) - 1
    idx = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if times[mid] <= instant_s:
            idx = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return idx


def _bar_index_containing(times: list[float], instant_s: float, bar_s: float) -> int | None:
    """Index of the stored bar whose span ``[open, open + bar_s)`` contains
    ``instant_s``, or ``None`` when no stored bar covers it (a halt, a missing
    minute, or a time before the first bar). EXEC#2-RQ / EXEC#3-RQ: the nearest
    earlier bar is NOT a substitute; the caller must report the gap instead."""
    if not times:
        return None
    idx = _bar_index_at(times, instant_s)
    if times[idx] <= instant_s < times[idx] + bar_s:
        return idx
    return None


def _bar_typical_price(row: dict[str, Any]) -> float | None:
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
    schedule_start_s: int,
    bar_s: float,
) -> list[dict[str, Any]]:
    """Map an algo ``schedule`` onto the real ``bars`` by RELEASE TIME and
    compute real per-slice slippage / shortfall / pace from the bar data.

    EXEC#3: slice ``i`` releases at ``schedule_start_s + offset_s`` and is
    measured against the bar that CONTAINS that instant. A release that falls in
    a gap of the stored bars carries no market data (``bar_status`` says so)
    rather than borrowing the previous bar (EXEC#3-RQ).
    """
    times = [float(b["time"]) for b in bars]
    side_sign = -1.0 if str(side).upper() == "SELL" else 1.0
    rows: list[dict[str, Any]] = []
    cum_qty = 0.0
    for idx, slot in enumerate(schedule):
        offset_s = int(slot.get("offset_s", 0))
        release_s = schedule_start_s + offset_s
        qty = float(slot.get("qty", 0.0))
        cum_qty += qty
        bar_idx = _bar_index_containing(times, release_s, bar_s)
        bar = bars[bar_idx] if bar_idx is not None else None
        close = bar.get("close") if bar is not None else None
        bench = _bar_typical_price(bar) if bar is not None else None
        slip_bps: float | None = None
        if close is not None and bench:
            slip_bps = (float(close) - bench) / bench * 10_000.0
        is_bps: float | None = None
        if close is not None and arrival_price:
            is_bps = (float(close) - float(arrival_price)) / float(arrival_price) * 10_000.0 * side_sign
        ts_s = bar.get("time") if bar is not None else None
        rows.append(
            {
                "slice_idx": idx,
                "offset_s": offset_s,
                "release_ts_ms": int(release_s) * 1000,
                "ts_ms": int(ts_s) * 1000 if ts_s is not None else None,
                "bar_status": "ok" if bar is not None else "no_bar_at_release",
                "qty": round(qty, 8),
                "cum_qty": round(cum_qty, 8),
                "bar_close": float(close) if close is not None else None,
                "benchmark_px": round(bench, 8) if bench is not None else None,
                "slip_bps": round(slip_bps, 2) if slip_bps is not None else None,
                "is_bps": round(is_bps, 2) if is_bps is not None else None,
                # EXEC#8: a plan executes nothing, so this is schedule progress
                # (cumulative scheduled / target), never a fill ratio.
                "schedule_pct": round(cum_qty / target_qty * 100.0, 2) if target_qty else None,
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
    if upper == "VWAP":
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
    if upper == "TWAP":
        sched = TWAPAlgo(target_quantity=target_qty, duration_seconds=horizon_s, slices=slices).schedule()
        return sched, "TWAP"
    # EXEC#7: no silent TWAP fallback for tags the engine does not schedule.
    raise ValueError(f"algo '{upper}' is not scheduled by EXEC")


@FunctionRegistry.register
class EXECFunction(BaseFunction):
    code = "EXEC"
    name = "Execution Monitor"
    category = "trade"
    description = "TWAP/VWAP/ICEBERG/SNIPER slice schedule replay and parent-order fill-quality monitor."

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
            # EXEC#7: the monitor records only algo tags the engine schedules. An
            # unscheduled tag is refused before anything is stored, never kept as a
            # label the parent does not follow.
            algo = str(params.get("algo") or "TWAP").strip().upper()
            if algo not in _PLAN_SUPPORTED_ALGOS:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        "status": "unsupported_algo",
                        "action": "open",
                        "algo": algo,
                        "reason": (
                            f"algo '{algo}' is not scheduled by EXEC; "
                            f"supported: {', '.join(_PLAN_SUPPORTED_ALGOS)}"
                        ),
                        "supported_algos": list(_PLAN_SUPPORTED_ALGOS),
                        "next_actions": [
                            "Re-open with one of the supported algos: " + ", ".join(_PLAN_SUPPORTED_ALGOS) + ".",
                        ],
                    },
                    sources=["exec_monitor"],
                    metadata={"error": True, "status": "unsupported_algo"},
                )
            try:
                pid = exec_monitor.open_parent(
                    parent_id=params["parent_id"],
                    symbol=params["symbol"], side=params["side"],
                    target_qty=float(params["target_qty"]),
                    arrival_price=params.get("arrival_price"),
                    algo=algo,
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
        # build an execution schedule over recent bars instead of an empty placeholder so
        # EXEC fulfils its "slice-by-slice for TWAP/VWAP/ICEBERG/SNIPER algos" claim.
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
        """Build a real VWAP/TWAP/Iceberg/Sniper slice schedule against recent
        intraday OHLCV (Binance for crypto, Yahoo for listed assets).

        Returns real per-slice rows: each slice maps to an actual market bar and
        carries a bar typical-price benchmark + computed slippage / implementation
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
        # EXEC#7: only algos the engine actually schedules. Anything else is refused
        # rather than replaced by TWAP/VWAP.
        if algo not in _PLAN_SUPPORTED_ALGOS:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "unsupported_algo",
                    "action": "plan",
                    "symbol": symbol,
                    "algo": algo,
                    "reason": (
                        f"algo '{algo}' is not scheduled by EXEC action=plan; "
                        f"supported: {', '.join(_PLAN_SUPPORTED_ALGOS)}"
                    ),
                    "supported_algos": list(_PLAN_SUPPORTED_ALGOS),
                    "rows": [],
                    "orders": [],
                    "n": 0,
                    "series": [],
                    "cards": {},
                    "methodology": self._plan_methodology(),
                    "field_dictionary": _FIELD_DICTIONARY,
                    "next_actions": [
                        "Re-run with one of the supported algos: " + ", ".join(_PLAN_SUPPORTED_ALGOS) + ".",
                    ],
                },
                sources=[],
                metadata={"status": "unsupported_algo", "algo": algo},
            )
        try:
            raw_qty = params.get("target_qty")
            target_qty = float(raw_qty) if raw_qty is not None and str(raw_qty).strip() != "" else None
            horizon_s = int(params.get("horizon_seconds") or 600)
            slices = int(params.get("slices") or 12)
        except (TypeError, ValueError) as exc:
            return _error_result(self.code, "plan", f"invalid field value: {exc}")
        # EXEC#6: no silent 100-unit schedule when the parent quantity is missing.
        # NaN and inf pass a plain ``<= 0`` test, so require a finite positive value.
        if target_qty is None or not math.isfinite(target_qty) or target_qty <= 0:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "needs_input",
                    "action": "plan",
                    "symbol": symbol,
                    "algo": algo,
                    "reason": "target_qty (total quantity to schedule) is required and must be a finite number greater than 0.",
                    "missing_fields": ["target_qty"],
                    "rows": [],
                    "orders": [],
                    "n": 0,
                    "series": [],
                    "cards": {},
                    "methodology": self._plan_methodology(),
                    "field_dictionary": _FIELD_DICTIONARY,
                    "next_actions": ["Pass target_qty (the parent quantity) and retry."],
                },
                sources=[],
                metadata={"status": "needs_input", "missing_fields": ["target_qty"]},
            )
        slices = max(2, min(slices, 24))
        side = (params.get("side") or "BUY").upper()
        # A caller-supplied arrival must be a finite number; anything else is reported,
        # not dropped silently (a dropped arrival would relabel the IS figures).
        arrival_price = params.get("arrival_price")
        if arrival_price is not None and str(arrival_price).strip() != "":
            try:
                arrival_price = float(arrival_price)
            except (TypeError, ValueError):
                return _error_result(
                    self.code, "plan",
                    f"invalid field value: arrival_price must be a number, got {arrival_price!r}",
                )
            if not math.isfinite(arrival_price):
                return _error_result(
                    self.code, "plan",
                    f"invalid field value: arrival_price must be a finite number, got {arrival_price!r}",
                )
        else:
            arrival_price = None

        slot_s = horizon_s / slices
        interval = _plan_interval(asset_class, slot_s)
        bar_s_nominal = _BAR_SECONDS[interval]
        provider = "binance" if asset_class == "CRYPTO" else "yfinance"

        # --- fetch recent intraday bars (graceful network-failure fallback) ---
        try:
            want_bars = max(slices * 2, 60, horizon_s // bar_s_nominal + 2)
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

        # EXEC#3 follow-up: replay completed bars only (see _drop_forming_bar).
        bars = _drop_forming_bar(bars, float(bar_s_nominal), time.time())

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

        # EXEC#3: the replay window is the last ``horizon_s`` seconds of
        # completed bars; the schedule starts at its beginning.
        bars = sorted(bars, key=lambda b: float(b["time"]))
        times = [float(b["time"]) for b in bars]
        bar_s = _median_spacing(times) or float(bar_s_nominal)
        window_end_s = int(times[-1]) + int(bar_s)
        schedule_start_s = window_end_s - horizon_s
        if schedule_start_s < int(times[0]):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "input_error",
                    "action": "plan",
                    "symbol": symbol,
                    "algo": algo,
                    "reason": (
                        f"horizon_seconds={horizon_s} exceeds the intraday history "
                        f"fetched for {symbol} ({window_end_s - int(times[0])} s)"
                    ),
                    "rows": [],
                    "orders": [],
                    "n": 0,
                    "series": [],
                    "cards": {},
                    "methodology": self._plan_methodology(),
                    "field_dictionary": _FIELD_DICTIONARY,
                    "next_actions": [
                        "Lower horizon_seconds or the slice count and retry.",
                    ],
                },
                sources=[src],
                metadata={"status": "input_error", "provider": src,
                          "asset_class": asset_class, "interval": interval},
            )

        # EXEC#2: with no supplied arrival, the decision price is the price at
        # the START of the schedule (open of the bar in effect then), never the
        # close of the window's last bar, which would be look-ahead.
        # EXEC#2-RQ: the arrival bar must CONTAIN the schedule start; a gap yields
        # no arrival (null) instead of the open of an older, unrelated bar.
        arrival_idx = _bar_index_containing(times, schedule_start_s, bar_s)
        arrival_bar = bars[arrival_idx] if arrival_idx is not None else None
        if arrival_price is None and arrival_bar is not None:
            start_px = arrival_bar.get("open")
            if start_px is None:
                start_px = arrival_bar.get("close")
            arrival_price = float(start_px) if start_px is not None else None

        warnings: list[str] = []
        if bar_s > slot_s:
            warnings.append(
                f"bar_coarser_than_slice_spacing: {int(bar_s)}s bars for "
                f"{slot_s:g}s slice spacing; consecutive slices share a bar."
            )
        if arrival_price is None and arrival_bar is None:
            warnings.append(
                "arrival_unavailable: no stored bar covers the schedule start, so "
                "arrival_price is null; pass arrival_price to compute implementation shortfall."
            )

        schedule, resolved_algo = _algo_schedule(
            algo, target_qty=target_qty, horizon_s=horizon_s, slices=slices,
            side=side, ref_price=ref_price,
        )
        rows = _build_plan_rows(
            bars, schedule=schedule, target_qty=target_qty, side=side,
            arrival_price=arrival_price, schedule_start_s=schedule_start_s,
            bar_s=bar_s,
        )
        gap_rows = sum(1 for r in rows if r["bar_status"] != "ok")
        if gap_rows:
            warnings.append(
                f"bar_gap: {gap_rows} of {len(rows)} slice(s) release where no stored bar "
                f"covers the instant; those rows carry no market data."
            )

        # EXEC#4: the cards report the monitor store, not a hard-coded parent.
        parents = exec_monitor.list_parents(limit=10_000)
        open_parents = sum(1 for p in parents if not p.get("ended_at"))
        needs_close = sum(1 for p in parents if p.get("status") == "filled_not_closed")

        # Parent-level aggregates from the real per-slice rows.
        filled_qty = rows[-1]["cum_qty"] if rows else 0.0
        # Only slices that have a stored bar contribute; a gap slice has no price.
        priced = [r for r in rows if r["bar_close"] is not None]
        priced_qty = sum(r["qty"] for r in priced)
        notional = sum(r["qty"] * r["bar_close"] for r in priced)
        avg_fill_px = (notional / priced_qty) if priced_qty else None
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
            # EXEC#8: nothing is executed in a plan, so nothing is filled.
            "filled_qty": 0.0,
            "scheduled_qty": round(filled_qty, 8),
            "avg_fill_px": round(avg_fill_px, 6) if avg_fill_px is not None else None,
            "arrival_price": round(arrival_price, 6) if arrival_price is not None else None,
            "is_bps": avg_is_bps,
            "schedule_pct": rows[-1]["schedule_pct"] if rows else None,
            "status": "planned",
            "opened_at": schedule_start_s * 1000,
        }

        # Series sit on the wall-clock release instants so the schedule curve
        # reflects the requested horizon.
        price_series = [
            {"t": r["release_ts_ms"], "v": r["bar_close"]} for r in rows
        ]
        slippage_series = [
            {"t": r["release_ts_ms"], "v": r["slip_bps"]} for r in rows
        ]
        schedule_series = [
            {"t": r["release_ts_ms"], "v": r["schedule_pct"]} for r in rows
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
                "bar_seconds": int(bar_s),
                "horizon_seconds": horizon_s,
                "schedule_start_ms": schedule_start_s * 1000,
                "window_end_ms": window_end_s * 1000,
                "rows": rows,
                "orders": [order_row],
                "n": len(rows),
                "series": {
                    "price": price_series,
                    "slippage": slippage_series,
                    "schedule": schedule_series,
                },
                "cards": {
                    # EXEC#4: report the monitor store, never a hard-coded parent.
                    "open_parents": open_parents,
                    "needs_close": needs_close,
                    "avg_is_bps": avg_is_bps,
                    "worst_slippage_bps": worst_slip,
                    # EXEC#1: the plan replays HISTORICAL bars; it is not a live
                    # exchange feed. "live_exchange" would be a false live claim.
                    "data_mode": "historical_replay",
                    # F9 [M]: the plan path executes NOTHING — the IS/slip/avg
                    # numbers are hypothetical against historical interval
                    # bars. Stamp the lifecycle so the pane (and any consumer)
                    # can label plan vs actual honestly; keep output additive.
                    "execution_mode": "planned",
                    "as_of": window_end_s * 1000,
                },
                "methodology": self._plan_methodology(),
                "field_dictionary": _FIELD_DICTIONARY,
                "next_actions": [
                    "Open this schedule with action=open then record fills with action=slice.",
                    "Tune algo/horizon_seconds/slices and re-run to compare slippage profiles.",
                ],
            },
            sources=[src],
            warnings=warnings,
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
            "action=plan is a HISTORICAL REPLAY (data_mode=historical_replay, no order "
            "is sent). It drives the execution-algo schedulers (algos.TWAP/VWAP/Iceberg/"
            "Sniper) over the last horizon_seconds of completed intraday OHLCV: Binance "
            "klines for crypto, Yahoo bars for listed assets (1m when slices are under "
            "5 minutes apart, otherwise 5m). Slice i releases at schedule_start + offset_s "
            "and is measured against the bar in effect at that instant. The default "
            "arrival is the open of the bar at schedule_start. Per-slice benchmark is that "
            "bar's typical price (H+L+C)/3, which is NOT volume-weighted; slippage = (close - "
            "benchmark)/benchmark * 1e4 bps, and implementation shortfall = (close - arrival)/"
            "arrival * 1e4 * sign(side). schedule_pct is cumulative scheduled qty / target; "
            "a plan fills nothing. No numbers are fabricated: on a feed outage the function "
            "returns status=provider_unavailable."
        )
