"""GEX — Gamma Exposure (dealer hedging structure)."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.services.gamma_exposure import chain_gex


def _model_gex(symbol: str, spot: float, rate: float) -> dict[str, Any]:
    expiries = ["30d"]
    calls: list[dict[str, Any]] = []
    puts: list[dict[str, Any]] = []
    for multiplier, oi in ((0.9, 120), (1.0, 180), (1.1, 135)):
        strike = round(spot * multiplier, 2)
        calls.append({
            "strike": strike,
            "openInterest": oi,
            "impliedVolatility": 0.42,
            "expiry": expiries[0],
        })
        puts.append({
            "strike": strike,
            "openInterest": oi + 40,
            "impliedVolatility": 0.47,
            "expiry": expiries[0],
        })
    out = chain_gex(spot=spot, calls=calls, puts=puts, rate=rate)
    out["symbol"] = symbol
    out["expiries"] = expiries
    return out


@FunctionRegistry.register
class GEXFunction(BaseFunction):
    code = "GEX"
    name = "Gamma Exposure"
    asset_classes = (AssetClass.EQUITY,)
    category = "derivative"
    description = "Per-strike dealer gamma exposure + flip + walls."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        sym = (instrument.symbol if instrument else
               params.get("symbol") or "SPY").upper()
        spot = float(params.get("spot", 100))
        rate = float(params.get("rate", 0.04))
        spot_inst = instrument or Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
        timeout = max(1.0, min(float(params.get("yfinance_timeout", 2.5)), 3.0))
        live_options = _truthy(params.get("live_options") or params.get("deep"))

        if self.deps.yfinance and _truthy(params.get("live")):
            try:
                quote = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.QUOTE, instrument=spot_inst,
                        extra={"timeout": timeout},
                    )),
                    timeout=timeout + 0.5,
                )
                spot = float(getattr(quote, "last", None) or spot)
            except Exception:
                pass

        if not live_options:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_model_gex(sym, spot, rate),
                sources=["yfinance_quote", "gamma_exposure_model"] if self.deps.yfinance else ["gamma_exposure_model"],
            )
        if not self.deps.yfinance:
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=_model_gex(sym, spot, rate),
                                  sources=["gamma_exposure_model"])
        if spot <= 0:
            spot = float(params.get("spot", 100))
        # 2. Pull all expiries up to ``max_expiries`` and combine.
        timeout = max(1.0, min(float(params.get("yfinance_timeout", 3)), 4.0))
        max_expiries = max(1, min(int(params.get("max_expiries", 1)), 3))
        try:
            chains = await asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OPTIONS_CHAIN, instrument=spot_inst,
                    extra={"timeout": timeout})),
                timeout=timeout + 1,
            )
        except Exception:
            chains = {}
        expiries = (chains or {}).get("expiries") or []
        expiries = expiries[:max_expiries]
        if not expiries:
            expiries = ["30d"]
        all_calls: list[dict[str, Any]] = []
        all_puts: list[dict[str, Any]] = []
        used_live_chain = False

        async def _one(exp: str):
            try:
                ch = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.OPTIONS_CHAIN, instrument=spot_inst,
                        extra={"expiry": exp, "timeout": timeout})),
                    timeout=timeout + 1,
                )
                return exp, ch
            except Exception:
                return exp, None

        results = await asyncio.gather(*(_one(exp) for exp in expiries))
        for exp, ch in results:
            if not ch:
                continue
            calls = ch.get("calls")
            puts = ch.get("puts")
            if calls is not None and len(calls) > 0:
                used_live_chain = True
                for _, r in calls.iterrows():
                    all_calls.append({
                        "strike": r.get("strike"),
                        "openInterest": r.get("openInterest"),
                        "impliedVolatility": r.get("impliedVolatility"),
                        "expiry": exp,
                    })
            if puts is not None and len(puts) > 0:
                used_live_chain = True
                for _, r in puts.iterrows():
                    all_puts.append({
                        "strike": r.get("strike"),
                        "openInterest": r.get("openInterest"),
                        "impliedVolatility": r.get("impliedVolatility"),
                        "expiry": exp,
                    })
        if not all_calls and not all_puts:
            for m in (0.9, 1.0, 1.1):
                strike = round(spot * m, 2)
                all_calls.append({
                    "strike": strike,
                    "openInterest": 100,
                    "impliedVolatility": 0.45,
                    "expiry": expiries[0],
                })
                all_puts.append({
                    "strike": strike,
                    "openInterest": 100,
                    "impliedVolatility": 0.50,
                    "expiry": expiries[0],
                })
        out = chain_gex(spot=spot, calls=all_calls, puts=all_puts, rate=rate)
        out["symbol"] = sym
        out["expiries"] = expiries
        return FunctionResult(code=self.code, instrument=instrument,
                              data=out, sources=["yfinance" if used_live_chain else "gamma_exposure_model"])


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
