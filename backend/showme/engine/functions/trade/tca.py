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

import asyncio
import csv
import io
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from showme.crypto_aliases import is_crypto_symbol as _is_crypto_symbol
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument

_OK = "ok"
_EMPTY = "empty"
_PROVIDER_UNAVAILABLE = "provider_unavailable"

_METHODOLOGY = (
    "TCA loads executed fills from the autonomous bot fill ledger (bot_fills) "
    "and the manual order_history store, then joins each fill against a live "
    "intraday VWAP benchmark sourced keyless (Binance klines for crypto, "
    "yfinance intraday candles otherwise) over the fill's own session, i.e. the "
    "UTC calendar day of the fill (TCA#2: never a window ending today). A fill "
    "without a timestamp, or whose session has no intraday bars, has no live "
    "benchmark and falls back to its arrival price. The optional transactions "
    "input (JSON or CSV) replaces the local store, and window keeps only fills "
    "whose filled_at lies inside the lookback (ALL or omitted: no lookback). "
    "Only real placed orders count: paper/shadow signals that never reached a "
    "broker are excluded, and rows without a positive executed size are "
    "skipped rather than defaulted. "
    "Per-fill slippage_bps = (avg_fill - benchmark) / benchmark * 10000 * "
    "side_sign; implementation-shortfall is_bps = (avg_fill - arrival) / arrival "
    "* 10000 * side_sign; opportunity_bps is always null because the ledgers "
    "record no target size from which unfilled quantity could be derived. "
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
    "benchmark_px": "Live intraday benchmark for the fill session: VWAP, or TWAP "
        "(equal-weight mean of bar typical prices) when benchmark=TWAP.",
    "arrival_px": "Reference (arrival/decision) price at order entry.",
    "slippage_bps": "Signed slippage vs the VWAP benchmark, in basis points.",
    "is_bps": "Implementation shortfall vs arrival price, in basis points.",
    "opportunity_bps": "Cost of unfilled quantity vs benchmark, in basis "
        "points. Always null in bot-fill rows: the fill ledgers do not record "
        "the target order size, so unfilled quantity is unknowable.",
    "notional_usd": "avg_fill_px * quantity (quote-currency notional).",
    "cost_usd": "slippage_bps * notional / 10000 (execution cost).",
    "filled_at": "ISO-8601 timestamp of the fill.",
    "benchmark_source": "Provider of the intraday bars for the fill's session, or 'arrival' fallback.",
    "excluded_orders": "Orders left out of the analysis because they had no broker-confirmed "
        "fill or executed size: total count and reasons.",
}


def _crypto_interval(symbol: str) -> bool:
    # TCA#7: a bare "USD"/"BTC"/"ETH" suffix match also caught FX pairs such as
    # EURUSD. Use the canonical crypto alias knowledge base instead.
    return bool(_is_crypto_symbol(symbol))


_BENCHMARKS = ("VWAP", "TWAP", "ARRIVAL", "IMPLEMENTATION_SHORTFALL")

# yfinance serves 5-minute bars only for roughly the last 60 days.
_INTRADAY_RETENTION_DAYS = 59


