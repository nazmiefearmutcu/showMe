"""Option analytics functions used by the derivative screens."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.functions.derivative.ovme import _bs_price


_HVT_FIELDS = {
    "window_days": "Trailing close-to-close return window used for the realized-volatility estimate.",
    "realized_vol": "Annualized realized volatility as a decimal: stdev(daily returns) * sqrt(252).",
    "realized_vol_pct": "Annualized realized volatility in percent.",
    "samples": "Number of daily returns used for the window.",
    "history.vol": "Rolling annualized realized volatility for the selected chart window.",
}

_IVOL_FIELDS = {
    "expiry": "Option expiration date.",
    "strike": "Option strike.",
    "option_type": "CALL or PUT.",
    "vol": "Implied volatility as a decimal.",
    "vol_pct": "Implied volatility in percent.",
    "moneyness": "Strike divided by spot price.",
    "open_interest": "Listed option open interest when the provider supplies it.",
}


def _vol_template(symbol: str, spot: float = 100.0) -> dict[str, float]:
    seed = (sum(ord(ch) for ch in symbol.upper()) % 35) / 1000
    return {
        "rv_30d_annualized": round(0.22 + seed, 4),
        "rv_60d_annualized": round(0.24 + seed, 4),
        "rv_90d_annualized": round(0.26 + seed, 4),
        "rv_252d_annualized": round(0.29 + seed, 4),
        "spot": spot,
    }


def _surface_template(spot: float) -> dict[str, Any]:
    expiries = ["30d", "60d", "90d"]
    strikes = [round(spot * m, 2) for m in (0.8, 0.9, 1.0, 1.1, 1.2)]
    calls = []
    puts = []
    for e_idx, expiry in enumerate(expiries):
        for k_idx, strike in enumerate(strikes):
            skew = abs(k_idx - 2) * 0.025
            calls.append({"expiry": expiry, "strike": strike, "iv": round(0.32 + skew + e_idx * 0.015, 4), "volume": 0})
            puts.append({"expiry": expiry, "strike": strike, "iv": round(0.35 + skew + e_idx * 0.018, 4), "volume": 0})
    surface = _surface_rows(calls, puts, spot=spot)
    return {
        "status": "reference",
        "spot": spot,
        "expiries": expiries,
        "rows": surface,
        "surface": surface,
        "calls_grid": calls,
        "puts_grid": puts,
        "summary": {"contracts": len(surface), "expiries": len(expiries), "source_mode": "reference"},
        "methodology": "Reference surface generated from Black-Scholes-style skew assumptions when live chains are not requested.",
        "field_dictionary": _IVOL_FIELDS,
    }


def _finite(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return num


def _surface_rows(calls: list[dict[str, Any]], puts: list[dict[str, Any]], *, spot: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for option_type, source_rows in (("CALL", calls), ("PUT", puts)):
        for row in source_rows:
            strike = _finite(row.get("strike"))
            vol = _finite(row.get("impliedVolatility") or row.get("iv"))
            if strike is None or vol is None:
                continue
            expiry = str(row.get("expiry") or row.get("expiration") or row.get("expiration_date") or "-")
            bid = _finite(row.get("bid"))
            ask = _finite(row.get("ask"))
            last = _finite(row.get("lastPrice") or row.get("last"))
            mid = (bid + ask) / 2 if bid is not None and ask is not None and ask >= bid else last
            volume = _finite(row.get("volume"))
            open_interest = _finite(row.get("openInterest") or row.get("open_interest"))
            rows.append({
                "label": f"{expiry} {option_type[0]} {strike:g}",
                "expiry": expiry,
                "strike": strike,
                "option_type": option_type,
                "vol": vol,
                "vol_pct": vol * 100,
                "moneyness": strike / spot if spot > 0 else None,
                "mid": mid,
                "bid": bid,
                "ask": ask,
                "last": last,
                "volume": volume,
                "open_interest": open_interest,
            })
    return rows


def _vol_rows_from_returns(rets: Any, windows: list[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in windows:
        sample = rets.tail(window)
        if len(sample) < max(5, min(window, 20)):
            continue
        vol = float(sample.std() * np.sqrt(252))
        rows.append({
            "metric": f"{window}D realized vol",
            "window_days": window,
            "realized_vol": vol,
            "realized_vol_pct": vol * 100,
            "samples": int(len(sample)),
            "formula": "stdev(daily close returns) * sqrt(252)",
        })
    return rows


def _rolling_vol_history(rets: Any, window: int) -> list[dict[str, Any]]:
    if len(rets) < max(6, window):
        window = max(5, min(window, max(5, len(rets) // 2)))
    rolling = rets.rolling(window).std().dropna() * np.sqrt(252)
    history: list[dict[str, Any]] = []
    for idx, value in rolling.tail(180).items():
        date = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
        history.append({
            "date": date,
            "vol": float(value),
            "vol_pct": float(value) * 100,
            "window_days": int(window),
        })
    return history


def _reference_hvt(symbol: str, spot: float, *, reason: str) -> dict[str, Any]:
    template = _vol_template(symbol, spot)
    rows = [
        {
            "metric": key.replace("_annualized", "").upper(),
            "window_days": int(key.split("_")[1].replace("d", "")),
            "realized_vol": value,
            "realized_vol_pct": value * 100,
            "samples": 0,
            "formula": "stdev(daily close returns) * sqrt(252)",
        }
        for key, value in template.items()
        if key.startswith("rv_")
    ]
    return {
        "status": "provider_unavailable",
        "reason": reason,
        "symbol": symbol,
        "spot": spot,
        "rows": rows,
        "summary": {"source_mode": "reference", "windows": len(rows)},
        "methodology": "Live daily close history is required for HVT. The realized-vol formula is stdev(daily close returns) * sqrt(252).",
        "field_dictionary": _HVT_FIELDS,
        "next_actions": ["Retry with a supported symbol or configure the yfinance data adapter."],
    }


@FunctionRegistry.register
class OSAFunction(BaseFunction):
    """OSA — Option Strategy Analysis."""
    code = "OSA"
    name = "Option Strategy Analysis"
    asset_classes = (AssetClass.DERIVATIVE,)
    category = "derivative"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        legs = params.get("legs") or [
            {"qty": 1, "strike": 100, "type": "CALL", "expiry": 0.25, "vol": 0.25},
            {"qty": -1, "strike": 110, "type": "CALL", "expiry": 0.25, "vol": 0.25},
        ]
        S = float(params.get("spot", 100))
        r = float(params.get("rate", 0.045))
        q = float(params.get("div_yield", 0.0))
        initial_premiums: list[dict[str, Any]] = []
        net_debit = 0.0
        for idx, leg in enumerate(legs, start=1):
            strike = float(leg["strike"])
            expiry = float(leg.get("expiry") or leg.get("years_to_expiry") or 0.25)
            vol = float(leg.get("vol") or 0.25)
            opt_type = str(leg.get("type") or "CALL").upper()
            qty = float(leg.get("qty") or 0)
            premium = _bs_price(S, strike, expiry, r, vol, q, opt_type == "CALL")["price"]
            net_debit += qty * premium
            initial_premiums.append({
                "leg": idx,
                "qty": qty,
                "type": opt_type,
                "strike": strike,
                "expiry_years": expiry,
                "vol": vol,
                "premium": premium,
                "initial_value": qty * premium,
            })
        spots = [S * (0.5 + i * 0.01) for i in range(101)]
        pnl_curve: list[dict] = []
        for s in spots:
            expiry_payoff = 0.0
            for leg in legs:
                strike = float(leg["strike"])
                qty = float(leg.get("qty") or 0)
                opt_type = str(leg.get("type") or "CALL").upper()
                payoff = max(s - strike, 0.0) if opt_type == "CALL" else max(strike - s, 0.0)
                expiry_payoff += qty * payoff
            pnl_curve.append({
                "spot": s,
                "pnl": expiry_payoff - net_debit,
                "payoff": expiry_payoff,
                "net_debit": net_debit,
            })
        pnls = [row["pnl"] for row in pnl_curve]
        return FunctionResult(code=self.code, instrument=instrument,
                              data={
                                  "status": "ok",
                                  "spot": S,
                                  "rate": r,
                                  "div_yield": q,
                                  "strategy": params.get("strategy") or "custom",
                                  "rows": initial_premiums,
                                  "legs": initial_premiums,
                                  "curve": pnl_curve,
                                  "pnl_curve": pnl_curve,
                                  "summary": {
                                      "net_debit": net_debit,
                                      "max_gain_visible": max(pnls),
                                      "max_loss_visible": min(pnls),
                                      "breakeven_count_visible": sum(
                                          1
                                          for prev, cur in zip(pnls, pnls[1:])
                                          if (prev <= 0 <= cur) or (prev >= 0 >= cur)
                                      ),
                                  },
                                  "methodology": "Expiration P&L = sum(qty * intrinsic payoff at spot) - initial option premium; premiums use Black-Scholes-Merton.",
                                  "field_dictionary": {
                                      "net_debit": "Positive value means the strategy costs premium up front; negative means a credit.",
                                      "curve.pnl": "Estimated expiration profit/loss at each underlying spot.",
                                      "premium": "Black-Scholes-Merton premium at the current spot.",
                                  },
                              },
                              sources=["black_scholes_formula"])


@FunctionRegistry.register
class HVTFunction(BaseFunction):
    """HVT — Historical Volatility Trends."""
    code = "HVT"
    name = "Historical Volatility Trends"
    asset_classes = (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.ETF)
    category = "derivative"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        symbol = instrument.symbol
        if not (params.get("live_vol") or params.get("live")):
            spot = float(params.get("spot", 100))
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_vol_template(symbol, spot),
                sources=["historical_vol_model"],
            )
        if not self.deps.yfinance:
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=_vol_template(symbol, float(params.get("spot", 100))),
                                  sources=["historical_vol_model"])
        timeout = max(1.0, min(float(params.get("yfinance_timeout", 4)), 6.0))
        days = max(30, min(int(params.get("days") or params.get("lookback_days") or 365), 365 * 3))
        start = datetime.utcnow() - timedelta(days=days + 30)
        try:
            df = await asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OHLCV, instrument=instrument,
                    start=start, interval="1d",
                    extra={"timeout": timeout},
                )),
                timeout=timeout + 1,
            )
        except Exception as exc:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_reference_hvt(symbol, float(params.get("spot", 100)), reason=f"yfinance: {exc}"),
                sources=[],
                metadata={"fallback": True},
            )
        if df is None or len(df) < 10 or "close" not in df:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_reference_hvt(symbol, float(params.get("spot", 100)), reason="no daily close history returned"),
                sources=[],
                metadata={"fallback": True},
            )
        closes = df["close"].dropna()
        rets = closes.pct_change().dropna()
        windows = [30, 60, 90, min(252, max(30, days))]
        rows = _vol_rows_from_returns(rets, sorted(set(windows)))
        history_window = min(30, max(10, days // 3))
        history = _rolling_vol_history(rets, history_window)
        current_spot = float(closes.iloc[-1]) if len(closes) else float(params.get("spot", 100))
        out = {
            "status": "ok",
            "symbol": symbol,
            "spot": current_spot,
            "lookback_days": days,
            "rows": rows,
            "history": history,
            "summary": {
                "current_realized_vol": rows[0]["realized_vol"] if rows else None,
                "current_realized_vol_pct": rows[0]["realized_vol_pct"] if rows else None,
                "observations": int(len(rets)),
                "history_window_days": history_window,
            },
            "methodology": "Annualized realized volatility = stdev(daily close-to-close returns) * sqrt(252). Rolling history uses the selected chart window.",
            "field_dictionary": _HVT_FIELDS,
        }
        return FunctionResult(code=self.code, instrument=instrument, data=out,
                              sources=["yfinance"])


@FunctionRegistry.register
class IVOLFunction(BaseFunction):
    """IVOL — Implied Vol Surface."""
    code = "IVOL"
    name = "Implied Vol Surface"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF, AssetClass.DERIVATIVE)
    category = "derivative"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        spot = float(params.get("spot", 100))
        if not (params.get("live_options") or params.get("live")):
            synthetic = _surface_template(spot)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=synthetic,
                sources=["black_scholes_reference_formula"],
                metadata={"calls": len(synthetic["calls_grid"]), "puts": len(synthetic["puts_grid"])},
            )
        if not self.deps.yfinance:
            synthetic = _surface_template(spot)
            return FunctionResult(code=self.code, instrument=instrument, data=synthetic,
                                  sources=["black_scholes_reference_formula"],
                                  metadata={"calls": len(synthetic["calls_grid"]), "puts": len(synthetic["puts_grid"])})
        from src.core.base_data_source import DataKind, DataRequest
        timeout = max(1.0, min(float(params.get("yfinance_timeout", 4)), 6.0))
        try:
            meta = await asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OPTIONS_CHAIN, instrument=instrument,
                    extra={"timeout": timeout},
                )),
                timeout=timeout + 1,
            )
        except Exception:
            meta = {}
        expiries = meta.get("expiries", []) or []
        if not expiries:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "reason": "No option expirations returned for this symbol.",
                    "symbol": instrument.symbol,
                    "spot": spot,
                    "rows": [],
                    "surface": [],
                    "methodology": "Requires a live option-chain provider with expirations, strikes, and implied volatility.",
                    "field_dictionary": _IVOL_FIELDS,
                    "next_actions": ["Try AAPL, MSFT, SPY, or another optionable equity/ETF."],
                },
                sources=[],
                metadata={"fallback": True, "provider_errors": ["yfinance options expiries empty"]},
            )
        max_expiries = max(1, min(int(params.get("max_expiries", 3)), 4))
        targets = expiries[:max_expiries]
        async def _one(exp):
            try:
                return exp, await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.OPTIONS_CHAIN, instrument=instrument,
                        extra={"expiry": exp, "timeout": timeout},
                    )),
                    timeout=timeout + 1,
                )
            except Exception:
                return exp, None
        results = await asyncio.gather(*(_one(e) for e in targets))
        raw_calls: list[dict[str, Any]] = []
        raw_puts: list[dict[str, Any]] = []
        for exp, chain in results:
            if not chain:
                continue
            calls = chain.get("calls")
            puts = chain.get("puts")
            if calls is not None and hasattr(calls, "iterrows"):
                for _, r in calls.iterrows():
                    raw_calls.append({"expiry": exp, **r.to_dict()})
            if puts is not None and hasattr(puts, "iterrows"):
                for _, r in puts.iterrows():
                    raw_puts.append({"expiry": exp, **r.to_dict()})
        surface_rows = _surface_rows(raw_calls, raw_puts, spot=spot)
        if not surface_rows:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "reason": "Option chains returned no usable implied volatility rows.",
                    "symbol": instrument.symbol,
                    "spot": spot,
                    "available_expiry_count": len(targets),
                    "available_expiry_preview": ", ".join(map(str, targets[:6])),
                    "rows": [],
                    "surface": [],
                    "methodology": "Requires option-chain rows with strike and impliedVolatility.",
                    "field_dictionary": _IVOL_FIELDS,
                    "next_actions": ["Try a liquid optionable equity/ETF or rerun later."],
                },
                sources=[],
                metadata={"fallback": True, "provider_errors": ["yfinance implied volatility rows empty"]},
            )
        return FunctionResult(code=self.code, instrument=instrument,
                              data={"status": "ok",
                                    "symbol": instrument.symbol,
                                    "spot": spot,
                                    "expiries": targets,
                                    "rows": surface_rows,
                                    "surface": surface_rows,
                                    "summary": {
                                        "contracts": len(surface_rows),
                                        "expiries": len(set(row["expiry"] for row in surface_rows)),
                                        "calls": sum(1 for row in surface_rows if row["option_type"] == "CALL"),
                                        "puts": sum(1 for row in surface_rows if row["option_type"] == "PUT"),
                                    },
                                    "methodology": "Live implied volatility surface from option-chain impliedVolatility by expiry, strike, and option type.",
                                    "field_dictionary": _IVOL_FIELDS},
                              sources=["yfinance"],
                              metadata={"calls": sum(1 for row in surface_rows if row["option_type"] == "CALL"),
                                        "puts": sum(1 for row in surface_rows if row["option_type"] == "PUT")})
