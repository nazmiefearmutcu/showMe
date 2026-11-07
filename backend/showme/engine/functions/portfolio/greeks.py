"""GREEKS — Portfolio-level options Greeks aggregation.

Inputs are normalised before pricing: the help and manifest advertise
``qty``/``expiry``/``rate``/``type`` while the Black-Scholes service reads
``quantity``/``T``/``r``/``kind``; until 2026-11-07 the advertised names were
silently dropped and replaced by service defaults. Nothing is invented now:
a missing spot or vol is taken from the symbol's real daily history (last
close, 30-day realized vol — labelled per row); a missing expiry, or a vol
with no history to estimate it from, is an input error.
"""

from __future__ import annotations

import asyncio
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.services import greeks as greeks_svc

_ALIASES: dict[str, tuple[str, ...]] = {
    "kind": ("kind", "type", "option_type", "right"),
    "T": ("T", "years_to_expiry", "tenor_years"),
    "r": ("r", "rate", "risk_free_rate"),
    "quantity": ("quantity", "qty", "contracts"),
    "vol": ("vol", "iv", "sigma", "volatility"),
}
_REALIZED_WINDOW = 30
_TRADING_DAYS = 252


def _first(position: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = position.get(name)
        if value not in (None, ""):
            return value
    return None


def _years_until(value: Any, today: date) -> float | None:
    """``expiry`` as an ISO date, or a number of years."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        when = date.fromisoformat(text[:10])
    except ValueError:
        return None
    return (when - today).days / 365.25


def normalize_position(position: dict[str, Any], today: date | None = None) -> tuple[dict[str, Any], list[str]]:
    """Canonical service keys + a list of what is still missing."""
    today = today or datetime.now(timezone.utc).date()
    out = dict(position)
    for canonical, names in _ALIASES.items():
        value = _first(position, names)
        if value is not None:
            out[canonical] = value
    kind = str(out.get("kind") or "").strip().lower()
    out["kind"] = {"c": "call", "p": "put"}.get(kind, kind)
    if out.get("T") in (None, ""):
        if position.get("expiry") not in (None, ""):
            out["T"] = _years_until(position["expiry"], today)
        elif position.get("expiry_days") not in (None, ""):
            out["T"] = float(position["expiry_days"]) / 365.0
    missing = []
    if out["kind"] not in {"call", "put"}:
        missing.append("type (call/put)")
    if out.get("strike") in (None, ""):
        missing.append("strike")
    if out.get("T") in (None, "") or float(out["T"]) <= 0:
        missing.append("expiry (future date or years)")
    if out.get("r") in (None, ""):
        out["r"] = 0.0
        out.setdefault("_notes", []).append("rate not supplied: r=0")
    return out, missing


async def _history_stats(deps: Any, symbol: str) -> tuple[float, float] | None:
    """(last close, 30d annualized realized vol) from real daily history."""
    yf = getattr(deps, "yfinance", None)
    if yf is None or not symbol:
        return None
    instrument = Instrument(symbol=symbol.split()[0].upper(), asset_class=AssetClass.EQUITY)
    try:
        df = await asyncio.wait_for(
            yf.fetch(DataRequest(kind=DataKind.OHLCV, instrument=instrument, interval="1d",
                                 start=datetime.now(timezone.utc) - timedelta(days=90))),
            timeout=6.0,
        )
    except Exception:  # noqa: BLE001 - reported as missing data by the caller
        return None
    if df is None or "close" not in df or len(df) < _REALIZED_WINDOW + 1:
        return None
    closes = [float(c) for c in df["close"].dropna().tolist()]
    if len(closes) < _REALIZED_WINDOW + 1:
        return None
    window = closes[-(_REALIZED_WINDOW + 1):]
    rets = [math.log(b / a) for a, b in zip(window[:-1], window[1:]) if a > 0 and b > 0]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
    return closes[-1], math.sqrt(var) * math.sqrt(_TRADING_DAYS)


@FunctionRegistry.register
class GREEKSFunction(BaseFunction):
    code = "GREEKS"
    name = "Portfolio Greeks"
    category = "portfolio"
    description = "Sum delta/gamma/vega/theta/rho across an option book."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        positions = params.get("positions") or []
        if not isinstance(positions, list):
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_error",
                    "reason": f"GREEKS requires positions as a list; received {type(positions).__name__}.",
                    "next_actions": [
                        "Pass positions as a JSON array of objects with qty, type, strike, expiry and (optionally) spot, vol, rate.",
                    ],
                    "rows": [],
                },
                warnings=[f"positions must be a list, got {type(positions).__name__}"],
            )
        if not positions:
            return FunctionResult(code=self.code, instrument=None,
                                  data={"delta": 0, "gamma": 0, "vega": 0, "theta": 0,
                                        "rho": 0, "positions": [], "n": 0,
                                        "rows": [],
                                        "status": "input_required",
                                        "reason": "No option positions were supplied or found in the local option book.",
                                        "next_actions": [
                                            "Pass positions with qty, type, strike, expiry and (optionally) spot, vol, rate.",
                                            "Use OSA/OVME for single-strategy or single-contract assumptions.",
                                        ],
                                        "methodology": _methodology(),
                                        "field_dictionary": _field_dictionary()},
                                  sources=["empty_book"])

        normalized: list[dict[str, Any]] = []
        problems: list[str] = []
        need_history: set[str] = set()
        for i, raw in enumerate(positions):
            if not isinstance(raw, dict):
                problems.append(f"position {i + 1}: not an object")
                continue
            pos, missing = normalize_position(raw)
            if missing:
                problems.append(f"position {i + 1} ({raw.get('symbol', '?')}): missing {', '.join(missing)}")
            if pos.get("spot") in (None, "") or pos.get("vol") in (None, ""):
                need_history.add(str(pos.get("symbol") or ""))
            normalized.append(pos)

        history: dict[str, tuple[float, float] | None] = {}
        if need_history:
            fetched = await asyncio.gather(*(_history_stats(self.deps, s) for s in sorted(need_history)))
            history = dict(zip(sorted(need_history), fetched))
        used_history = False
        for i, pos in enumerate(normalized):
            stats = history.get(str(pos.get("symbol") or ""))
            if pos.get("spot") in (None, ""):
                if stats is None:
                    problems.append(f"position {i + 1} ({pos.get('symbol', '?')}): missing spot and no price history")
                else:
                    pos["spot"], pos["spot_source"] = stats[0], "yfinance_last_close"
                    used_history = True
            else:
                pos.setdefault("spot_source", "input")
            if pos.get("vol") in (None, ""):
                if stats is None:
                    problems.append(f"position {i + 1} ({pos.get('symbol', '?')}): missing vol and no price history to estimate it")
                else:
                    pos["vol"], pos["vol_source"] = stats[1], f"realized_{_REALIZED_WINDOW}d"
                    used_history = True
            else:
                pos.setdefault("vol_source", "input")

        if problems:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_error",
                    "reason": "Cannot price the book: " + "; ".join(problems),
                    "next_actions": [
                        "Give every position a type (call/put), strike and expiry (ISO date or years).",
                        "Spot and vol may be omitted only for symbols with daily price history.",
                    ],
                    "rows": [],
                    "methodology": _methodology(),
                    "field_dictionary": _field_dictionary(),
                },
                warnings=problems,
            )

        try:
            agg = greeks_svc.aggregate_book(normalized)
        except Exception as e:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "calc_error",
                    "reason": f"Greeks aggregation failed: {e}",
                    "rows": [],
                    "next_actions": [
                        "Verify each position has numeric qty, strike, expiry, vol, rate, and spot.",
                    ],
                },
                warnings=[f"aggregate: {e}"],
            )
        for row, pos in zip(agg.get("positions", []), normalized):
            for key in ("spot_source", "vol_source"):
                if key in pos:
                    row[key] = pos[key]
        totals = agg.get("totals") or {}
        warnings = sorted({note for pos in normalized for note in pos.get("_notes", [])})
        data = {
            **agg,
            # NOTE: no separate input-echo `rows` key — the payload's `positions`
            # are the greeks-bearing service rows the pane renders.
            "summary": {
                "positions": len(normalized),
                "delta": totals.get("delta"),
                "gamma": totals.get("gamma"),
                "vega": totals.get("vega"),
                "theta": totals.get("theta"),
                "rho": totals.get("rho"),
            },
            "methodology": _methodology(),
            "field_dictionary": _field_dictionary(),
        }
        sources = ["black_scholes_model"] + (["yfinance"] if used_history else [])
        return FunctionResult(code=self.code, instrument=None, data=data, sources=sources, warnings=warnings)


def _methodology() -> str:
    return (
        "Aggregate contract-level Black-Scholes Greeks across the option book. Each row is scaled by "
        "quantity and contract size; portfolio delta/gamma/vega/theta/rho are the sums across positions. "
        "A missing spot uses the symbol's last daily close and a missing vol its 30-day realized "
        "volatility (log returns, annualized with 252 days); both are labelled per row. Expiry is never "
        "assumed."
    )


def _field_dictionary() -> dict[str, str]:
    return {
        "delta": "Change in option value for a one-unit spot move.",
        "gamma": "Change in delta for a one-unit spot move.",
        "vega": "Change in option value for a 1.00 volatility-point move.",
        "theta": "Time decay per year under the Black-Scholes convention used by the service.",
        "rho": "Change in option value for a 1.00 rate move.",
        "contract_size": "Multiplier applied to per-contract Greeks.",
        "spot_source": "input, or yfinance_last_close when spot was not supplied.",
        "vol_source": "input, or realized_30d when vol was not supplied.",
    }
