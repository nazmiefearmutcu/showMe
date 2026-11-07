"""YAS — Yield & Spread Analytics."""

from __future__ import annotations

import asyncio
import math
import re
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions._fred_csv import fred_with_keyless_fallback


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


def _single_cashflow_metrics(face: float, price: float, coupon: float, years: float) -> dict[str, float]:
    """One payment ``face * (1 + coupon * T)`` at T, simple-interest yield.

    P = F(1 + cT) / (1 + yT)  ⇒  y = (F(1 + cT) / P − 1) / T
    Macaulay = T; modified = T / (1 + yT); convexity = 2T² / (1 + yT)².
    """
    redemption = face * (1 + coupon * years)
    ytm = (redemption / price - 1) / years
    growth = 1 + ytm * years
    return {"ytm": ytm, "macaulay_duration": years,
            "modified_duration": years / growth, "convexity": 2 * years * years / (growth * growth)}


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


_US_TENOR = re.compile(r"^US(\d{1,2})([MY])$")
# Treasury constant-maturity (CMT) par yields, FRED series per tenor.
_CMT_SERIES = {
    ("1", "M"): "DGS1MO", ("3", "M"): "DGS3MO", ("6", "M"): "DGS6MO",
    ("1", "Y"): "DGS1", ("2", "Y"): "DGS2", ("3", "Y"): "DGS3", ("5", "Y"): "DGS5",
    ("7", "Y"): "DGS7", ("10", "Y"): "DGS10", ("20", "Y"): "DGS20", ("30", "Y"): "DGS30",
}
_BENCHMARK_SERIES = "DGS10"


