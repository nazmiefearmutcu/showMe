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
from showme.engine.functions._fred_csv import fred_with_keyless_fallback
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
#: A plain (unitless) rate above this magnitude is refused as ambiguous: a
#: decimal rate of 20%+ is not a plausible risk-free rate, so a value in
#: (0.2, 1] is most likely a percent typed without its unit.
_MAX_PLAIN_DECIMAL_RATE = 0.2


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
    return (when - today).days / greeks_svc.DAYS_PER_YEAR


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def normalize_position(position: dict[str, Any], today: date | None = None) -> tuple[dict[str, Any], list[str]]:
    """Canonical service keys + a list of what is missing or invalid.

    Nothing is defaulted here: a missing ``rate`` is flagged with
    ``_needs_rate`` (the caller fetches the live risk-free rate), a missing
    spot/vol is left for the price-history step, everything else must be a
    valid number.
    """
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
            days = _positive(position["expiry_days"])
            out["T"] = days / greeks_svc.DAYS_PER_YEAR if days else None
    problems = []
    if out["kind"] not in {"call", "put"}:
        problems.append("type (call/put)")
    for key, label in (("strike", "strike"), ("T", "expiry (future date or years)")):
        number = _positive(out.get(key))
        if number is None:
            problems.append(label if out.get(key) in (None, "") else f"{label} must be a positive number")
        else:
            out[key] = number
    try:
        qty = float(out.get("quantity"))
        if not math.isfinite(qty) or qty == 0:
            raise ValueError
        out["quantity"] = qty
    except (TypeError, ValueError):
        problems.append("qty (non-zero number)")
    if out.get("contract_size") not in (None, ""):
        size = _positive(out["contract_size"])
        if size is None:
            problems.append("contract_size must be a positive number")
        else:
            out["contract_size"] = size
    if out.get("spot") not in (None, ""):
        spot = _positive(out["spot"])
        if spot is None:
            problems.append("spot must be a positive number")
        else:
            out["spot"] = spot
    if out.get("vol") not in (None, ""):
        vol = _positive(out["vol"])
        if vol is None or vol > 5:
            problems.append("vol must be a decimal in (0, 5] (0.25 = 25%)")
        else:
            out["vol"] = vol
    # Explicit units are unambiguous: rate_pct (4.5 = 4.5%) and rate_bps (450 = 4.5%).
    explicit = [key for key in ("rate_pct", "rate_bps") if position.get(key) not in (None, "")]
    if explicit and (len(explicit) > 1 or position.get("r") not in (None, "")):
        problems.append("rate given more than once (use one of rate_pct, rate_bps or r)")
    elif explicit:
        key = explicit[0]
        number = _number(position[key])
        if number is None:
            problems.append(f"{key} must be a number")
        else:
            out["r"] = number / 100.0 if key == "rate_pct" else number / 10000.0
            out["rate_source"] = "input_percent" if key == "rate_pct" else "input_bps"
    elif out.get("r") in (None, ""):
        out["_needs_rate"] = True
    else:
        rate = _number(out["r"])
        if rate is None:
            problems.append("rate must be a number")
        elif abs(rate) > 1:  # 4.5 means 4.5%; no real risk-free rate exceeds 100%
            rate /= 100.0
            out["rate_source"] = "input_percent"
            out["r"] = rate
        elif abs(rate) > _MAX_PLAIN_DECIMAL_RATE:
            # 0.5 typed by a user who means 0.5 percent would be priced as 50%.
            problems.append(
                f"rate {rate:g} is ambiguous (read as a decimal it is {rate * 100:g}%): enter "
                f"r={rate / 100:g} for {rate:g}% (decimal form), or rate_pct={rate:g} through the API")
            out["r"] = rate
        else:
            out["r"] = rate
            out["rate_source"] = "input_decimal"
    return out, problems


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


