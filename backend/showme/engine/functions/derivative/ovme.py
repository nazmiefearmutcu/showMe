"""OVME — Option Valuation (Black-Scholes + Greeks)."""

from __future__ import annotations

import math
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _bs_price(S: float, K: float, T: float, r: float, sigma: float, q: float, is_call: bool) -> dict[str, float]:
    """Black-Scholes-Merton with continuous dividend yield q.

    C2 fix: previously ``math.log(S / K)`` would raise ``ValueError: math
    domain error`` when ``S <= 0`` or ``K <= 0`` (negative/zero prices). The
    pre-flight guard now covers all four invalid-input cases by emitting a
    NaN-filled result with an ``error`` marker so the caller can surface a
    structured warning instead of crashing the route.
    """
    nan = float("nan")
    if S <= 0 or K <= 0:
        return {
            "price": nan, "delta": nan, "gamma": nan, "theta": nan,
            "vega": nan, "rho": nan, "d1": nan, "d2": nan,
            "error": f"invalid_inputs: S and K must be > 0 (got S={S}, K={K})",
        }
    if T <= 0 or sigma <= 0:
        # D03-2026-05-24: explicit intrinsic delta cases. Old code returned
        # 0 for ITM puts (S<K) because the conditional only matched calls.
        intrinsic = max((S - K), 0.0) if is_call else max((K - S), 0.0)
        if is_call:
            if S > K:
                delta = 1.0
            elif S < K:
                delta = 0.0
            else:
                delta = 0.5
        else:
            if S < K:
                delta = -1.0
            elif S > K:
                delta = 0.0
            else:
                delta = -0.5
        return {"price": intrinsic, "delta": delta,
                "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    def n_cdf(x: float) -> float:
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    def n_pdf(x: float) -> float:
        return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

    if is_call:
        price = S * math.exp(-q * T) * n_cdf(d1) - K * math.exp(-r * T) * n_cdf(d2)
        delta = math.exp(-q * T) * n_cdf(d1)
        rho = K * T * math.exp(-r * T) * n_cdf(d2) / 100
    else:
        price = K * math.exp(-r * T) * n_cdf(-d2) - S * math.exp(-q * T) * n_cdf(-d1)
        delta = -math.exp(-q * T) * n_cdf(-d1)
        rho = -K * T * math.exp(-r * T) * n_cdf(-d2) / 100
    gamma = math.exp(-q * T) * n_pdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * math.exp(-q * T) * n_pdf(d1) * math.sqrt(T) / 100
    # D03-2026-05-24: theta call vs put now split into explicit branches.
    # Previous (1 if is_call else -1) multiplier on the q-term gave the
    # correct answer for the q=0 case by accident but the formula structure
    # was fragile. Hull eq 17.4: call theta has +q*S*e^(-qT)*N(d1); put
    # has -q*S*e^(-qT)*N(-d1).
    common = -S * sigma * math.exp(-q * T) * n_pdf(d1) / (2 * math.sqrt(T))
    if is_call:
        theta = (
            common
            - r * K * math.exp(-r * T) * n_cdf(d2)
            + q * S * math.exp(-q * T) * n_cdf(d1)
        ) / 365
    else:
        theta = (
            common
            + r * K * math.exp(-r * T) * n_cdf(-d2)
            - q * S * math.exp(-q * T) * n_cdf(-d1)
        ) / 365
    return {"price": price, "delta": delta, "gamma": gamma,
            "theta": theta, "vega": vega, "rho": rho,
            "d1": d1, "d2": d2}


@FunctionRegistry.register
class OVMEFunction(BaseFunction):
    code = "OVME"
    name = "Option Valuation"
    asset_classes = (AssetClass.DERIVATIVE,)
    category = "derivative"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        S = float(params.get("spot", 100))
        K = float(params.get("strike", 100))
        T = float(params.get("years_to_expiry", 0.25))
        sigma = float(params.get("vol", 0.25))
        # D03-2026-05-24 (H11): r used to be hardcoded 0.045; optional FRED
        # hook lets callers pass `live_rate=true` to pull DGS1 instead.
        r = float(params.get("rate", 0.045))
        q = float(params.get("div_yield", 0.0))
        sources_list = ["black_scholes_formula"]
        if _truthy(params.get("live_rate")) and getattr(self.deps, "fred", None) is not None:
            try:
                df = await self.deps.fred.series("DGS1", frequency="d")
                live_r = float(df["value"].iloc[-1]) / 100 if not df.empty else None
                if live_r is not None and math.isfinite(live_r):
                    r = live_r
                    if "fred" not in sources_list:
                        sources_list.append("fred")
            except Exception:
                pass
        # D03-2026-05-24 (C4): Garman-Kohlhagen FX option mapping. For FX,
        # q = foreign currency rate, r = domestic; the BS formula then
        # accepts the same shape.
        option_kind = (params.get("option_type") or params.get("opt_type") or "equity").lower()
        if option_kind in {"fx", "currency"}:
            r_dom = params.get("r_domestic")
            r_for = params.get("r_foreign")
            if r_dom is not None:
                r = float(r_dom)
            if r_for is not None:
                q = float(r_for)
        opt_type = (params.get("type") or "CALL").upper()
        is_call = opt_type == "CALL"
        model = (params.get("model") or "bs").lower()
        result = _bs_price(S, K, T, r, sigma, q, is_call)
        # C2 fix: if S/K invalid, _bs_price now returns an ``error`` marker
        # and NaN sensitivities. Skip the curve generation in that case so
        # the caller still gets a structured envelope with the error.
        input_error = result.get("error") if isinstance(result, dict) else None
        sensitivity: list[dict[str, float]] = []
        if not input_error:
            for step in range(51):
                s = S * (0.75 + step * 0.01)
                priced = _bs_price(s, K, T, r, sigma, q, is_call)
                intrinsic = max(s - K, 0.0) if is_call else max(K - s, 0.0)
                sensitivity.append({
                    "spot": s,
                    "price": priced["price"],
                    "intrinsic": intrinsic,
                    "time_value": priced["price"] - intrinsic,
                    "delta": priced["delta"],
                })
        rows = [
            {"metric": "price", "value": result["price"], "unit": "currency/share"},
            {"metric": "delta", "value": result["delta"], "unit": "price delta per 1 underlying unit"},
            {"metric": "gamma", "value": result["gamma"], "unit": "delta change per 1 underlying unit"},
            {"metric": "theta", "value": result["theta"], "unit": "price/day"},
            {"metric": "vega", "value": result["vega"], "unit": "price per 1 vol point"},
            {"metric": "rho", "value": result["rho"], "unit": "price per 1 rate point"},
            {"metric": "d1", "value": result.get("d1"), "unit": "standard deviations"},
            {"metric": "d2", "value": result.get("d2"), "unit": "standard deviations"},
        ]
        if model == "heston" and not input_error:
            try:
                from showme.engine.functions.derivative.heston import HestonParams, heston_mc
                hp = HestonParams(
                    kappa=float(params.get("kappa", 2.0)),
                    theta=float(params.get("theta", sigma * sigma)),
                    sigma=float(params.get("hsigma", 0.4)),
                    rho=float(params.get("rho", -0.6)),
                    v0=float(params.get("v0", sigma * sigma)),
                )
                hr = heston_mc(S, K, T, r, q, hp, is_call=is_call,
                                paths=int(params.get("paths", 30_000)),
                                steps=int(params.get("steps", 100)))
                result["heston_price"] = hr["price"]
                result["heston_stderr"] = hr["stderr"]
                result["heston_paths"] = hr["paths"]
            except Exception as e:
                result["heston_error"] = str(e)
        payload = {
            "status": "error" if input_error else "ok",
            **result,
            "spot": S,
            "strike": K,
            "T": T,
            "years_to_expiry": T,
            "vol": sigma,
            "rate": r,
            "div_yield": q,
            "type": opt_type,
            "model": model,
            "rows": rows,
            "curve": sensitivity,
            "sensitivity": sensitivity,
            "summary": {
                "price": result["price"],
                "delta": result["delta"],
                "gamma": result["gamma"],
                "theta_per_day": result["theta"],
                "vega_per_vol_point": result["vega"],
                "rho_per_rate_point": result["rho"],
            },
            "methodology": (
                "Black-Scholes-Merton: price = S*e^(-qT)*N(d1) - K*e^(-rT)*N(d2) for calls; "
                "puts use put-call parity form. d1 = [ln(S/K) + (r-q+0.5*sigma^2)T] / (sigma*sqrt(T)); d2 = d1 - sigma*sqrt(T)."
            ),
            "field_dictionary": {
                "spot": "Current underlying price used by the calculation.",
                "strike": "Option strike price.",
                "years_to_expiry": "Time to expiry in years.",
                "vol": "Annualized implied volatility as a decimal.",
                "theta": "Per-day option decay under the current assumptions.",
                "curve.price": "Option value across a spot sensitivity range.",
            },
        }
        warnings_list: list[str] = []
        if input_error:
            warnings_list.append(input_error)
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=payload,
            sources=["black_scholes_formula" if model != "heston" else "black_scholes_formula", "heston_formula"] if model == "heston" else ["black_scholes_formula"],
            warnings=warnings_list,
        )