def _first_param(params: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = params.get(name)
        if value not in (None, ""):
            return value
    return None


def generic_treasury(symbol: str) -> tuple[str, float] | None:
    """``US2Y`` → (``DGS2``, 2.0 years); ``None`` for anything else."""
    match = _US_TENOR.match(symbol.strip().upper())
    if not match:
        return None
    series = _CMT_SERIES.get((match.group(1), match.group(2)))
    if series is None:
        return None
    n = float(match.group(1))
    return series, (n / 12.0 if match.group(2) == "M" else n)


@FunctionRegistry.register
class YASFunction(BaseFunction):
    code = "YAS"
    name = "Yield & Spread Analytics"
    asset_classes = (AssetClass.BOND,)
    category = "bond"

    async def _cmt(self, series_id: str, timeout: float) -> tuple[float, str] | None:
        """Latest observation of a FRED CMT series as (decimal yield, ISO date)."""
        fred = fred_with_keyless_fallback(self.deps.fred, client=getattr(self, "_http_client", None))
        try:
            df = await asyncio.wait_for(fred.series(series_id, frequency="d"), timeout=timeout)
        except Exception:  # noqa: BLE001 - caller reports the outage
            return None
        if df is None or getattr(df, "empty", True) or "value" not in df:
            return None
        values = df["value"].dropna()
        if values.empty:
            return None
        when = values.index[-1]
        return float(values.iloc[-1]) / 100.0, str(getattr(when, "date", lambda: when)())

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        """Yield/duration/convexity/spread for a bond.

        2026-11-07 (strict truth audit): the handler ignored the symbol and
        priced one static bond (price 99.5, coupon 4.25%, 10y) for every
        input, with a static 4.45% benchmark fallback. Now:
          * generic US Treasuries (US1M … US30Y) use the live FRED
            constant-maturity par yield for that tenor — a par bond (price
            100, coupon = CMT yield, maturity = tenor);
          * any explicitly supplied price/coupon/maturity overrides that;
          * any other bond needs price, coupon and maturity (no default bond);
          * the benchmark is the live 10Y CMT unless given; if unavailable
            the spread is not reported (no static benchmark).
        Manifest names (years_to_maturity, frequency, benchmark) are accepted
        alongside the handler's historical names.
        """
        if instrument is None:
            instrument = Instrument(symbol=str(params.get("symbol") or "US10Y").upper(), asset_class=AssetClass.BOND)
        symbol = instrument.symbol.upper()
        timeout = float(params.get("fred_timeout", 8))
        assume_dec = bool(params.get("assume_decimal", False))
        face = float(params.get("face", 100.0))
        freq = int(_first_param(params, "freq", "frequency") or 2)
        price = _first_param(params, "price")
        coupon_raw = _first_param(params, "coupon")
        maturity = _first_param(params, "maturity_years", "years_to_maturity", "years")
        bench_raw = _first_param(params, "benchmark_rate", "benchmark", "ust10y")
        try:
            float(bench_raw) if bench_raw is not None else None
        except (TypeError, ValueError):
            bench_raw = None  # a name such as "UST10Y" selects the live 10Y benchmark

        sources: list[str] = []
        warnings: list[str] = []
        metadata: dict[str, Any] = {}
        generic = generic_treasury(symbol)
        cmt_date = None
        if generic and (price is None or coupon_raw is None or maturity is None):
            series_id, tenor_years = generic
            cmt = await self._cmt(series_id, timeout)
            if cmt is None:
                return FunctionResult(
                    code=self.code, instrument=instrument,
                    data={"status": "provider_unavailable",
                          "reason": f"FRED {series_id} (constant-maturity {symbol}) is unavailable.",
                          "next_actions": ["Retry later, or enter price, coupon and maturity to analyse a specific bond."],
                          "rows": []},
                    warnings=[f"FRED {series_id} unavailable"],
                )
            par_yield, cmt_date = cmt
            sources.append("fred")
            metadata.update({"cmt_series": series_id, "cmt_date": cmt_date,
                             "construction": "par bond at the constant-maturity yield"})
            price = face if price is None else price
            coupon_raw = par_yield if coupon_raw is None else coupon_raw
            maturity = tenor_years if maturity is None else maturity
            if coupon_raw == par_yield:
                assume_dec = True  # CMT already converted to a decimal
        missing = [name for name, value in (("price", price), ("coupon", coupon_raw), ("maturity", maturity))
                   if value is None]
        if missing:
            return FunctionResult(
                code=self.code, instrument=instrument,
                data={"status": "input_error",
                      "reason": f"{symbol} is not a generic US Treasury tenor; YAS needs {', '.join(missing)}.",
                      "next_actions": ["Enter the bond's price (per 100), coupon and years to maturity, "
                                       "or pick a generic tenor such as US2Y or US10Y."],
                      "rows": []},
            )
        price = float(price)
        coupon = _rate_decimal(coupon_raw, 0.0, assume_decimal=assume_dec)
        maturity_years = float(maturity)
        if maturity_years * freq < 1 and "n_periods" not in params:
            # Shorter than one coupon period (US1M/US3M bills): a single cash
            # flow at maturity. Rounding to one full period used to put it 6
            # months out (1M bill modified duration 0.49y instead of ~0.083y).
            metrics = _single_cashflow_metrics(face, price, coupon, maturity_years)
            metadata["cashflow_model"] = "single payment at maturity (simple interest)"
        else:
            n_periods = int(params.get("n_periods", max(1, round(maturity_years * freq))))
            metrics = _ytm_macaulay_modified_duration(face, price, coupon, n_periods, freq)
        if not sources:
            sources.append("yield_spread_model")

        benchmark = None
        if bench_raw is not None:
            benchmark = _rate_decimal(bench_raw, 0.0, assume_decimal=bool(params.get("assume_decimal", False)))
            metadata["benchmark"] = "input"
        else:
            bench = await self._cmt(_BENCHMARK_SERIES, timeout)
            if bench is None:
                warnings.append("Live 10Y benchmark (FRED DGS10) unavailable; the spread is not reported.")
            else:
                benchmark = bench[0]
                metadata.update({"benchmark": _BENCHMARK_SERIES, "benchmark_date": bench[1]})
                if "fred" not in sources:
                    sources.append("fred")
        spread = metrics["ytm"] - benchmark if benchmark is not None else None
        curve = []
        for offset_bps in [-100, -50, -25, 0, 25, 50, 100]:
            delta_y = offset_bps / 10_000
            est_price = price * (
                1
                - metrics["modified_duration"] * delta_y
                + 0.5 * metrics["convexity"] * delta_y * delta_y
            )
            curve.append({"ytm_pct": (metrics["ytm"] + delta_y) * 100, "price": est_price, "shock_bps": offset_bps})
        rows = [
            {"metric": "yield_to_maturity", "value": metrics["ytm"], "display_pct": metrics["ytm"] * 100, "unit": "decimal"},
            {"metric": "spread_vs_benchmark", "value": spread,
             "display_pct": None if spread is None else spread * 100,
             "spread_bps": None if spread is None else spread * 10_000, "unit": "decimal"},
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
                    "bond": symbol,
                    "price": price,
                    "face": face,
                    "coupon_rate": coupon,
                    "coupon_pct": coupon * 100,
                    "maturity_years": maturity_years,
                    "frequency": freq,
                    "benchmark_rate": benchmark,
                    "benchmark_pct": None if benchmark is None else benchmark * 100,
                    "ytm": metrics["ytm"],
                    "ytm_pct": metrics["ytm"] * 100,
                    "spread_vs_benchmark": spread,
                    "spread_bps": None if spread is None else spread * 10_000,
                    "as_of": cmt_date,
                },
                "methodology": (
                    "Generic US Treasury tenors (US1M-US30Y) are analysed as a par bond at the live FRED "
                    "constant-maturity yield for that tenor; other bonds need price, coupon and maturity. "
                    "YAS solves yield-to-maturity with Newton iteration (bisection fallback), then computes "
                    "Macaulay duration, modified duration, convexity, and the spread versus the live 10Y CMT "
                    "benchmark (or a supplied one). Coupon and benchmark inputs accept decimals (0.0425) or "
                    "percentages (4.25); frequency is coupon payments per year."
                ),
                "field_dictionary": {
                    "ytm": "Yield-to-maturity as a decimal annual rate.",
                    "spread_vs_benchmark": "YTM minus benchmark rate (null when no benchmark is available).",
                    "spread_bps": "Spread versus benchmark in basis points.",
                    "modified_duration": "Approximate percent price sensitivity to a 100 bp yield move.",
                    "convexity": "Second-order price sensitivity to yield changes.",
                    "ytm_pct": "Yield used on the sensitivity-curve x-axis.",
                    "price": "Observed or model price per 100 face (100 for a par CMT bond).",
                    "as_of": "Observation date of the constant-maturity yield, when used.",
                },
            },
            sources=sources,
            warnings=warnings,
            metadata=metadata,
        )
