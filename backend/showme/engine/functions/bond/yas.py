"""YAS — Yield & Spread Analytics."""

from __future__ import annotations

import asyncio
import math
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


def _bond_pv(face: float, c: float, y: float, n_periods: int) -> float:
    """Present value of a fixed-coupon bond at per-period yield ``y``."""
    if y <= -1.0:
        return float("inf")
    return sum(c * face / (1 + y) ** k for k in range(1, n_periods + 1)) + \
        face / (1 + y) ** n_periods


def _ytm_bisection(face: float, price: float, c: float, n_periods: int,
                   y_low: float, y_high: float, tol: float = 1e-10,
                   max_iter: int = 200) -> float:
    """Fallback bisection — used when Newton diverges on distressed bonds.

    D03-2026-05-24 (H12): caller previously had no fallback so distressed
    bonds (yield > ~50%) blew up. We now bracket the root in
    [y_low, y_high] and bisect — convergence is guaranteed if PV(y_low) and
    PV(y_high) bracket ``price``.
    """
    f_lo = _bond_pv(face, c, y_low, n_periods) - price
    f_hi = _bond_pv(face, c, y_high, n_periods) - price
    if f_lo * f_hi > 0:
        # No root in bracket; return whichever endpoint is closer.
        return y_low if abs(f_lo) < abs(f_hi) else y_high
    for _ in range(max_iter):
        mid = 0.5 * (y_low + y_high)
        f_mid = _bond_pv(face, c, mid, n_periods) - price
        if abs(f_mid) < tol or (y_high - y_low) < tol:
            return mid
        if f_lo * f_mid < 0:
            y_high = mid
        else:
            y_low = mid
            f_lo = f_mid
    return 0.5 * (y_low + y_high)


def _ytm_macaulay_modified_duration(face: float, price: float, coupon: float,
                                     n_periods: int, freq: int) -> dict[str, float]:
    """Newton solver — 1D YTM + duration with bisection fallback.

    D03-2026-05-24 (H12+H13+H14):
      H12: divergence-trapped Newton + bisection fallback for distressed
        bonds (|y_period| > 2.0 trips the trap, i.e. annualized >200%).
      H13: convexity formula keeps consistent per-period y and ``freq^2``
        normalization — quarterly bonds (freq=4) used to drift because
        the (1+y)^(k+2) discounting was already per-period but the freq
        scaling at the end double-counted.
      H14: convexity normalization stays inside the formula (no extra
        0.5 scaling). 30y 4% bond convexity → ~200, not ~700.
    """
    c = coupon / freq
    # Initial guess: coupon yield if reasonable, else 5%.
    if price > 0 and abs(coupon / price * face) < 1:
        y = (coupon / freq)
    else:
        y = 0.05 / freq
    newton_converged = False
    for _ in range(50):
        pv = _bond_pv(face, c, y, n_periods)
        d = -sum(k * c * face / (1 + y) ** (k + 1) for k in range(1, n_periods + 1))
        d -= n_periods * face / (1 + y) ** (n_periods + 1)
        diff = pv - price
        if abs(diff) < 1e-8 or d == 0:
            newton_converged = True
            break
        step = diff / d
        y_new = y - step
        # H12: divergence trap — Newton blew up if |y_period| > 2.0
        # (annualized > 2*freq, i.e. >400% for semi-annual). Bail out.
        if not math.isfinite(y_new) or abs(y_new) > 2.0:
            break
        y = y_new
    if not newton_converged:
        # H12: bisection fallback. Cover -1% to 500% annual yield bracket.
        y = _ytm_bisection(face, price, c, n_periods,
                           y_low=-0.01 / freq, y_high=5.0 / freq)
    ytm = y * freq
    pv_check = _bond_pv(face, c, y, n_periods)
    macaulay = sum(k * (c * face) / (1 + y) ** k for k in range(1, n_periods + 1))
    macaulay += n_periods * face / (1 + y) ** n_periods
    macaulay /= pv_check
    macaulay /= freq
    modified = macaulay / (1 + ytm / freq)
    # H13+H14: convexity. Per-period cashflow PV weighted by k*(k+1), then
    # discounted by an extra (1+y)^2 (i.e. k+2 in the denominator), then
    # normalized by PV. Final freq^2 makes the result an annualized
    # second-derivative; the 30y 4% bond now yields convexity ≈ 200 instead
    # of the inflated ~700.
    convexity = sum(k * (k + 1) * c * face / (1 + y) ** (k + 2)
                    for k in range(1, n_periods + 1))
    convexity += n_periods * (n_periods + 1) * face / (1 + y) ** (n_periods + 2)
    convexity /= pv_check
    convexity /= freq ** 2
    return {"ytm": ytm, "macaulay_duration": macaulay,
            "modified_duration": modified, "convexity": convexity}


def _rate_decimal(value: Any, fallback: float, *,
                  assume_decimal: bool = False) -> float:
    """Coerce a rate input to decimal form.

    D03-2026-05-24 (H15): old heuristic ``abs(rate) > 1 -> /100`` warped
    distressed yields (150% input -> 1.5 decimal = 15000% catastrophe).
    The heuristic is preserved for backward compat (most callers still
    send percent), but ``assume_decimal=True`` skips the heuristic and
    treats the input as already-decimal. Future contract: callers should
    always pass decimals.
    """
    rate = float(value if value not in (None, "") else fallback)
    if assume_decimal:
        return rate
    # Legacy heuristic: |x| > 1 means percent (e.g. 4.5 -> 0.045). This
    # WILL misfire on yields > 100% annual — pass assume_decimal=True for
    # distressed/junk bonds.
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
        # H15: assume_decimal=true bypasses the legacy "x>1 → /100" auto-
        # convert and lets callers send distressed yields >100% as raw
        # decimals (e.g. 1.50 for 150% annual yield).
        assume_dec = bool(params.get("assume_decimal", False))
        coupon = _rate_decimal(params.get("coupon"), 0.0425,
                               assume_decimal=assume_dec)
        maturity_years = float(params.get("maturity_years", params.get("years", 10)))
        freq = int(params.get("freq", 2))
        n_periods = int(params.get("n_periods", max(1, round(maturity_years * freq))))
        metrics = _ytm_macaulay_modified_duration(face, price, coupon, n_periods, freq)
        benchmark = _rate_decimal(params.get("benchmark_rate", params.get("ust10y")),
                                  0.0445, assume_decimal=assume_dec)
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
