"""SECT — Sector Heatmap (S&P 500 + global sector ETF performance)."""

from __future__ import annotations

import asyncio
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


_PERIOD_FACTORS = {
    "1D": 1.0,
    "MTD": 2.4,
    "QTD": 4.6,
    "YTD": 8.8,
}


def _period_param(params: dict[str, Any]) -> str:
    raw = str(params.get("period") or params.get("range") or "1D").strip().upper()
    aliases = {"DAY": "1D", "D": "1D", "MONTH": "MTD", "QUARTER": "QTD", "YEAR": "YTD"}
    return aliases.get(raw, raw if raw in _PERIOD_FACTORS else "1D")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _sector_template(period: str = "1D") -> list[dict[str, Any]]:
    changes = {
        "Technology": 0.42,
        "Financials": 0.18,
        "Energy": -0.21,
        "Healthcare": 0.09,
        "Industrials": 0.14,
        "Consumer Discretionary": 0.31,
        "Consumer Staples": -0.04,
        "Utilities": -0.12,
        "Materials": 0.06,
        "Real Estate": -0.18,
        "Communication Services": 0.24,
    }
    factor = _PERIOD_FACTORS.get(period, 1.0)
    rows = [
        {"sector": name, "etf": etf, "last": 100 + i,
         "change_pct": round(changes.get(name, 0.0) * factor, 3),
         "period": period,
         "quote_type": "model",
         "high_24h": 101 + i, "low_24h": 99 + i}
        for i, (name, etf) in enumerate(_SECTOR_ETFS.items())
    ]
    rows.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
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
                                      "reason": "Deterministic sector ETF model selected; values are not live market quotes.",
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
                                          "Switch SECT to Model mode for deterministic fallback values.",
                                          "Connect a sector ETF quote provider to enable live period changes.",
                                      ],
                                  },
                                  sources=["sector_heatmap_model"],
                                  metadata={"fallback": True, "degraded": True})
        async def _one(name: str, etf: str):
            try:
                inst = Instrument(symbol=etf, asset_class=AssetClass.ETF)
                q = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.QUOTE,
                        instrument=inst,
                        extra={"timeout": float(params.get("quote_timeout", 1.25))},
                    )),
                    timeout=float(params.get("quote_timeout", 1.25)) + 0.25,
                )
                last = q.last; prev = q.close_prev
                chg_pct = ((last or 0) / (prev or 1) - 1) * 100 if prev else None
                return {
                    "sector": name, "etf": etf, "last": last,
                    "change_pct": chg_pct,
                    "period": "1D",
                    "quote_type": "live",
                    "high_24h": q.high_24h, "low_24h": q.low_24h,
                }
            except Exception:
                return {"sector": name, "etf": etf, "last": None, "change_pct": None,
                        "period": period, "quote_type": "unavailable"}
        rows = await asyncio.gather(*(_one(n, e) for n, e in _SECTOR_ETFS.items()))
        rows.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
        if not any(row.get("last") is not None or row.get("change_pct") is not None for row in rows):
            fallback_rows = _sector_template(period)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "Sector ETF quote provider returned no usable live quotes.",
                    "period": period,
                    "rows": fallback_rows,
                    "next_actions": [
                        "Retry after the Yahoo quote throttle clears or connect a sector ETF quote provider.",
                        "Rows shown are a deterministic sector ETF model, not live quotes.",
                        "Use the Live/Model control to switch to the deterministic fallback intentionally.",
                    ],
                },
                sources=["yfinance", "sector_heatmap_model"],
                metadata={
                    "fallback": True,
                    "degraded": True,
                    "provider_errors": ["yfinance sector ETF quotes unavailable"],
                },
            )
        return FunctionResult(
            code=self.code, instrument=None, data={"status": "ok", "period": "1D", "rows": rows},
            sources=["yfinance"],
        )
