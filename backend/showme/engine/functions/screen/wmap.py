"""MAP — World market heatmap (major equity index ETFs)."""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


_COUNTRY_ETFS = {
    "US":      "SPY",
    "EU":      "VGK",
    "DE":      "EWG",
    "GB":      "EWU",
    "FR":      "EWQ",
    "IT":      "EWI",
    "ES":      "EWP",
    "JP":      "EWJ",
    "CN":      "FXI",
    "IN":      "INDA",
    "BR":      "EWZ",
    "MX":      "EWW",
    "TR":      "TUR",
    "ZA":      "EZA",
    "AU":      "EWA",
    "CA":      "EWC",
    "KR":      "EWY",
    "TW":      "EWT",
    "HK":      "EWH",
    "ID":      "EIDO",
    "SA":      "KSA",
    "AR":      "ARGT",
    "VN":      "VNM",
    "PL":      "EPOL",
    "RU":      "RSX",
}


def _map_template() -> list[dict[str, Any]]:
    rows = []
    for i, (country, etf) in enumerate(_COUNTRY_ETFS.items()):
        rows.append({
            "country": country,
            "etf": etf,
            "last": round(50 + i * 1.7, 2),
            "change_pct": round(((i % 9) - 4) * 0.18, 3),
            "period": "1D",
            "quote_type": "model",
        })
    rows.sort(key=lambda x: x.get("change_pct") or -999, reverse=True)
    return rows


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


@FunctionRegistry.register
class MAPFunction(BaseFunction):
    code = "MAP"
    name = "World Market Heatmap"
    category = "screen"
    description = "MSCI single-country ETF day-change heatmap (25+ countries)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        live = _truthy(params.get("live_screen")) or _truthy(params.get("live"))
        if not live:
            return FunctionResult(code=self.code, instrument=None,
                                  data={
                                      "status": "model",
                                      "reason": "Deterministic country ETF model selected; values are not live market quotes.",
                                      "period": "1D",
                                      "rows": _map_template(),
                                  },
                                  sources=["world_market_model"])
        if not self.deps.yfinance:
            return FunctionResult(code=self.code, instrument=None,
                                  data={
                                      "status": "provider_unavailable",
                                      "reason": "No quote provider is configured for country ETF heatmap quotes.",
                                      "period": "1D",
                                      "rows": _map_template(),
                                      "next_actions": [
                                          "Switch MAP to Model mode for deterministic fallback values.",
                                          "Connect a quote provider to enable live country ETF day changes.",
                                      ],
                                  },
                                  sources=["world_market_model"],
                                  metadata={"fallback": True, "degraded": True})
        timeout = max(1.0, min(float(params.get("quote_timeout", 3)), 5.0))
        screen_timeout = max(2.0, min(float(params.get("screen_timeout", 5)), 8.0))

        async def _one(country: str, etf: str):
            try:
                inst = Instrument(symbol=etf, asset_class=AssetClass.ETF)
                q = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.QUOTE,
                        instrument=inst,
                        extra={"timeout": timeout},
                    )),
                    timeout=timeout + 1,
                )
                last = q.last; prev = q.close_prev
                chg = ((last or 0) / (prev or 1) - 1) * 100 if prev else None
                return {"country": country, "etf": etf,
                         "last": last, "change_pct": chg,
                         "period": "1D", "quote_type": "live"}
            except Exception:
                return {"country": country, "etf": etf,
                         "last": None, "change_pct": None,
                         "period": "1D", "quote_type": "unavailable"}
        tasks = [asyncio.create_task(_one(c, e)) for c, e in _COUNTRY_ETFS.items()]
        done, pending = await asyncio.wait(tasks, timeout=screen_timeout)
        for task in pending:
            task.cancel()
        rows = [task.result() for task in done if not task.cancelled()]
        rows = [row for row in rows if row.get("last") is not None]
        if not rows:
            fallback_rows = _map_template()
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "World ETF quote provider returned no usable live rows.",
                    "period": "1D",
                    "rows": fallback_rows,
                    "next_actions": [
                        "Retry MAP after the public quote provider recovers.",
                        "Rows shown are a deterministic country ETF model, not live quotes.",
                        "Use the Live/Model control to switch to the deterministic fallback intentionally.",
                    ],
                },
                sources=["yfinance", "world_market_model"],
                metadata={
                    "fallback": True,
                    "degraded": True,
                    "provider_errors": ["yfinance world ETF quotes unavailable"],
                },
            )
        rows.sort(key=lambda x: x.get("change_pct") or -999, reverse=True)
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={"status": "ok", "period": "1D", "rows": rows},
            sources=["yfinance"],
        )