async def _risk_free_rate(deps: Any, client: Any = None) -> tuple[float, str] | None:
    """Live 3-month US T-bill yield (FRED DGS3MO) as a decimal, with its date."""
    fred = fred_with_keyless_fallback(getattr(deps, "fred", None), client=client)
    try:
        df = await asyncio.wait_for(fred.series("DGS3MO", frequency="d"), timeout=8.0)
    except Exception:  # noqa: BLE001 - reported as a missing input
        return None
    if df is None or getattr(df, "empty", True) or "value" not in df:
        return None
    values = df["value"].dropna()
    if values.empty:
        return None
    when = values.index[-1]
    return float(values.iloc[-1]) / 100.0, str(getattr(when, "date", lambda: when)())


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
                                  data={# T10: an empty book has no Greeks to report, not zeros.
                                        "delta": None, "gamma": None, "vega": None, "theta": None,
                                        "rho": None, "positions": [], "n": 0,
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

        used_rate = False
        if not problems and any(pos.get("_needs_rate") for pos in normalized):
            rf = await _risk_free_rate(self.deps, client=getattr(self, "_http_client", None))
            if rf is None:
                problems.append("rate: not supplied and the live 3-month T-bill rate (FRED DGS3MO) is unavailable")
            else:
                used_rate = True
                for pos in normalized:
                    if pos.pop("_needs_rate", False):
                        pos["r"], pos["rate_source"] = rf[0], f"fred_DGS3MO_{rf[1]}"

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
                    "reason": f"Greeks aggregation failed: {str(e) or type(e).__name__}",
                    "rows": [],
                    "next_actions": [
                        "Verify each position has numeric qty, strike, expiry, vol, rate, and spot.",
                    ],
                },
                warnings=[f"aggregate: {str(e) or type(e).__name__}"],
            )
        failed = [row for row in agg.get("positions", []) if row.get("error")]
        if failed:
            # Never serve totals that silently leave a position out.
            reasons = [f"{row.get('symbol', '?')}: {row['error']}" for row in failed]
            return FunctionResult(
                code=self.code, instrument=None,
                data={"status": "calc_error",
                      "reason": "Greeks could not be computed for: " + "; ".join(reasons),
                      "next_actions": ["Fix or remove the failing positions and re-run."],
                      "rows": [], "methodology": _methodology(), "field_dictionary": _field_dictionary()},
                warnings=reasons,
            )
        for row, pos in zip(agg.get("positions", []), normalized):
            for key in ("spot_source", "vol_source", "rate_source"):
                if key in pos:
                    row[key] = pos[key]
            # Echo the interpreted decimal rate so the unit actually used is visible.
            if "r" in pos:
                row["rate"] = pos["r"]
        totals = agg.get("totals") or {}
        warnings: list[str] = []
        for i, pos in enumerate(normalized):
            if pos.get("rate_source") == "input_decimal":
                # A plain rate in (0, 0.2] is a valid decimal, but a user who typed
                # a percent (0.1 = 0.1%) would get 10% priced: say which one was used.
                rate = float(pos["r"])
                warnings.append(
                    f"position {i + 1} ({pos.get('symbol', '?')}): rate {rate:g} was read as a decimal "
                    f"and priced at {rate * 100:g}%; if you meant {rate:g}% enter r={rate / 100:g}")
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
        sources = (["black_scholes_model"] + (["yfinance"] if used_history else [])
                   + (["fred"] if used_rate else []))
        return FunctionResult(code=self.code, instrument=None, data=data, sources=sources, warnings=warnings)


def _methodology() -> str:
    return (
        "Aggregate contract-level Black-Scholes Greeks across the option book. The model prices European "
        "exercise in closed form, so American early exercise (common for listed puts and dividend payers) is "
        "not modelled. Each row is scaled by quantity and contract size; a missing contract size uses 100 and "
        "a missing dividend yield uses 0, both reported per row (contract_size_source / q) and in "
        "assumptions_used. Portfolio delta/gamma/vega/theta/rho are the sums across positions. "
        "A missing spot uses the symbol's last daily close and a missing vol its 30-day realized "
        "volatility (log returns, annualized with 252 days), and a missing rate the live 3-month T-bill "
        "yield (FRED DGS3MO); each is labelled per row (spot_source / vol_source / rate_source). A rate "
        "above 1 is read as a percent; a plain rate in (0.2, 1] is refused as ambiguous, and rate_pct or "
        "rate_bps give an explicit unit (rate_source records which one was used). Expiry is never assumed, "
        "and a position that cannot be priced "
        "fails the whole book instead of being left out of the totals."
    )


def _field_dictionary() -> dict[str, str]:
    return {
        "delta": "Change in option value for a one-unit spot move.",
        "gamma": "Change in delta for a one-unit spot move.",
        "vega": "Change in option value for a 1.00 volatility-point move.",
        "theta": "Time decay per year under the Black-Scholes convention used by the service.",
        "rho": "Change in option value for a 1.00 rate move.",
        "contract_size": "Multiplier applied to per-contract Greeks.",
        "contract_size_source": "input, or default_100 when contract_size was not supplied.",
        "q_source": "input, or default_0 when no dividend yield was supplied.",
        "spot_source": "input, or yfinance_last_close when spot was not supplied.",
        "vol_source": "input, or realized_30d when vol was not supplied.",
    }