def _parse_ts(value: Any) -> datetime | None:
    """Parse a fill timestamp (ISO-8601 string or epoch seconds) to aware UTC."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _session_day(value: Any) -> date | None:
    """UTC calendar day of a fill: the session its benchmark is drawn from."""
    dt = _parse_ts(value)
    return dt.date() if dt is not None else None


def _day_bounds_ms(day: date) -> tuple[int, int]:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    start_ms = int(start.timestamp() * 1000)
    return start_ms, start_ms + 86_400_000 - 1


_EXCLUSION_LABELS = {
    "unfilled_no_execution": "no recorded execution",
    "no_fill_price": "no broker fill price",
    "no_positive_qty": "no positive executed size",
    "outside_window": "outside the requested window",
    "timestamp_missing": "no timestamp to apply the window to",
    "invalid_row": "malformed transaction row",
    "missing_symbol": "no symbol",
    "invalid_side": "side is not BUY/SELL",
}

# TCA#4: `window` is a lookback on filled_at. Omitted or ALL = no lookback filter.
_WINDOW_DAYS = {"1D": 1, "1W": 7, "1M": 30, "3M": 90, "1Y": 365}

_TX_ALIASES = {
    "qty": "quantity", "size": "quantity",
    "price": "avg_fill_px", "fill_price": "avg_fill_px", "fill_px": "avg_fill_px",
    "avg_fill": "avg_fill_px",
    "arrival": "arrival_px", "arrival_price": "arrival_px",
    "time": "filled_at", "ts": "filled_at", "timestamp": "filled_at",
    "filled": "filled_at",
    "id": "order_id",
}
_TX_POSITIONAL = ["symbol", "side", "quantity", "avg_fill_px", "arrival_px",
                  "filled_at", "order_id"]
_SIDE_MAP = {"BUY": "BUY", "B": "BUY", "LONG": "BUY",
             "SELL": "SELL", "S": "SELL", "SHORT": "SELL"}


def _window_cutoff(window: Any, now: datetime) -> datetime | None:
    """Earliest filled_at kept by ``window``; None means no lookback filter."""
    if window is None:
        return None
    text = str(window).strip().upper()
    if text in ("", "ALL"):
        return None
    if text == "YTD":
        return datetime(now.year, 1, 1, tzinfo=timezone.utc)
    days = _WINDOW_DAYS.get(text)
    if days is None:
        raise ValueError(
            f"Unsupported window '{window}'; expected one of "
            "1D, 1W, 1M, 3M, YTD, 1Y, ALL.")
    return now - timedelta(days=days)


def _window_skip(filled_at: Any, cutoff: datetime | None) -> str | None:
    if cutoff is None:
        return None
    ts = _parse_ts(filled_at)
    if ts is None:
        return "timestamp_missing"
    return "outside_window" if ts < cutoff else None


def _has_inline_transactions(raw: Any) -> bool:
    if raw is None:
        return False
    if isinstance(raw, (list, dict)):
        return len(raw) > 0
    return bool(str(raw).strip())


def _parse_transactions_rows(raw: Any) -> list[Any]:
    """Parse the inline `transactions` input (JSON or CSV) into raw row objects.

    Raises ValueError when the text cannot be read as JSON or CSV at all; row
    level problems are reported as exclusions later, not here.
    """
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return raw
    text = str(raw).strip()
    if text[:1] in ("[", "{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"transactions is not valid JSON ({exc.msg}).") from exc
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return parsed
        raise ValueError("transactions JSON must be an object or an array of objects.")
    grid = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if not grid:
        return []
    first = [c.strip().lower() for c in grid[0]]
    if first and first[0] in ("symbol", "ticker", "instrument"):
        header = [_TX_ALIASES.get(h, h) for h in first]
        body = grid[1:]
    else:
        header = _TX_POSITIONAL
        body = grid
    return [dict(zip(header, [c.strip() for c in r])) for r in body]


def _to_positive(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value:
            return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num or num in (float("inf"), float("-inf")) or num <= 0:
        return None
    return num


def _normalise_transaction(row: Any, index: int) -> tuple[dict[str, Any] | None, str | None]:
    """Return (fill, None) for a usable row, or (None, exclusion_reason)."""
    if not isinstance(row, dict):
        return None, "invalid_row"
    symbol = str(row.get("symbol") or "").strip().upper()
    if not symbol:
        return None, "missing_symbol"
    side = _SIDE_MAP.get(str(row.get("side") or "").strip().upper())
    if side is None:
        return None, "invalid_side"
    qty = _to_positive(row.get("quantity"))
    if qty is None:
        return None, "no_positive_qty"
    px = _to_positive(row.get("avg_fill_px"))
    if px is None:
        return None, "no_fill_price"
    return {
        "order_id": str(row.get("order_id") or "").strip() or f"tx-{index}",
        "symbol": symbol,
        "broker": str(row.get("broker") or "").strip() or "inline",
        "side": side,
        "quantity": qty,
        "avg_fill_px": px,
        "arrival_px": _to_positive(row.get("arrival_px")),
        "filled_at": str(row.get("filled_at") or "").strip() or None,
    }, None


def _excluded_payload(excluded: dict[str, int]) -> dict[str, Any]:
    reasons = {k: v for k, v in excluded.items() if v}
    return {"total": sum(reasons.values()), "reasons": reasons}


def _exclusion_warnings(excluded_orders: dict[str, Any]) -> list[str]:
    total = int(excluded_orders.get("total") or 0)
    if not total:
        return []
    parts = ", ".join(
        f"{_EXCLUSION_LABELS.get(k, k)}: {v}"
        for k, v in excluded_orders.get("reasons", {}).items()
    )
    return [f"Excluded {total} order(s) from the analysis ({parts}); they are not "
            "counted as fills."]


def _normalise_klines(rows: Any) -> list[dict[str, Any]]:
    """Accept Binance raw kline rows (lists) or already-shaped OHLCV dicts."""
    out: list[dict[str, Any]] = []
    for r in rows or []:
        if isinstance(r, dict):
            out.append(r)
        elif isinstance(r, (list, tuple)) and len(r) >= 6:
            out.append({"high": float(r[2]), "low": float(r[3]),
                        "close": float(r[4]), "volume": float(r[5])})
    return out


def _twap_from_candles(candles: list[dict[str, Any]]) -> float | None:
    """Time-weighted average of typical price: equal weight per bar (TCA#3)."""
    total = 0.0
    count = 0
    for c in candles:
        try:
            high = float(c.get("high") or 0)
            low = float(c.get("low") or 0)
            close = float(c.get("close") or 0)
        except (TypeError, ValueError):
            continue
        typical = (high + low + close) / 3.0 if (high or low or close) else close
        if typical <= 0:
            continue
        total += typical
        count += 1
    if count == 0:
        return None
    return total / count


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
        if benchmark not in _BENCHMARKS:
            # An unknown benchmark used to fall through to VWAP while still being
            # echoed back as the requested label. Reject it instead.
            reason = (f"Unsupported TCA benchmark '{benchmark}'; expected one of "
                      f"{', '.join(_BENCHMARKS)}.")
            return FunctionResult(
                code=self.code, instrument=instrument,
                data={
                    "status": "input_error",
                    "reason": reason,
                    "as_of": as_of,
                    "benchmark": benchmark,
                    "rows": [],
                    "series": [],
                    "summary": {"benchmark": benchmark, "fill_count": 0},
                    "next_actions": [f"Choose one of: {', '.join(_BENCHMARKS)}."],
                },
                sources=[],
                warnings=[reason],
            )
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
                    "excluded_orders": {"total": 0, "reasons": {}},
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

        # ---- 1) Load REAL fills: the inline transactions input when given (it
        # replaces the local store), else the bot ledger + order_history.
        try:
            cutoff = _window_cutoff(params.get("window"), datetime.now(timezone.utc))
        except ValueError as exc:
            return self._input_error(instrument, benchmark, as_of, str(exc))
        excluded: dict[str, int] = {}
        tx_raw = params.get("transactions")
        if _has_inline_transactions(tx_raw):
            try:
                tx_rows = _parse_transactions_rows(tx_raw)
            except ValueError as exc:
                return self._input_error(
                    instrument, benchmark, as_of, f"Invalid transactions input: {exc}")
            fills = self._fills_from_transactions(
                tx_rows, symbol=symbol, broker=broker, cutoff=cutoff,
                excluded=excluded)[:limit]
            source_names = {"inline_transactions"}
        else:
            fills = self._load_fills(symbol=symbol, broker=broker, limit=limit,
                                     excluded=excluded, cutoff=cutoff)
            source_names = {"bot_fills", "order_history"}
        excluded_orders = _excluded_payload(excluded)
        exclusion_warnings = _exclusion_warnings(excluded_orders)

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
                    "excluded_orders": excluded_orders,
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                    "next_actions": [
                        "Run a bot (paper or live) so fills land in the bot ledger, "
                        "or submit/import orders with fill metadata.",
                        "Use EXEC to monitor parent orders before TCA.",
                    ],
                },
                sources=sorted(source_names),
                warnings=["No executed fills available for trade cost analysis.",
                          *exclusion_warnings],
            )

        # ---- 2) Resolve live VWAP benchmark per distinct symbol.
        benchmark_warnings: list[str] = list(exclusion_warnings)
        provider_failed = False
        sources: set[str] = set(source_names)
        # TCA#3: TWAP selects the time-weighted bar mean; every other live
        # benchmark (VWAP, and the VWAP fallback of ARRIVAL/IS) uses VWAP.
        bench_kind = "TWAP" if benchmark == "TWAP" else "VWAP"
        # TCA#2: the benchmark is looked up per (symbol, fill session), where the
        # session is the UTC day of the fill. Fills with no timestamp get None.
        keys = sorted(
            {(f["symbol"], _session_day(f.get("filled_at")))
             for f in fills if f.get("symbol")},
            key=lambda k: (k[0], k[1].isoformat() if k[1] else ""),
        )
        lookups = await asyncio.gather(*(
            self._live_vwap(sym, instrument, kind=bench_kind, session_day=day)
            for sym, day in keys
        ))
        vwap_by_key: dict[tuple[str, date | None], tuple[float | None, str]] = {}
        no_session: set[str] = set()
        no_bars: set[str] = set()
        for (sym, day), (vwap, src, failed) in zip(keys, lookups):
            vwap_by_key[(sym, day)] = (vwap, src)
            if failed:
                provider_failed = True
            elif vwap is None and day is None:
                no_session.add(sym)
            elif vwap is None and src != "none":
                no_bars.add(f"{sym} {day.isoformat()}")
            if src and src not in ("arrival", "none"):
                sources.add(src)
        if no_session:
            benchmark_warnings.append(
                "Fill timestamp missing for "
                f"{', '.join(sorted(no_session))}; no session benchmark was requested, "
                "so those fills fell back to their arrival price."
            )
        if no_bars:
            benchmark_warnings.append(
                "No intraday bars for the fill session of "
                f"{', '.join(sorted(no_bars))} (session = UTC day of the fill; "
                "yfinance keeps 5-minute bars for about 60 days); those fills fell "
                "back to their arrival price where one was recorded."
            )

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
            live_vwap, bench_src = vwap_by_key.get(
                (sym, _session_day(f.get("filled_at"))), (None, "none"))

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
                # F6/H10: opportunity_bps is NOT implementation shortfall. The
                # field dictionary defines it as the cost of UNFILLED size vs
                # benchmark, but fill-ledger rows never record a target size,
                # so unfilled qty is unknowable here. Return None (with the
                # dictionary corrected) instead of serving a mislabeled copy
                # of is_bps.
                "opportunity_bps": None,
                "notional_usd": round(notional, 2),
                "cost_usd": round(cost_usd, 2),
                "filled_at": f.get("filled_at"),
                "benchmark_source": bench_used,
            })
            # TCA#6: a fill without a benchmark has no slippage. It is left out
            # of the series rather than plotted as a 0.0 bps execution.
            if slip_bps is not None:
                series.append({
                    "label": (f.get("order_id") or sym or "fill"),
                    "value": round(slip_bps, 2),
                })

        n = len(rows)
        # No measured value means no mean: null, never a 0.0 that reads as a
        # perfect execution.
        avg_slip = sum(slip_bps_vals) / len(slip_bps_vals) if slip_bps_vals else None
        avg_is = sum(is_bps_vals) / len(is_bps_vals) if is_bps_vals else None
        worst_slip = max(slip_bps_vals, key=abs) if slip_bps_vals else None
        summary = {
            "benchmark": benchmark,
            "fill_count": n,
            "avg_slippage_bps": round(avg_slip, 2) if avg_slip is not None else None,
            "avg_is_bps": round(avg_is, 2) if avg_is is not None else None,
            "worst_slippage_bps": round(worst_slip, 2) if worst_slip is not None else None,
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
                "excluded_orders": excluded_orders,
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

    @staticmethod
    def _input_error(instrument: Instrument | None, benchmark: str,
                     as_of: str, reason: str) -> FunctionResult:
        return FunctionResult(
            code=TCAFunction.code, instrument=instrument,
            data={
                "status": "input_error",
                "reason": reason,
                "as_of": as_of,
                "benchmark": benchmark,
                "rows": [],
                "series": [],
                "summary": {"benchmark": benchmark, "fill_count": 0},
                "next_actions": ["Correct the TCA input (window, transactions) and re-run."],
            },
            sources=[],
            warnings=[reason],
        )

    @staticmethod
    def _fills_from_transactions(
        rows: list[Any], *, symbol: str | None, broker: str | None,
        cutoff: datetime | None, excluded: dict[str, int],
    ) -> list[dict[str, Any]]:
        """Normalise inline transaction rows; malformed rows are counted, not dropped silently."""
        want_sym = symbol.upper() if symbol else None
        want_broker = broker.lower() if broker else None
        out: list[dict[str, Any]] = []
        for index, raw in enumerate(rows, start=1):
            fill, reason = _normalise_transaction(raw, index)
            if fill is None:
                excluded[reason] = excluded.get(reason, 0) + 1
                continue
            if want_sym and fill["symbol"] != want_sym:
                continue
            if want_broker and fill["broker"].lower() != want_broker:
                continue
            skip = _window_skip(fill["filled_at"], cutoff)
            if skip:
                excluded[skip] = excluded.get(skip, 0) + 1
                continue
            out.append(fill)
        return out

    def _load_fills(
        self, *, symbol: str | None, broker: str | None, limit: int,
        excluded: dict[str, int] | None = None, cutoff: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return normalised real fills from the bot ledger + order_history.

        The autonomous bot ledger is ``BotStore`` (JSON BotRecords under
        ``<app_home>/bots/``). Each ``signal_log`` entry that actually placed
        an order is a real fill: ``fill_price`` is the broker-confirmed
        execution price (preferred), ``price`` is the signal/decision price we
        treat as the arrival benchmark, ``qty`` the executed size, and
        ``kind`` (entry/exit) maps to BUY/SELL.

        F6 (MED, honest-data): only ``action == "placed"`` rows count as fills.
        The old filter also accepted ``"shadow"`` — paper signals for which NO
        real order was ever sent (bots/runner.py sets action="shadow" exactly
        then) — so never-executed simulation rows were counted as executed
        fills in every slippage/cost metric. Shadow rows are now excluded
        outright (chosen over tagging ``executed: False``) because the module's
        contract is "REAL executed fills" only; the summary KPIs are means over
        rows and there is no honest way to present a blended population.
        Entries with missing/non-positive qty are SKIPPED instead of being
        defaulted to a fabricated size of 1.0.
        """
        out: list[dict[str, Any]] = []
        want_sym = symbol.upper() if symbol else None
        skipped: dict[str, int] = excluded if excluded is not None else {}

        def _skip(reason: str) -> None:
            skipped[reason] = skipped.get(reason, 0) + 1

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
                    if entry.action != "placed":
                        continue
                    try:
                        qty = float(entry.qty) if entry.qty is not None else 0.0
                    except (TypeError, ValueError):
                        continue
                    if qty <= 0:
                        # No fabricated default size — a fill without a size
                        # cannot contribute honest notional/cost numbers.
                        _skip("no_positive_qty")
                        continue
                    # Only a broker-confirmed execution price is a fill. The
                    # signal price (entry.price) is the arrival benchmark, not
                    # an execution: a placed order with no fill_price stays
                    # unfilled and is excluded instead of booked at signal px.
                    fill_px = entry.fill_price
                    if not fill_px or fill_px <= 0:
                        _skip("no_fill_price")
                        continue
                    side = "BUY" if entry.kind == "entry" else "SELL"
                    # arrival/decision reference = the signal-bar close, which
                    # is distinct from the broker fill_price when slippage > 0.
                    arrival = entry.price if entry.fill_price else None
                    filled_at = entry.bar_close_time or entry.timestamp
                    skip = _window_skip(filled_at, cutoff)
                    if skip:
                        _skip(skip)
                        continue
                    out.append({
                        "order_id": entry.order_id or f"{meta.id[:8]}-{entry.bar_index}",
                        "symbol": bot_sym or None,
                        "broker": f"bot:{meta.id[:8]}",
                        "side": side,
                        "quantity": qty,
                        "avg_fill_px": float(fill_px),
                        "arrival_px": float(arrival) if arrival is not None else None,
                        "filled_at": filled_at,
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
                avg_fill, filled_qty = self._avg_fill(md)
                if avg_fill is None:
                    # No recorded execution (submitted / open / cancelled):
                    # not a fill. Never fall back to the limit price or the
                    # ordered quantity here.
                    _skip("unfilled_no_execution")
                    continue
                # Arrival is only what the order recorded. The limit price is
                # an order instruction, not a market benchmark: when it is
                # absent, arrival stays None and slippage/IS stay unset.
                arrival = md.get("arrival_price")
                ts = o.get("ts")
                filled_at = (datetime.fromtimestamp(ts, timezone.utc).isoformat()
                             if ts else None)
                skip = _window_skip(filled_at, cutoff)
                if skip:
                    _skip(skip)
                    continue
                out.append({
                    "order_id": o.get("order_id") or f"ord-{o.get('id')}",
                    "symbol": (o.get("symbol") or "").upper() or None,
                    "broker": o.get("broker") or "manual",
                    "side": (o.get("side") or "BUY").upper(),
                    "quantity": float(filled_qty),
                    "avg_fill_px": float(avg_fill),
                    "arrival_px": float(arrival) if arrival is not None else None,
                    "filled_at": filled_at,
                })
        except Exception:  # noqa: BLE001 — store optional
            pass

        return out[:limit]

    @staticmethod
    def _avg_fill(metadata: dict[str, Any]) -> tuple[float | None, float]:
        """Return (avg_fill_px, executed_qty) or (None, 0.0) when unfilled.

        An order is filled only when its metadata records an execution: either
        a ``fills`` list with positive quantity, or an explicit ``avg_fill``
        together with a positive ``filled_qty``. The order's book/limit price
        is deliberately NOT used as a fill price (that booked unfilled limit
        orders as full-size fills with fabricated slippage).
        """
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
        try:
            filled_qty = float(metadata.get("filled_qty") or 0)
        except (TypeError, ValueError):
            filled_qty = 0.0
        av = metadata.get("avg_fill")
        if av is None or filled_qty <= 0:
            return None, 0.0
        return float(av), filled_qty

    async def _live_vwap(
        self, symbol: str, instrument: Instrument | None, *, kind: str = "VWAP",
        session_day: date | None = None,
    ) -> tuple[float | None, str, bool]:
        """Return (benchmark, source, failed) for the fill session ``session_day``.

        Keyless: Binance for crypto, yfinance otherwise. ``kind`` selects the bar
        aggregation: ``"VWAP"`` (volume-weighted) or ``"TWAP"`` (equal-weight mean
        of bar typical prices). A fill with no session (no timestamp) is never
        benchmarked against some other window (TCA#2).
        """
        if session_day is None:
            return None, "none", False
        aggregate = _twap_from_candles if kind == "TWAP" else _vwap_from_candles
        is_crypto = _crypto_interval(symbol)
        if instrument is not None and instrument.symbol == symbol:
            is_crypto = instrument.asset_class == AssetClass.CRYPTO

        if is_crypto:
            try:
                candles = await self._binance_klines(symbol, session_day)
                px = aggregate(candles)
                if px is not None:
                    return px, "binance", False
                return None, "binance", False
            except Exception:  # noqa: BLE001 — network/parse failure
                return None, "arrival", True

        age_days = (datetime.now(timezone.utc).date() - session_day).days
        if age_days > _INTRADAY_RETENTION_DAYS:
            # Outside the provider's 5-minute history: no bars, not an outage.
            return None, "yfinance", False
        try:
            candles = await self._yfinance_intraday(symbol, session_day)
            px = aggregate(candles)
            if px is not None:
                return px, "yfinance", False
            return None, "yfinance", False
        except Exception:  # noqa: BLE001 — network/parse failure
            return None, "arrival", True

    async def _binance_klines(self, symbol: str, session_day: date) -> list[dict[str, Any]]:
        start_ms, end_ms = _day_bounds_ms(session_day)
        provider = self.deps.get("binance")
        if provider is not None and hasattr(provider, "klines"):
            raw = await provider.klines(
                symbol, interval="5m", limit=288, start_ms=start_ms, end_ms=end_ms)
            return _normalise_klines(raw)
        # Direct keyless fallback.
        from showme.providers._http import get_client

        client = await get_client()
        resp = await client.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol.upper(), "interval": "5m", "limit": 288,
                    "startTime": start_ms, "endTime": end_ms},
        )
        resp.raise_for_status()
        return _normalise_klines(resp.json())

    async def _yfinance_intraday(self, symbol: str, session_day: date) -> list[dict[str, Any]]:
        start = session_day.isoformat()
        end = (session_day + timedelta(days=1)).isoformat()
        provider = self.deps.get("yfinance")
        if provider is not None and hasattr(provider, "ohlcv"):
            return await provider.ohlcv(symbol, start=start, end=end, interval="5m")

        def _sync() -> list[dict[str, Any]]:
            import yfinance as yf

            hist = yf.Ticker(symbol).history(start=start, end=end, interval="5m")
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
            # TCA#6: a card mean that was never measured (empty, timeout) is
            # null, never a 0.0 that reads as a perfect execution.
            "avg_slippage_bps": summary.get("avg_slippage_bps"),
            "avg_is_bps": summary.get("avg_is_bps"),
            "worst_slippage_bps": summary.get("worst_slippage_bps"),
            "total_cost_usd": summary.get("total_cost_usd"),
            "benchmark": benchmark,
            "data_mode": data_mode,
            "as_of": as_of,
        }
