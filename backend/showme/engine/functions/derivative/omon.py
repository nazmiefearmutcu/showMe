"""OMON — Option Monitor (full chain)."""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.derivative._stubs import _IVOL_FIELDS, _surface_rows


async def _resolve_spot(deps: Any, instrument: Instrument, params: dict[str, Any]) -> float:
    """Pull the live underlying price for OMON.

    2026-05-17 BugHunt S10: previously OMON did ``spot = params.get("spot", 100)``
    in both the reference and live branches, which gave every non-$100 symbol
    (AAPL ~$200, NVDA ~$1400, etc.) wildly wrong moneyness on every row. We
    now mirror the GEX pattern: explicit param wins, otherwise yfinance QUOTE
    fills it; final fallback to 100 only when no other signal is available.
    """
    if "spot" in params:
        try:
            value = float(params["spot"])
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    yfinance = getattr(deps, "yfinance", None)
    if yfinance is None:
        return 100.0
    timeout = max(1.0, min(float(params.get("yfinance_timeout", 3)), 4.0))
    try:
        quote = await asyncio.wait_for(
            yfinance.fetch(DataRequest(
                kind=DataKind.QUOTE, instrument=instrument,
                extra={"timeout": timeout},
            )),
            timeout=timeout + 0.5,
        )
    except Exception:
        return 100.0
    last = getattr(quote, "last", None)
    try:
        value = float(last) if last is not None else 0.0
        return value if value > 0 else 100.0
    except (TypeError, ValueError):
        return 100.0


def _has_no_rows(value: Any) -> bool:
    if value is None:
        return True
    if hasattr(value, "empty"):
        return bool(value.empty)
    try:
        return len(value) == 0
    except Exception:
        return True


def _options_surface_model(spot: float) -> dict[str, Any]:
    expiries = ["30d", "60d", "90d"]
    strikes = [round(spot * m, 2) for m in (0.9, 1.0, 1.1)]
    calls = [{"expiry": e, "strike": k, "impliedVolatility": 0.4, "bid": None, "ask": None}
             for e in expiries for k in strikes]
    puts = [{"expiry": e, "strike": k, "impliedVolatility": 0.45, "bid": None, "ask": None}
            for e in expiries for k in strikes]
    rows = _surface_rows(calls, puts, spot=spot)
    return {
        "status": "reference",
        "spot": spot,
        "expiries": expiries,
        "rows": rows,
        "surface": rows,
        "calls": calls,
        "puts": puts,
        "summary": {"contracts": len(rows), "expiries": len(expiries), "source_mode": "reference"},
        "methodology": "Reference option monitor rows are formula-shaped placeholders; live mode requires yfinance option chains.",
        "field_dictionary": _IVOL_FIELDS,
    }


@FunctionRegistry.register
class OMONFunction(BaseFunction):
    code = "OMON"
    name = "Option Monitor"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF, AssetClass.DERIVATIVE)
    category = "derivative"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        warnings: list[str] = []
        data = {}
        if not (params.get("live_options") or params.get("live")):
            # Reference path: still pull a live quote so the model surface is
            # anchored on the real underlying (avoids the $100-strike trap on
            # AAPL/NVDA/etc.). If the quote also fails we fall back to 100.
            ref_spot = await _resolve_spot(self.deps, instrument, dict(params))
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_options_surface_model(ref_spot),
                sources=["black_scholes_reference_formula"],
            )
        try:
            if self.deps.yfinance:
                data = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OPTIONS_CHAIN, instrument=instrument,
                    extra={"expiry": params.get("expiry"),
                           "timeout": float(params.get("yfinance_timeout", 6))},
                ))
        except Exception as e:
            warnings.append(f"yfinance options: {e}")
        if not data or not isinstance(data, dict):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "reason": "Option-chain provider returned no payload.",
                    "symbol": instrument.symbol,
                    "rows": [],
                    "surface": [],
                    "methodology": "Requires live option chains with expiry, strike, bid/ask, implied volatility, volume, and open interest.",
                    "field_dictionary": _IVOL_FIELDS,
                    "next_actions": ["Try AAPL, MSFT, SPY, or another optionable equity/ETF."],
                },
                sources=[],
                warnings=warnings,
                metadata={"fallback": True, "provider_errors": warnings or ["empty option-chain payload"]},
            )
        expiries = data.get("expiries") or []
        calls = data.get("calls")
        puts = data.get("puts")
        if expiries and (_has_no_rows(calls) or _has_no_rows(puts)):
            expiry = params.get("expiry") or expiries[0]
            try:
                data = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OPTIONS_CHAIN,
                    instrument=instrument,
                    extra={"expiry": expiry, "timeout": float(params.get("yfinance_timeout", 6))},
                ))
                data["selected_expiry"] = expiry
                expiries = data.get("expiries") or expiries
                calls = data.get("calls")
                puts = data.get("puts")
            except Exception as e:
                warnings.append(f"yfinance options {expiry}: {e}")
        raw_calls: list[dict[str, Any]] = []
        raw_puts: list[dict[str, Any]] = []
        selected_expiry = data.get("selected_expiry") or params.get("expiry") or (expiries[0] if expiries else "-")
        if calls is not None and hasattr(calls, "iterrows"):
            for _, row in calls.iterrows():
                raw_calls.append({"expiry": selected_expiry, **row.to_dict()})
        if puts is not None and hasattr(puts, "iterrows"):
            for _, row in puts.iterrows():
                raw_puts.append({"expiry": selected_expiry, **row.to_dict()})
        # 2026-05-17 BugHunt S10: spot must come from the live quote so
        # moneyness reflects the real underlying, not a $100 placeholder.
        spot = await _resolve_spot(self.deps, instrument, dict(params))
        rows = _surface_rows(raw_calls, raw_puts, spot=spot)
        if not rows:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "reason": "No usable option rows with strike and implied volatility.",
                    "symbol": instrument.symbol,
                    "available_expiry_count": len(expiries),
                    "available_expiry_preview": ", ".join(map(str, expiries[:6])),
                    "rows": [],
                    "surface": [],
                    "methodology": "Requires live option-chain rows with strike, impliedVolatility, bid/ask, volume, and open interest.",
                    "field_dictionary": _IVOL_FIELDS,
                    "next_actions": ["Try a liquid optionable equity/ETF or rerun later."],
                },
                sources=[],
                warnings=warnings,
                metadata={"fallback": True, "provider_errors": warnings or ["empty usable option-chain rows"]},
            )
        payload = {
            "status": "ok",
            "symbol": instrument.symbol,
            "spot": spot,
            "selected_expiry": selected_expiry,
            "expiries": expiries,
            "rows": rows,
            "surface": rows,
            "summary": {
                "contracts": len(rows),
                "calls": sum(1 for row in rows if row["option_type"] == "CALL"),
                "puts": sum(1 for row in rows if row["option_type"] == "PUT"),
                "selected_expiry": selected_expiry,
            },
            "methodology": "Live option monitor flattens the selected option-chain expiry into CALL/PUT rows with bid, ask, mid, IV, volume, and open interest.",
            "field_dictionary": _IVOL_FIELDS,
        }
        return FunctionResult(code=self.code, instrument=instrument, data=payload,
                              sources=["yfinance_options"], warnings=warnings)
