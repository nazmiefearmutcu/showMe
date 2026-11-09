"""SECT — Sector Heatmap (S&P 500 + global sector ETF performance)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


_SECTOR_ETFS = {
    "Technology":  "XLK",
    "Financials":  "XLF",
    "Energy":      "XLE",
    "Healthcare":  "XLV",
    "Industrials": "XLI",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Utilities":   "XLU",
    "Materials":   "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


_PERIODS = ("1D", "MTD", "QTD", "YTD")


def _period_param(params: dict[str, Any]) -> str:
    raw = str(params.get("period") or params.get("range") or "1D").strip().upper()
    aliases = {"DAY": "1D", "D": "1D", "MONTH": "MTD", "QUARTER": "QTD", "YEAR": "YTD"}
    return aliases.get(raw, raw if raw in _PERIODS else "1D")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _period_base_date(period: str, today: date) -> date | None:
    """Last calendar day before the period opens; its close is the base price.

    1D has no daily-history base (the quote's previous close is used instead).
    """
    if period == "MTD":
        return date(today.year, today.month, 1) - timedelta(days=1)
    if period == "QTD":
        quarter_first_month = 3 * ((today.month - 1) // 3) + 1
        return date(today.year, quarter_first_month, 1) - timedelta(days=1)
    if period == "YTD":
        return date(today.year, 1, 1) - timedelta(days=1)
    return None


def _close_on_or_before(frame: Any, cutoff: date) -> float | None:
    """Close of the latest daily bar dated on or before ``cutoff`` (None if absent)."""
    if frame is None or getattr(frame, "empty", True) or "close" not in getattr(frame, "columns", []):
        return None
    best_day: date | None = None
    best_close: float | None = None
    for stamp, close in zip(frame.index, frame["close"].tolist()):
        try:
            day = stamp.date() if hasattr(stamp, "date") else stamp
        except Exception:
            continue
        if not isinstance(day, date) or day > cutoff:
            continue
        try:
            value = float(close)
        except (TypeError, ValueError):
            continue
        if value != value or value <= 0:  # NaN or non-positive is not a base price
            continue
        if best_day is None or day > best_day:
            best_day, best_close = day, value
    return best_close


def _sector_template(period: str = "1D") -> list[dict[str, Any]]:
    """Model rows carry names and tickers only.

    The model has no price or change series, so no last, high, low or change
    value is emitted: a placeholder price or a constant change would read as
    market data. Every value field is null and the pane renders it as missing.
    """
    rows = [
        {"sector": name, "etf": etf, "last": None,
         "change_pct": None,
         "change_pct_period": None,
         "period": period,
         "quote_type": "model",
         "high_24h": None, "low_24h": None}
        for name, etf in _SECTOR_ETFS.items()
    ]
    return rows


def _rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Largest change first; rows without a change sort last, never as 0."""
    rows.sort(key=lambda x: (x.get("change_pct") is None, -(x.get("change_pct") or 0.0)))
    return rows


@FunctionRegistry.register
class SECTFunction(BaseFunction):
    code = "SECT"
    name = "Sector Heatmap"
    category = "screen"
    description = "S&P 500 sector ETF day/MTD/QTD/YTD performance heatmap."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        period = _period_param(params)
        live = _truthy(params.get("live_screen")) or _truthy(params.get("live"))
        if not live:
            return FunctionResult(code=self.code, instrument=None,
                                  data={
                                      "status": "model",
                                      "reason": (
                                          "Deterministic sector ETF model selected. The model carries no "
                                          "price or change values, so every row is empty; use Live for quotes."
                                      ),
                                      "period": period,
                                      "rows": _sector_template(period),
                                  },
                                  sources=["sector_heatmap_model"])
        if not self.deps.yfinance:
            return FunctionResult(code=self.code, instrument=None,
                                  data={
                                      "status": "provider_unavailable",
                                      "reason": "No quote provider is configured for sector ETF heatmap quotes.",
                                      "period": period,
                                      "rows": _sector_template(period),
                                      "next_actions": [
                                          "Switch SECT to Model mode to see the sector list without values.",
                                          "Connect a sector ETF quote provider to enable live period changes.",
                                      ],
                                  },
                                  sources=["sector_heatmap_model"],
                                  metadata={"fallback": True, "degraded": True})
        quote_timeout = float(params.get("quote_timeout", 1.25))
        history_timeout = float(params.get("history_timeout", 4.0))
        today = datetime.now(timezone.utc).date()
        base_date = _period_base_date(period, today)

        async def _quote(etf: str):
            inst = Instrument(symbol=etf, asset_class=AssetClass.ETF)
            return await asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.QUOTE,
                    instrument=inst,
                    extra={"timeout": quote_timeout},
                )),
                timeout=quote_timeout + 0.25,
            )

        async def _history(etf: str):
            # Daily bars from the day before the period opens (plus a weekend margin).
            start = datetime.combine(base_date - timedelta(days=10), time(0), tzinfo=timezone.utc)
            inst = Instrument(symbol=etf, asset_class=AssetClass.ETF)
            return await asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OHLCV,
                    instrument=inst,
                    start=start,
                    interval="1d",
                    extra={"timeout": history_timeout},
                )),
                timeout=history_timeout + 0.25,
            )

        async def _one(name: str, etf: str):
            try:
                q = await _quote(etf)
            except Exception:
                return {"sector": name, "etf": etf, "last": None, "change_pct": None,
                        "change_pct_period": None,
                        "period": period, "quote_type": "unavailable"}
            last = q.last
            # A missing last price is not a 0 price: no last means no change
            # and the row is not labelled live.
            has_last = last is not None
            base: float | None = None
            if has_last:
                if base_date is None:
                    # 1D: the quote's previous close is the base.
                    base = q.close_prev or None
                else:
                    try:
                        base = _close_on_or_before(await _history(etf), base_date)
                    except Exception:
                        base = None
            chg_pct = (last / base - 1) * 100 if has_last and base else None
            return {
                "sector": name, "etf": etf, "last": last,
                "change_pct": chg_pct,
                "change_pct_period": period if chg_pct is not None else None,
                "period": period,
                "quote_type": "live" if has_last else "unavailable",
                "high_24h": q.high_24h, "low_24h": q.low_24h,
            }

        rows = _rank(list(await asyncio.gather(*(_one(n, e) for n, e in _SECTOR_ETFS.items()))))
        if not any(row.get("last") is not None or row.get("change_pct") is not None for row in rows):
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "Sector ETF quote provider returned no usable live quotes.",
                    "period": period,
                    "rows": _sector_template(period),
                    "next_actions": [
                        "Retry after the Yahoo quote throttle clears or connect a sector ETF quote provider.",
                        "Rows shown carry no values because the model has no price data.",
                        "Use the Live/Model control to switch modes intentionally.",
                    ],
                },
                sources=["yfinance", "sector_heatmap_model"],
                metadata={
                    "fallback": True,
                    "degraded": True,
                    "provider_errors": ["yfinance sector ETF quotes unavailable"],
                },
            )
        warnings: list[str] = []
        if base_date is not None:
            missing = [row["etf"] for row in rows if row.get("last") is not None and row.get("change_pct") is None]
            if missing:
                warnings.append(
                    f"{len(missing)} sector ETF(s) have no {period} base close in their daily history "
                    f"({', '.join(missing)}); their change is null, not zero"
                )
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok",
                "period": period,
                "change_pct_period": period,
                "rows": rows,
            },
            sources=["yfinance"],
            warnings=warnings,
            metadata={"live": True, "requested_period": period, "live_period": period},
        )
