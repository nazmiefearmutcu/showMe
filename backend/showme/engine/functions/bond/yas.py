"""YAS — Yield & Spread Analytics."""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


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


def _rate_decimal(value: Any, fallback: float) -> float:
    rate = float(value if value not in (None, "") else fallback)
    return rate / 100 if abs(rate) > 1 else rate


@FunctionRegistry.register
class YASFunction(BaseFunction):
    code = "YAS"
    name = "Yield & Spread Analytics"
    asset_classes = (AssetClass.BOND,)
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            instrument = Instrument(symbol=str(params.get("symbol") or "US10Y").upper(), asset_class=AssetClass.BOND)
        face = float(params.get("face", 100.0))
        price = float(params.get("price", 99.5))
        coupon = _rate_decimal(params.get("coupon"), 0.0425)
        maturity_years = float(params.get("maturity_years", params.get("years", 10)))
        freq = int(params.get("freq", 2))
        n_periods = int(params.get("n_periods", max(1, round(maturity_years * freq))))
        metrics = _ytm_macaulay_modified_duration(face, price, coupon, n_periods, freq)
        benchmark = _rate_decimal(params.get("benchmark_rate", params.get("ust10y")), 0.0445)
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
        curve = []
        for offset_bps in [-100, -50, -25, 0, 25, 50, 100]:
            ytm = metrics["ytm"] + offset_bps / 10_000
            # Simple duration/convexity approximation around current price.
            delta_y = ytm - metrics["ytm"]
            est_price = price * (
                1
                - metrics["modified_duration"] * delta_y
                + 0.5 * metrics["convexity"] * delta_y * delta_y
            )
            curve.append({"ytm_pct": ytm * 100, "price": est_price, "shock_bps": offset_bps})
        rows = [
            {"metric": "yield_to_maturity", "value": metrics["ytm"], "display_pct": metrics["ytm"] * 100, "unit": "decimal"},
            {"metric": "spread_vs_benchmark", "value": spread, "display_pct": spread * 100, "spread_bps": spread * 10_000, "unit": "decimal"},
            {"metric": "macaulay_duration", "value": metrics["macaulay_duration"], "unit": "years"},
            {"metric": "modified_duration", "value": metrics["modified_duration"], "unit": "years"},
            {"metric": "convexity", "value": metrics["convexity"], "unit": "price convexity"},
        ]
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "rows": rows,
                "curve": curve,
                "summary": {
                    "bond": instrument.symbol,
                    "price": price,
                    "face": face,
                    "coupon_rate": coupon,
                    "coupon_pct": coupon * 100,
                    "maturity_years": maturity_years,
                    "frequency": freq,
                    "benchmark_rate": benchmark,
                    "benchmark_pct": benchmark * 100,
                    "ytm": metrics["ytm"],
                    "ytm_pct": metrics["ytm"] * 100,
                    "spread_vs_benchmark": spread,
                    "spread_bps": spread * 10_000,
                },
                "methodology": "YAS solves yield-to-maturity with Newton iteration, then computes Macaulay duration, modified duration, convexity, and spread versus the selected benchmark. Coupon and benchmark inputs accept either decimals (0.0425) or percentages (4.25); frequency is coupon payments per year.",
                "field_dictionary": {
                    "ytm": "Yield-to-maturity as a decimal annual rate.",
                    "spread_vs_benchmark": "YTM minus benchmark rate, both normalized to decimal annual rates.",
                    "spread_bps": "Spread versus benchmark in basis points.",
                    "modified_duration": "Approximate percent price sensitivity to a 100 bp yield move.",
                    "convexity": "Second-order price sensitivity to yield changes.",
                    "ytm_pct": "Yield used on the sensitivity-curve x-axis.",
                    "price": "Observed or model price per 100 face.",
                },
            },
            sources=sources,
            metadata={"note": "closed-form yield analytics; set live_benchmark=true for FRED"},
        )
