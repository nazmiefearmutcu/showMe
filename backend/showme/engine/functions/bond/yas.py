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
        0.5 scaling). 30y 4% quarterly par bond convexity is ~421 years^2
        (annual-yield convention), not the inflated ~700.
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
    # normalized by PV. Final freq^2 makes the result (1/P) d²P/dy² in
    # years^2 for an annual yield; the 30y 4% quarterly par bond gives
    # ≈ 421 (checked by finite difference), not the inflated ~700.
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


_AMBIGUOUS_RATE_LOW = 0.2  # matches portfolio/greeks _MAX_PLAIN_DECIMAL_RATE (XCON-2)


def _ambiguous_rate(value: Any, assume_decimal: bool) -> bool:
    """True for a caller rate in (0.2, 1] with no stated unit: percent or decimal?"""
    if assume_decimal or value in (None, ""):
        return False
    try:
        number = abs(float(value))
    except (TypeError, ValueError):
        return False
    return _AMBIGUOUS_RATE_LOW < number <= 1.0


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


def _benchmark_series(name: str) -> str | None:
    """FRED CMT series for a named US benchmark (``UST2Y``/``US2Y``); ``None`` when none is live."""
    key = str(name).strip().upper()
    if key.startswith("UST"):
        key = "US" + key[3:]
    generic = generic_treasury(key)
    return generic[0] if generic else None


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
        bench_name: str | None = None
        if bench_raw is not None:
            try:
                float(bench_raw)
            except (TypeError, ValueError):
                bench_name = str(bench_raw)  # a name such as "UST10Y" or "DBR10Y"
                bench_raw = None
        # XCON-2: a rate in (0.2, 1] is ambiguous (0.5 is 0.5% or 50%). Refuse it with an
        # explicit state unless the caller states the unit with assume_decimal.
        user_assume = bool(params.get("assume_decimal", False))
        for rate_name, rate_value in (("coupon", coupon_raw), ("benchmark", bench_raw)):
            if _ambiguous_rate(rate_value, user_assume):
                value = float(rate_value)
                return FunctionResult(
                    code=self.code, instrument=instrument,
                    data={"status": "input_error",
                          "reason": (f"{rate_name} {value:g} is ambiguous: as a percent it is {value:g}%, "
                                     f"as a decimal it is {value * 100:g}%. Enter a percent above 1 "
                                     f"(e.g. 4.25) or the decimal with assume_decimal=true (e.g. 0.005)."),
                          "next_actions": [f"Restate the {rate_name} as a percent above 1, or pass the "
                                           "decimal with assume_decimal=true."],
                          "rows": []},
                    warnings=[f"{rate_name} {value:g} is ambiguous; not priced"],
                )

        sources: list[str] = []
        warnings: list[str] = []
        metadata: dict[str, Any] = {}
        generic = generic_treasury(symbol)
        cmt_date = None
        cmt_used = False  # the bond's terms came from a live FRED CMT yield
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
            cmt_used = True
            metadata.update({"cmt_series": series_id, "cmt_date": cmt_date,
                             "construction": "par bond at the constant-maturity yield"})
            # Quotes are per 100 of face: a par bond is priced at 100, whatever face is.
            price = 100.0 if price is None else price
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
        price = float(price)  # quoted per 100 of face (seed: "Quoted clean price (per 100 face)")
        # YAS#1: cashflows are face-scaled, so the solver must compare them with the
        # price in currency units (price per 100 x face / 100), not with the per-100 quote.
        price_amount = price * face / 100.0
        coupon = _rate_decimal(coupon_raw, 0.0, assume_decimal=assume_dec)
        maturity_years = float(maturity)
        if maturity_years * freq < 1 and "n_periods" not in params:
            # Shorter than one coupon period (US1M/US3M bills): a single cash
            # flow at maturity. Rounding to one full period used to put it 6
            # months out (1M bill modified duration 0.49y instead of ~0.083y).
            metrics = _single_cashflow_metrics(face, price_amount, coupon, maturity_years)
            metadata["cashflow_model"] = "single payment at maturity (simple interest)"
        else:
            n_periods = int(params.get("n_periods", max(1, round(maturity_years * freq))))
            metrics = _ytm_macaulay_modified_duration(face, price_amount, coupon, n_periods, freq)
        if not sources:
            sources.append("yield_spread_model")

        # YAS#2: every benchmark states what it is, so the pane never shows a bare "BENCH x%".
        benchmark = None
        bench_series: str | None = None
        if bench_raw is not None:
            benchmark = _rate_decimal(bench_raw, 0.0, assume_decimal=bool(params.get("assume_decimal", False)))
            metadata["benchmark"] = "input"
            bench_label = "custom rate"
        elif bench_name is not None:
            # A named benchmark is the series it names, never a silent US 10Y substitute.
            metadata["benchmark_requested"] = bench_name
            series = _benchmark_series(bench_name)
            if series is None:
                metadata["benchmark"] = None
                bench_label = f"{bench_name} · no live series"
                warnings.append(
                    f"Benchmark {bench_name} has no live series in this build; the spread is not "
                    "reported (no US 10Y substitute is used)."
                )
            else:
                bench = await self._cmt(series, timeout)
                bench_label = f"{bench_name.upper()} · FRED {series}"
                if bench is None:
                    metadata["benchmark"] = None
                    bench_label += " unavailable"
                    warnings.append(f"FRED {series} ({bench_name}) benchmark unavailable; the spread is not reported.")
                else:
                    benchmark = bench[0]
                    bench_series = series
                    metadata.update({"benchmark": series, "benchmark_date": bench[1]})
                    if "fred" not in sources:
                        sources.append("fred")
        else:
            # No benchmark named: the 10Y CMT is used, and the label says it is the default.
            bench = await self._cmt(_BENCHMARK_SERIES, timeout)
            bench_label = f"UST10Y (default) · FRED {_BENCHMARK_SERIES}"
            if bench is None:
                bench_label += " unavailable"
                warnings.append("Live 10Y benchmark (FRED DGS10) unavailable; the spread is not reported.")
            else:
                benchmark = bench[0]
                bench_series = _BENCHMARK_SERIES
                metadata.update({"benchmark": _BENCHMARK_SERIES, "benchmark_date": bench[1]})
                if "fred" not in sources:
                    sources.append("fred")
        metadata["benchmark_label"] = bench_label
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
            {"metric": "convexity", "value": metrics["convexity"], "unit": "years^2"},
        ]
        # YAS#5: the mode follows the data path. A bond built from a live CMT
        # yield is modeled; one priced from user-supplied terms is user_input.
        data_mode = "modeled" if cmt_used else "user_input"
        metadata["data_mode"] = data_mode
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "rows": rows,
                "curve": curve,
                "data_mode": data_mode,
                "summary": {
                    "bond": symbol,
                    "price": price,
                    "price_amount": price_amount,
                    "face": face,
                    "coupon_rate": coupon,
                    "coupon_pct": coupon * 100,
                    "maturity_years": maturity_years,
                    "frequency": freq,
                    "benchmark_rate": benchmark,
                    "benchmark_pct": None if benchmark is None else benchmark * 100,
                    "benchmark_label": bench_label,
                    "benchmark_series": bench_series,
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
                    "benchmark by default, a named UST tenor's live CMT (UST2Y, UST5Y, UST10Y, UST30Y), or a supplied "
                    "rate; a named benchmark with no live series reports no spread. Coupon and benchmark inputs accept decimals (0.0425) or "
                    "percentages (4.25); frequency is coupon payments per year."
                ),
                "field_dictionary": {
                    "ytm": "Yield-to-maturity as a decimal annual rate.",
                    "spread_vs_benchmark": "YTM minus benchmark rate (null when no benchmark is available).",
                    "spread_bps": "Spread versus benchmark in basis points.",
                    "modified_duration": "Approximate percent price sensitivity to a 100 bp yield move.",
                    "convexity": "Second-order yield sensitivity (1/P)·d²P/dy² for an annual yield, in years^2 (about 421 for a 30y 4% quarterly par bond).",
                    "data_mode": "modeled when the bond is a par bond at a live FRED constant-maturity yield; user_input when price, coupon and maturity were supplied.",
                    "ytm_pct": "Yield used on the sensitivity-curve x-axis.",
                    "price": "Observed or model price per 100 face (100 for a par CMT bond).",
                    "as_of": "Observation date of the constant-maturity yield, when used.",
                },
            },
            sources=sources,
            warnings=warnings,
            metadata=metadata,
        )
