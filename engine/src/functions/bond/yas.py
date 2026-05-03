"""YAS — Yield & Spread Analytics."""

from __future__ import annotations

import asyncio
import math
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


def _ytm_macaulay_modified_duration(face: float, price: float, coupon: float,
                                     n_periods: int, freq: int) -> dict[str, float]:
    """Newton solver — 1D YTM + duration. Faz 4'te QuantLib'e geçilebilir."""
    c = coupon / freq
    y = 0.05 / freq
    for _ in range(50):
        pv = sum(c * face / (1 + y) ** k for k in range(1, n_periods + 1))
        pv += face / (1 + y) ** n_periods
        d = -sum(k * c * face / (1 + y) ** (k + 1) for k in range(1, n_periods + 1))
        d -= n_periods * face / (1 + y) ** (n_periods + 1)
        diff = pv - price
        if abs(diff) < 1e-8 or d == 0:
            break
        y -= diff / d
    ytm = y * freq
    pv_check = sum(c * face / (1 + y) ** k for k in range(1, n_periods + 1)) + face / (1 + y) ** n_periods
    macaulay = sum(k * (c * face) / (1 + y) ** k for k in range(1, n_periods + 1))
    macaulay += n_periods * face / (1 + y) ** n_periods
    macaulay /= pv_check
    macaulay /= freq
    modified = macaulay / (1 + ytm / freq)
    convexity = sum(k * (k + 1) * c * face / (1 + y) ** (k + 2) for k in range(1, n_periods + 1))
    convexity += n_periods * (n_periods + 1) * face / (1 + y) ** (n_periods + 2)
    convexity /= pv_check
    convexity /= freq ** 2
    return {"ytm": ytm, "macaulay_duration": macaulay,
            "modified_duration": modified, "convexity": convexity}


@FunctionRegistry.register
class YASFunction(BaseFunction):
    code = "YAS"
    name = "Yield & Spread Analytics"
    asset_classes = (AssetClass.BOND,)
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        face = float(params.get("face", 100.0))
        price = float(params.get("price", 99.5))
        coupon = float(params.get("coupon", 0.04))
        n_periods = int(params.get("n_periods", 20))
        freq = int(params.get("freq", 2))
        metrics = _ytm_macaulay_modified_duration(face, price, coupon, n_periods, freq)
        benchmark = float(params.get("benchmark_rate", params.get("ust10y", 0.0445)))
        sources = ["yield_spread_model"]
        if (params.get("live_benchmark") or params.get("live")) and self.deps.fred:
            try:
                df = await asyncio.wait_for(
                    self.deps.fred.series("DGS10", frequency="d"),
                    timeout=float(params.get("fred_timeout", 5)),
                )
                bench = float(df["value"].iloc[-1]) / 100 if not df.empty else None
                if bench is not None:
                    benchmark = bench
                    sources = ["fred"]
            except Exception:
                pass
        spread = metrics["ytm"] - benchmark
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={**metrics, "spread_vs_ust10y": spread, "price": price, "face": face,
                   "coupon": coupon, "n_periods": n_periods, "freq": freq,
                   "benchmark_rate": benchmark},
            sources=sources,
            metadata={"note": "closed-form yield analytics; set live_benchmark=true for FRED"},
        )
