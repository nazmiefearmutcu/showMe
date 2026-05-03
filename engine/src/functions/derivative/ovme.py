"""OVME — Option Valuation (Black-Scholes + Greeks)."""

from __future__ import annotations

import math
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


def _bs_price(S: float, K: float, T: float, r: float, sigma: float, q: float, is_call: bool) -> dict[str, float]:
    """Black-Scholes-Merton with continuous dividend yield q."""
    if T <= 0 or sigma <= 0:
        intrinsic = max((S - K), 0.0) if is_call else max((K - S), 0.0)
        return {"price": intrinsic, "delta": 1.0 if is_call and S > K else 0.0,
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
    theta = (
        -S * sigma * math.exp(-q * T) * n_pdf(d1) / (2 * math.sqrt(T))
        - r * K * math.exp(-r * T) * (n_cdf(d2) if is_call else n_cdf(-d2)) * (1 if is_call else -1)
        + q * S * math.exp(-q * T) * (n_cdf(d1) if is_call else n_cdf(-d1)) * (1 if is_call else -1)
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
        r = float(params.get("rate", 0.045))
        q = float(params.get("div_yield", 0.0))
        opt_type = (params.get("type") or "CALL").upper()
        is_call = opt_type == "CALL"
        model = (params.get("model") or "bs").lower()
        result = _bs_price(S, K, T, r, sigma, q, is_call)
        if model == "heston":
            try:
                from src.functions.derivative.heston import HestonParams, heston_mc
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
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={**result, "spot": S, "strike": K, "T": T, "vol": sigma,
                   "rate": r, "div_yield": q, "type": opt_type, "model": model},
            sources=[],
        )
