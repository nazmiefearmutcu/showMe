"""GEX — Gamma Exposure (dealer hedging structure)."""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.services.gamma_exposure import chain_gex


def _model_gex(symbol: str, spot: float, rate: float, div_yield: float = 0.0) -> dict[str, Any]:
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
    out = chain_gex(spot=spot, calls=calls, puts=puts, rate=rate, div_yield=div_yield)
    out["symbol"] = symbol
    out["expiries"] = expiries
    return _shape_gex_payload(out, symbol=symbol, source_mode="reference")


_GEX_FIELDS = {
    "strike": "Option strike bucket.",
    "gex": "Dealer-perspective gamma exposure in dollars per 1% underlying move.",
    "value": "Same as gex, provided for chart rendering.",
    "gamma_flip": "First strike where cumulative gamma exposure changes sign.",
    "call_wall": "Strike with the largest positive dealer gamma concentration.",
    "put_wall": "Strike with the largest negative dealer gamma concentration.",
}


def _shape_gex_payload(raw: dict[str, Any], *, symbol: str, source_mode: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    cumulative = 0.0
    for row in raw.get("gex_per_strike") or []:
        strike = row.get("strike")
        gex = row.get("gex")
        try:
            strike_num = float(strike)
            gex_num = float(gex)
        except (TypeError, ValueError):
            continue
        cumulative += gex_num
        rows.append({
            "label": f"{strike_num:g}",
            "strike": strike_num,
            "gex": gex_num,
            "value": gex_num,
            "cumulative_gex": cumulative,
        })
    return {
        "status": "ok",
        "symbol": symbol,
        "spot": raw.get("spot"),
        "expiries": raw.get("expiries") or [],
        "rows": rows,
        "curve": rows,
        "summary": {
            "net_gex": raw.get("net_gex"),
            "call_gex_total": raw.get("call_gex_total"),
            "put_gex_total": raw.get("put_gex_total"),
            "gamma_flip": raw.get("gamma_flip"),
            "call_wall": (raw.get("call_wall") or {}).get("strike"),
            "put_wall": (raw.get("put_wall") or {}).get("strike"),
            "n_strikes": raw.get("n_strikes") or len(rows),
            "source_mode": source_mode,
        },
        "call_wall": raw.get("call_wall"),
        "put_wall": raw.get("put_wall"),
        "methodology": (
            "Dealer GEX assumes dealers are short call open interest and long put open interest. "
            "Black-Scholes gamma = N'(d1) / (S * sigma * sqrt(T)); exposure = gamma * OI * contract_size * S^2 * 1%."
        ),
        "field_dictionary": _GEX_FIELDS,
    }


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
        div_yield = float(params.get("div_yield", 0.0))
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

        # A bad quote (or a manual spot=0 input) used to slip through to the
        # model-only branch and produce a strike grid centered at 0 — every
        # cell came out garbage. Clamp before any consumer uses `spot`.
        if spot <= 0:
            spot = float(params.get("spot") or 100)

        if not live_options:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_model_gex(sym, spot, rate, div_yield),
                sources=["yfinance_quote", "black_scholes_gamma_formula"] if self.deps.yfinance else ["black_scholes_gamma_formula"],
            )
        if not self.deps.yfinance:
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=_model_gex(sym, spot, rate, div_yield),
                                  sources=["gamma_exposure_model"])
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
        out = chain_gex(spot=spot, calls=all_calls, puts=all_puts, rate=rate,
                        div_yield=div_yield)
        out["symbol"] = sym
        out["expiries"] = expiries
        shaped = _shape_gex_payload(
            out,
            symbol=sym,
            source_mode="live_chain" if used_live_chain else "reference_chain",
        )
        return FunctionResult(code=self.code, instrument=instrument,
                              data=shaped,
                              sources=["yfinance_options" if used_live_chain else "black_scholes_gamma_formula"])


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
