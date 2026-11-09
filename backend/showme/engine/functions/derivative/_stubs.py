"""Option analytics functions used by the derivative screens."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.derivative.ovme import _bs_price


_HVT_FIELDS = {
    "window_days": "Trailing close-to-close return window used for the realized-volatility estimate.",
    "realized_vol": "Annualized realized volatility as a decimal: stdev(daily returns) * sqrt(N), N = 252 trading days for equities/ETFs or 365 calendar days for crypto.",
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


def _vol_template(symbol: str, spot: float = 100.0) -> dict[str, Any]:
    seed = (sum(ord(ch) for ch in symbol.upper()) % 35) / 1000
    rv = {
        "rv_30d_annualized": round(0.22 + seed, 4),
        "rv_60d_annualized": round(0.24 + seed, 4),
        "rv_90d_annualized": round(0.26 + seed, 4),
        "rv_252d_annualized": round(0.29 + seed, 4),
    }
    rows = [
        {
            "metric": key.replace("_annualized", "").upper(),
            "window_days": int(key.split("_")[1].replace("d", "")),
            "realized_vol": value,
            "realized_vol_pct": value * 100,
            "samples": 0,
            "source_mode": "reference",
            "formula": "stdev(daily close returns) * sqrt(252)",
        }
        for key, value in rv.items()
    ]
    return {
        "status": "reference",
        "symbol": symbol,
        "spot": spot,
        "rows": rows,
        **rv,
        "summary": {"source_mode": "reference", "windows": len(rows)},
        "methodology": "Reference realized-volatility windows generated from a deterministic per-symbol seed; not live data.",
        "field_dictionary": _HVT_FIELDS,
    }


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "y", "t"}


async def _resolve_ivol_spot(
    deps: Any, instrument: Instrument, params: dict[str, Any],
) -> tuple[float, str]:
    """Pull the live underlying price for IVOL.

    Returns ``(spot, data_state)`` where ``data_state`` is one of
    ``"live_quote"`` (yfinance QUOTE adapter returned a finite value),
    ``"user_override"`` (caller passed ``spot`` in params),
    ``"synthetic_anchor"`` (no usable signal — fell back to 100).

    Mirrors the OMON ``_resolve_spot`` pattern so the two derivative
    functions stay in lock-step. Kept local to avoid an import-cycle
    with ``omon.py`` (which imports helpers from this module).
    """
    if "spot" in params and params.get("spot") is not None:
        try:
            value = float(params["spot"])
            if value > 0 and math.isfinite(value):
                return value, "user_override"
        except (TypeError, ValueError):
            pass
    yfinance = getattr(deps, "yfinance", None)
    if yfinance is None:
        return 100.0, "synthetic_anchor"
    from showme.engine.core.base_data_source import DataKind, DataRequest
    timeout = max(1.0, min(float(params.get("yfinance_timeout", 3)), 4.0))
    try:
        quote = await asyncio.wait_for(
            yfinance.fetch(DataRequest(
                kind=DataKind.QUOTE, instrument=instrument,
                extra={"timeout": timeout, "offline_ok": True},
            )),
            timeout=timeout + 0.5,
        )
    except Exception:
        return 100.0, "synthetic_anchor"
    last = getattr(quote, "last", None)
    try:
        value = float(last) if last is not None else 0.0
    except (TypeError, ValueError):
        return 100.0, "synthetic_anchor"
    if value > 0 and math.isfinite(value):
        return value, "live_quote"
    return 100.0, "synthetic_anchor"


def _finite(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return num


# A solver-failure IV is reported as ~0 (or 1e-5). Anything below this floor is
# not a usable implied vol and must not reach the surface.
_IV_FLOOR = 0.01


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    """First non-null value among ``keys`` (keeps a legitimate 0.0)."""
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _surface_rows(
    calls: list[dict[str, Any]],
    puts: list[dict[str, Any]],
    *,
    spot: float,
    dropped: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build surface cells from option-chain rows.

    A cell is dropped (and recorded in ``dropped`` when supplied) when its
    implied vol is missing or below ``_IV_FLOOR`` (solver failure), or when its
    quoted mid is below intrinsic value at spot. SPY options are American, so
    the price must be at least intrinsic (``max(S-K,0)`` / ``max(K-S,0)``); a
    mid below that has no real implied vol.
    """
    rows: list[dict[str, Any]] = []
    for option_type, source_rows in (("CALL", calls), ("PUT", puts)):
        for row in source_rows:
            strike = _finite(row.get("strike"))
            vol = _finite(_first_present(row, "impliedVolatility", "iv"))
            if strike is None:
                continue
            expiry = str(row.get("expiry") or row.get("expiration") or row.get("expiration_date") or "-")
            bid = _finite(row.get("bid"))
            ask = _finite(row.get("ask"))
            last = _finite(row.get("lastPrice") or row.get("last"))
            mid = (bid + ask) / 2 if bid is not None and ask is not None and ask >= bid else last
            if vol is None or vol < _IV_FLOOR:
                if dropped is not None:
                    dropped.append({"label": f"{expiry} {option_type[0]} {strike:g}",
                                    "reason": "iv_missing_or_below_floor"})
                continue
            if spot > 0 and mid is not None:
                intrinsic = max(spot - strike, 0.0) if option_type == "CALL" else max(strike - spot, 0.0)
                if mid < intrinsic:
                    if dropped is not None:
                        dropped.append({"label": f"{expiry} {option_type[0]} {strike:g}",
                                        "reason": "mid_below_intrinsic"})
                    continue
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


_ATM_MAX_DISTANCE = 0.10


def _ivol_atm_iv(cells: list[dict[str, Any]]) -> float | None:
    """ATM IV for one expiry: mean of call and put IV at the listed strike nearest spot.

    Only strikes quoted on BOTH sides qualify, so the value is never a single-side
    IV passed off as the call/put average (IVOL#2). This is deliberately stricter than
    the OMON pane, which takes the strike nearest spot whichever side is quoted
    (omon.py ATM block): the two agree only when that nearest strike is two-sided.
    No interpolation is used for ATM; no qualifying strike within
    ``_ATM_MAX_DISTANCE`` of spot gives None.
    """
    by_strike: dict[float, dict[str, list[float]]] = {}
    for cell in cells:
        by_strike.setdefault(round(cell["moneyness"], 6), {}).setdefault(cell["side"], []).append(cell["vol"])
    candidates = [
        m for m, sides in by_strike.items()
        if "CALL" in sides and "PUT" in sides and abs(m - 1.0) <= _ATM_MAX_DISTANCE
    ]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda m: (abs(m - 1.0), m))
    sides = by_strike[nearest]
    call_iv = sum(sides["CALL"]) / len(sides["CALL"])
    put_iv = sum(sides["PUT"]) / len(sides["PUT"])
    return (call_iv + put_iv) / 2


def _ivol_side_at(cells: list[dict[str, Any]], side: str, target: float) -> float | None:
    """IV of one side at an exact moneyness, linearly interpolated between listed strikes.

    Never extrapolates: a target outside the listed strike range of that side gives None (IVOL#3).
    """
    by_m: dict[float, list[float]] = {}
    for cell in cells:
        if cell["side"] == side:
            by_m.setdefault(round(cell["moneyness"], 6), []).append(cell["vol"])
    points = sorted((m, sum(vols) / len(vols)) for m, vols in by_m.items())
    for m, vol in points:
        if abs(m - target) < 1e-9:
            return vol
    for (m0, v0), (m1, v1) in zip(points, points[1:]):
        if m0 < target < m1:
            weight = (target - m0) / (m1 - m0)
            return v0 + weight * (v1 - v0)
    return None


def _ivol_atm_term_and_skew(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Derive the ATM term structure + front-expiry skew from real surface rows.

    Every value is read off the shipped surface cells (no constants, nothing invented).
    Any expiry without usable cells is skipped rather than fabricated.

    * ATM IV per expiry: see ``_ivol_atm_iv`` (call/put average at the nearest two-sided strike).
    * Skew (90-110) = IV(OTM put at 90% moneyness) - IV(OTM call at 110% moneyness), on the
      front expiry, each side interpolated on its own listed strikes.

    Returns ``(stats, series)`` where stats are DECIMALS (front/back ATM IV,
    skew, ``back - front`` slope, and the two skew legs) and ``series`` is the
    per-expiry ATM IV term structure consumed by the pane sparkline.
    """
    by_expiry: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for row in rows:
        expiry = str(row.get("expiry") or "")
        vol = _finite(row.get("vol") if row.get("vol") is not None else row.get("iv"))
        moneyness = _finite(row.get("moneyness"))
        side = str(row.get("option_type") or "").upper()
        if not expiry or vol is None or moneyness is None or side not in ("CALL", "PUT"):
            continue
        if expiry not in by_expiry:
            by_expiry[expiry] = []
            order.append(expiry)
        by_expiry[expiry].append({"moneyness": moneyness, "vol": vol, "side": side})

    series: list[dict[str, Any]] = []
    for expiry in order:
        atm = _ivol_atm_iv(by_expiry[expiry])
        if atm is not None:
            series.append({"t": expiry, "v": round(atm, 6)})
    front = series[0]["v"] if series else None
    back = series[-1]["v"] if series else None
    iv_put_90: float | None = None
    iv_call_110: float | None = None
    skew: float | None = None
    if series:
        front_cells = by_expiry.get(str(series[0]["t"])) or []
        iv_put_90 = _ivol_side_at(front_cells, "PUT", 0.90)
        iv_call_110 = _ivol_side_at(front_cells, "CALL", 1.10)
        if iv_put_90 is not None and iv_call_110 is not None:
            skew = round(iv_put_90 - iv_call_110, 6)
    term_slope: float | None = None
    if front is not None and back is not None:
        term_slope = round(back - front, 6)
    stats = {
        "atm_iv_front": front,
        "atm_iv_back": back,
        "skew": skew,
        "term_slope": term_slope,
        "skew_put_iv_90": iv_put_90,
        "skew_call_iv_110": iv_call_110,
    }
    return stats, series


TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365


def _annualization_days(instrument: Instrument | None) -> int:
    """Days per year used to annualize daily returns for this instrument.

    Crypto trades every calendar day, so its daily returns are annualized on
    365 days; equities and ETFs use the 252-trading-day convention.
    """
    if instrument is not None and instrument.asset_class == AssetClass.CRYPTO:
        return CALENDAR_DAYS_PER_YEAR
    return TRADING_DAYS_PER_YEAR


def _vol_rows_from_returns(
    rets: Any, windows: list[int], annualization: int = TRADING_DAYS_PER_YEAR,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in windows:
        sample = rets.tail(window)
        if len(sample) < max(5, min(window, 20)):
            continue
        vol = float(sample.std() * np.sqrt(annualization))
        rows.append({
            "metric": f"{window}D realized vol",
            "window_days": window,
            "realized_vol": vol,
            "realized_vol_pct": vol * 100,
            "samples": int(len(sample)),
            "formula": f"stdev(daily close returns) * sqrt({annualization})",
        })
    return rows


def _rolling_vol_history(
    rets: Any, window: int, annualization: int = TRADING_DAYS_PER_YEAR,
) -> list[dict[str, Any]]:
    if len(rets) < max(6, window):
        window = max(5, min(window, max(5, len(rets) // 2)))
    rolling = rets.rolling(window).std().dropna() * np.sqrt(annualization)
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
    # HNT-14 fix: the provider_unavailable envelope must not carry
    # fabricated realized-vol rows (the old shape filled ``rows`` with
    # seed-derived constants that rendered like real numbers despite the
    # warning banner). Only the reason + next_actions remain; the
    # formula/methodology text is kept so the pane can still explain what
    # HVT would compute.
    return {
        "status": "provider_unavailable",
        "reason": reason,
        "symbol": symbol,
        "rows": [],
        "summary": {"source_mode": "provider_unavailable", "windows": 0},
        "methodology": "Live daily close history is required for HVT. The realized-vol formula is stdev(daily close returns) * sqrt(N), N = 252 for equities/ETFs and 365 for crypto.",
        "field_dictionary": _HVT_FIELDS,
        "next_actions": ["Retry with a supported symbol or configure the yfinance data adapter."],
    }


def _osa_finite_positive(value: Any) -> float | None:
    """A finite, strictly positive float, else None (never a default)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _osa_rate_input(params: dict[str, Any], key: str, default: float) -> tuple[float | None, str, str]:
    """A rate/yield fraction from ``params[key]``: ``(value, source, reason)``.

    A missing or null value takes ``default`` (source ``default``). A supplied
    value must be a finite number; otherwise ``value`` is None and ``reason``
    says what is wrong. Never raises.
    """
    raw = params.get(key)
    if raw is None:
        return default, "default", ""
    if not isinstance(raw, bool):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = None
        if value is not None and math.isfinite(value):
            return value, "param", ""
    return None, "", (
        f"{key} must be a finite decimal fraction (for example 0.045 for 4.5%), "
        f"got {raw!r}."
    )


async def _osa_live_spot(deps: Any, underlying: str, params: dict[str, Any]) -> tuple[float | None, str]:
    """Live last price for the OSA underlying from the yfinance QUOTE adapter.

    Returns ``(price, "")`` or ``(None, reason)``. Never substitutes a number.
    """
    yfinance = getattr(deps, "yfinance", None)
    if yfinance is None:
        return None, "the yfinance quote adapter is not configured"
    try:
        timeout = max(1.0, min(float(params.get("yfinance_timeout", 3)), 4.0))
    except (TypeError, ValueError):
        timeout = 3.0
    try:
        quote = await asyncio.wait_for(
            yfinance.fetch(DataRequest(
                kind=DataKind.QUOTE,
                instrument=Instrument(symbol=underlying, asset_class=AssetClass.EQUITY),
                extra={"timeout": timeout, "offline_ok": True},
            )),
            timeout=timeout + 0.5,
        )
    except Exception as exc:  # noqa: BLE001 - reported as an honest provider state
        return None, f"the quote request failed ({type(exc).__name__})"
    value = _osa_finite_positive(getattr(quote, "last", None))
    if value is None:
        return None, "the quote carried no last price"
    return value, ""


# A payoff slope below this (P&L per unit of underlying) counts as flat: a limit
# that is approached asymptotically, not a payoff that keeps growing.
_OSA_FLAT_SLOPE = 1e-3


def _osa_extreme_state(pnls: list[float], step: float, *, want_max: bool) -> str:
    """Classify a grid extreme as ``bounded``, ``grid_edge`` or ``unbounded``.

    ``unbounded``: the payoff still moves in the direction of the extreme at the
    top of the grid, so the true extreme is beyond the range.
    ``grid_edge``: the extreme sits at the bottom of the grid and the payoff is
    still moving that way, so it may lie below the grid.
    ``bounded``: the extreme is interior or on a flat plateau.
    """
    if len(pnls) < 2 or step <= 0:
        return "bounded"
    high_slope = (pnls[-1] - pnls[-2]) / step
    low_slope = (pnls[1] - pnls[0]) / step
    if want_max:
        if high_slope > _OSA_FLAT_SLOPE:
            return "unbounded"
        if pnls.index(max(pnls)) == 0 and low_slope < -_OSA_FLAT_SLOPE:
            return "grid_edge"
        return "bounded"
    if high_slope < -_OSA_FLAT_SLOPE:
        return "unbounded"
    if pnls.index(min(pnls)) == 0 and low_slope > _OSA_FLAT_SLOPE:
        return "grid_edge"
    return "bounded"


def _osa_needs_input(
    reason: str,
    instrument: Instrument | None,
    *,
    status: str = "needs_input",
    underlying: str | None = None,
    next_actions: list[str] | None = None,
) -> FunctionResult:
    """OSA input gap: no priced curve, no placeholder numbers, explicit reason."""
    if next_actions is None:
        if status == "provider_unavailable":
            next_actions = [
                f"Retry the live quote for {underlying or 'the underlying'}, or enter a spot price.",
            ]
        else:
            next_actions = [
                "Enter a positive spot price, or an underlying ticker to take its live quote.",
                "Give every leg a CALL/PUT type, positive strike, positive expiry in years, "
                "signed qty and an implied vol (or a market_price to solve it).",
            ]
    return FunctionResult(
        code="OSA",
        instrument=instrument,
        data={
            "status": status,
            "reason": reason,
            "underlying": underlying,
            "spot": None,
            "spot_source": None,
            "legs": [],
            "rows": [],
            "curve": [],
            "pnl_curve": [],
            "summary": {},
            "methodology": (
                "Premiums use Black-Scholes-Merton at the spot used (entered, or the "
                "underlying's live quote), with the per-leg implied vol entered (or solved "
                "from market_price). Nothing is priced until every input is supplied."
            ),
            "next_actions": next_actions,
        },
        sources=["black_scholes_formula"],
    )


@FunctionRegistry.register
class OSAFunction(BaseFunction):
    """OSA — Option Strategy Analysis."""
    code = "OSA"
    name = "Option Strategy Analysis"
    asset_classes = (AssetClass.DERIVATIVE,)
    category = "derivative"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # T10 (honesty): OSA never invents a spot, a strike/expiry template or a
        # vol. Missing inputs return an explicit needs_input state.
        legs = params.get("legs") or []
        if not isinstance(legs, list) or not legs:
            return _osa_needs_input(
                "Add at least one option leg (side, type, strike, expiry, vol).",
                instrument,
            )
        # Rate and dividend yield are parsed before any network call: a bad
        # value is an input gap, never an exception or a silent default.
        r, rate_source, rate_reason = _osa_rate_input(params, "rate", 0.045)
        q, div_source, div_reason = _osa_rate_input(params, "div_yield", 0.0)
        if r is None or q is None:
            return _osa_needs_input(
                rate_reason or div_reason,
                instrument,
                next_actions=["Enter the rate and dividend yield as decimal fractions, or leave them blank for the defaults."],
            )
        # OSA#2: spot is the caller's entered value, else the underlying's live
        # quote, else an explicit provider/input state. Never a default number.
        spot_source = "user_override"
        S = _osa_finite_positive(params.get("spot"))
        underlying = str(params.get("underlying") or params.get("symbol") or "").strip().upper() or None
        if S is None and underlying is None:
            return _osa_needs_input(
                "Enter a spot price, or an underlying ticker to take its live quote.",
                instrument,
            )
        if S is None:
            S, quote_reason = await _osa_live_spot(self.deps, underlying or "", params)
            if S is None:
                return _osa_needs_input(
                    f"No live quote for {underlying}: {quote_reason}. "
                    "Enter a spot price to price the strategy.",
                    instrument,
                    status="provider_unavailable",
                    underlying=underlying,
                )
            spot_source = "live_quote"
        initial_premiums: list[dict[str, Any]] = []
        net_debit = 0.0
        # D03-2026-05-24 (H19): per-leg vol resolution — if a leg quotes a
        # market price, solve the IV implied by that market price. A leg with
        # neither an entered vol nor a solvable market price is an input gap,
        # not a 0.25 placeholder.
        for idx, leg in enumerate(legs, start=1):
            if not isinstance(leg, dict):
                return _osa_needs_input(f"Leg {idx} is not a valid leg object.", instrument)
            strike = _osa_finite_positive(leg.get("strike"))
            expiry = _osa_finite_positive(leg.get("expiry") or leg.get("years_to_expiry"))
            if strike is None or expiry is None:
                return _osa_needs_input(
                    f"Leg {idx} needs a positive strike and expiry (years).", instrument,
                )
            opt_type = str(leg.get("type") or "").upper()
            if opt_type not in {"CALL", "PUT"}:
                return _osa_needs_input(f"Leg {idx} type must be CALL or PUT.", instrument)
            try:
                qty = float(leg.get("qty"))
            except (TypeError, ValueError):
                return _osa_needs_input(f"Leg {idx} needs a numeric quantity (qty).", instrument)
            vol = leg.get("vol")
            iv_source = "input"
            market = leg.get("market_price")
            if market is not None and (vol is None or vol == 0):
                try:
                    from showme.engine.services.iv_solver import implied_vol
                    iv_res = implied_vol(
                        market_price=float(market), S=S, K=strike, T=expiry,
                        r=r, q=q, is_call=opt_type == "CALL",
                    )
                    if iv_res.get("converged"):
                        vol = iv_res["iv"]
                        iv_source = f"solved_{iv_res['method']}"
                except Exception:
                    pass
            vol_value = _osa_finite_positive(vol)
            if vol_value is None:
                return _osa_needs_input(
                    f"Leg {idx} has no valid implied vol (vol) and its market_price could not "
                    "be solved for one.",
                    instrument,
                )
            vol = vol_value
            premium = _bs_price(S, strike, expiry, r, vol, q, opt_type == "CALL")["price"]
            net_debit += qty * premium
            initial_premiums.append({
                "leg": idx,
                "qty": qty,
                "type": opt_type,
                "strike": strike,
                "expiry_years": expiry,
                "vol": vol,
                "iv_source": iv_source,
                "premium": premium,
                "initial_value": qty * premium,
            })
        # H17: derive grid from strike range, not 50-150% of spot. Low-priced
        # underlyings (e.g. S=20) with wing strikes outside that range used
        # to fall off the chart.
        strike_list = [float(leg["strike"]) for leg in legs] or [S]
        max_strike = max(strike_list + [S])
        min_strike = min(strike_list + [S])
        spot_low = min(min_strike * 0.5, S * 0.5)
        spot_high = max(max_strike * 1.2, S * 1.5)
        # 101 evenly-spaced grid points.
        n_grid = 101
        step = (spot_high - spot_low) / (n_grid - 1) if n_grid > 1 else 0.0
        spots = [spot_low + i * step for i in range(n_grid)]
        pnl_curve: list[dict] = []
        # H18 (revised by HNT-03): compound the initial debit FORWARD to the
        # expiration horizon so the P&L curve compares cash flows at the same
        # point in time. ``expiry_payoff`` is a T-moment cash flow; the t=0
        # debit must carry the financing cost net_debit * exp(+r * max_T).
        # The old PV discount (exp(-rT)) understated the cost and inflated
        # every pnl point by roughly r*T*net_debit.
        # OSA-1: legs with different expiries must share one valuation date.
        # The position is marked at the FIRST expiry: legs that expire there
        # pay intrinsic value, longer legs are marked at Black-Scholes with
        # their remaining time and the same per-leg vol. Valuing every leg at
        # intrinsic on the longest horizon zeroed out a calendar's time value.
        leg_expiries = [float(prem["expiry_years"]) for prem in initial_premiums]
        t_eval = min(leg_expiries, default=0.25)
        fv_debit = net_debit * math.exp(r * t_eval)
        leg_terms: list[tuple[float, float, float, str, float, float]] = []
        for leg, t_leg, prem in zip(legs, leg_expiries, initial_premiums):
            leg_terms.append((
                float(leg["strike"]),
                float(leg.get("qty") or 0),
                t_leg,
                str(leg.get("type") or "CALL").upper(),
                float(prem["vol"]),
                float(q),
            ))
        for s in spots:
            expiry_payoff = 0.0
            for strike, qty, t_leg, opt_type, vol_leg, q_leg in leg_terms:
                if t_leg <= t_eval + 1e-12:
                    value = max(s - strike, 0.0) if opt_type == "CALL" else max(strike - s, 0.0)
                else:
                    value = _bs_price(s, strike, t_leg - t_eval, r, vol_leg, q_leg,
                                      opt_type == "CALL")["price"]
                expiry_payoff += qty * value
            pnl_curve.append({
                "spot": s,
                "pnl": expiry_payoff - fv_debit,
                "payoff": expiry_payoff,
                "net_debit": net_debit,
                "fv_debit": fv_debit,
            })
        pnls = [row["pnl"] for row in pnl_curve]
        return FunctionResult(code=self.code, instrument=instrument,
                              data={
                                  "status": "ok",
                                  "underlying": underlying,
                                  "spot": S,
                                  "spot_source": spot_source,
                                  "rate": r,
                                  "rate_source": rate_source,
                                  "div_yield": q,
                                  "div_yield_source": div_source,
                                  "strategy": params.get("strategy") or "custom",
                                  "rows": initial_premiums,
                                  "legs": initial_premiums,
                                  "curve": pnl_curve,
                                  "pnl_curve": pnl_curve,
                                  "summary": {
                                      "net_debit": net_debit,
                                      "evaluation_horizon_years": t_eval,
                                      "multi_expiry": len(set(leg_expiries)) > 1,
                                      "max_gain_visible": max(pnls),
                                      "max_loss_visible": min(pnls),
                                      # OSA#3: the grid only samples a window. A
                                      # payoff still moving at the grid edge is
                                      # unbounded (or extends past it), not capped.
                                      "max_gain_state": _osa_extreme_state(pnls, step, want_max=True),
                                      "max_loss_state": _osa_extreme_state(pnls, step, want_max=False),
                                      "grid_low": spot_low,
                                      "grid_high": spot_high,
                                      "breakeven_count_visible": sum(
                                          1
                                          for prev, cur in zip(pnls, pnls[1:])
                                          if (prev <= 0 <= cur) or (prev >= 0 >= cur)
                                      ),
                                  },
                                  "methodology": "Horizon P&L at the first expiry = sum(qty * value at spot) - fv_debit. Legs expiring at the horizon are valued at intrinsic payoff; longer legs are valued with Black-Scholes-Merton at their remaining time and per-leg IV. fv_debit = net_debit * exp(+r * horizon) carries the initial debit to the same horizon. Premiums use Black-Scholes-Merton with per-leg IV (entered vol, or solved from market_price). Spot is the entered value or the underlying's live quote (spot_source says which).",
                                  "field_dictionary": {
                                      "net_debit": "Positive value means the strategy costs premium up front; negative means a credit.",
                                      "curve.pnl": "Estimated expiration profit/loss at each underlying spot.",
                                      "premium": "Black-Scholes-Merton premium at the current spot.",
                                  },
                              },
                              sources=["black_scholes_formula"]
                              + (["yfinance"] if spot_source == "live_quote" else []))


@FunctionRegistry.register
class HVTFunction(BaseFunction):
    """HVT — Historical Volatility Trends."""
    code = "HVT"
    name = "Historical Volatility Trends"
    asset_classes = (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.ETF)
    category = "derivative"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("HVT requires a symbol")
        symbol = instrument.symbol
        # D04-2026-06-01 (de-garbage): the realized-vol term structure is now
        # fetched LIVE from yfinance daily OHLCV by default. The old gate
        # required an opt-in ``live_vol`` flag and otherwise returned a
        # deterministic per-symbol seed (canned constants), which made the
        # product claim a lie. Callers can still force the offline reference
        # template by passing ``reference=true`` (used by tests / air-gapped
        # demos); genuine provider failure falls back to the labeled
        # provider_unavailable reference shape.
        if _truthy(params.get("reference")):
            spot = float(params.get("spot", 100))
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_vol_template(symbol, spot),
                sources=["historical_vol_reference"],
                metadata={"live": False, "mode": "reference"},
            )
        if not self.deps.yfinance:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_reference_hvt(symbol, float(params.get("spot", 100)),
                                    reason="yfinance adapter unavailable"),
                sources=[],
                metadata={"live": False, "fallback": True,
                          "provider_errors": ["yfinance adapter unavailable"]},
            )
        timeout = max(1.0, min(float(params.get("yfinance_timeout", 4)), 6.0))
        days = max(30, min(int(params.get("days") or params.get("lookback_days") or 365), 365 * 3))
        start = datetime.now(timezone.utc) - timedelta(days=days + 30)
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
                data=_reference_hvt(symbol, float(params.get("spot", 100)), reason=f"yfinance: {str(exc) or type(exc).__name__}"),
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
        annualization = _annualization_days(instrument)
        windows = [30, 60, 90, min(252, max(30, days))]
        rows = _vol_rows_from_returns(rets, sorted(set(windows)), annualization)
        history_window = min(30, max(10, days // 3))
        history = _rolling_vol_history(rets, history_window, annualization)
        current_spot = float(closes.iloc[-1]) if len(closes) else float(params.get("spot", 100))
        calendar_note = (
            "crypto trades every calendar day, so N = 365 calendar days"
            if annualization == CALENDAR_DAYS_PER_YEAR
            else "equities/ETFs use N = 252 trading days"
        )
        out = {
            "status": "ok",
            "symbol": symbol,
            "spot": current_spot,
            "lookback_days": days,
            "annualization_days": annualization,
            "rows": rows,
            "history": history,
            "summary": {
                "current_realized_vol": rows[0]["realized_vol"] if rows else None,
                "current_realized_vol_pct": rows[0]["realized_vol_pct"] if rows else None,
                "observations": int(len(rets)),
                "history_window_days": history_window,
                "annualization_days": annualization,
            },
            "methodology": (
                f"Annualized realized volatility = stdev(daily close-to-close returns) * sqrt({annualization}); "
                f"{calendar_note}. Rolling history uses the selected chart window."
            ),
            "field_dictionary": _HVT_FIELDS,
        }
        return FunctionResult(code=self.code, instrument=instrument, data=out,
                              sources=["yfinance"],
                              metadata={"live": True, "data_mode": "live_yfinance"})


def _ivol_public_spot(spot: float | None, spot_state: str) -> float | None:
    """A synthetic anchor is not a price: it is never reported as ``spot`` (placeholder 100)."""
    return None if spot_state == "synthetic_anchor" else spot


def _ivol_front_days(expiry: str | None, now: datetime) -> int | None:
    if not expiry:
        return None
    try:
        return (datetime.strptime(expiry, "%Y-%m-%d").date() - now.date()).days
    except (TypeError, ValueError):
        return None


def _ivol_as_of(*row_sets: list[dict[str, Any]]) -> str | None:
    """Newest option ``lastTradeDate`` across the fetched chains, as a snapshot-time proxy."""
    newest: datetime | None = None
    for rows in row_sets:
        for row in rows:
            raw = row.get("lastTradeDate")
            # IVOL#4-RQ: a missing trade time (None, NaN or pd.NaT) carries no stamp.
            # NaT is a datetime subclass and compares False with ">", so it must be
            # dropped here or it pins the as-of to the string 'NaT'.
            if raw is None or raw != raw:
                continue
            try:
                ts = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if ts is None or ts != ts:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if newest is None or ts > newest:
                newest = ts
    return newest.isoformat() if newest else None


def _ivol_unavailable(
    instrument: Instrument,
    *,
    spot: float,
    spot_state: str,
    reason: str,
    next_actions: list[str],
    sources: list[str],
    provider_errors: list[str],
    expiries: list[str] | None = None,
) -> FunctionResult:
    """Explicit empty state: no surface, no template, no placeholder spot."""
    return FunctionResult(
        code="IVOL",
        instrument=instrument,
        data={
            "status": "provider_unavailable",
            "reason": reason,
            "symbol": instrument.symbol,
            "spot": _ivol_public_spot(spot, spot_state),
            "data_state": spot_state,
            "expiries": expiries or [],
            "rows": [],
            "surface": [],
            "series": [],
            "summary": {"contracts": 0, "expiries": 0, "source_mode": "provider_unavailable"},
            "methodology": "Live implied volatility surface from option-chain impliedVolatility by expiry, strike, and option type. No surface is shown without a live spot and a live chain.",
            "field_dictionary": _IVOL_FIELDS,
            "next_actions": next_actions,
        },
        sources=sources,
        metadata={"live": False, "fallback": True,
                  "spot_source": spot_state,
                  "provider_errors": provider_errors},
    )


@FunctionRegistry.register
class IVOLFunction(BaseFunction):
    """IVOL — Implied Vol Surface."""
    code = "IVOL"
    name = "Implied Vol Surface"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF, AssetClass.DERIVATIVE)
    category = "derivative"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("IVOL requires a symbol")
        # A02-2026-05-24: previously every non-live branch returned
        # ``spot=100`` even when SPY traded at $525, which threw every
        # strike on the surface into bizarro-moneyness territory and
        # made the UI vol-surface anchor a lie. We now try to fill it
        # from the live quote adapter first; a missing spot is reported
        # as ``spot: null`` with ``data_state: synthetic_anchor``.
        spot, spot_state = await _resolve_ivol_spot(self.deps, instrument, params)
        # D04-2026-06-01 (de-garbage): the implied-vol surface is now pulled
        # LIVE from the yfinance option chain by default. Callers can still
        # force the offline reference surface with ``reference=true`` (tests /
        # air-gapped demos); it is labelled ``reference`` and never presented
        # as live. Genuine provider failure returns the explicit
        # provider_unavailable shape below, never a template.
        if _truthy(params.get("reference")):
            # T10 placeholder_value: the constant-IV reference template is retired. It was built from
            # assumed skew offsets, not market data, so it is never served, whatever spot is known.
            return _ivol_unavailable(
                instrument, spot=spot, spot_state=spot_state,
                reason=("reference=true asked for the offline reference surface, which is retired: it was "
                        "built from constant skew assumptions, not market data. No surface is shown."),
                next_actions=["Call IVOL without reference=true to request the live option chain.",
                              "Retry when the option-chain adapter responds."],
                sources=["yfinance"] if spot_state == "live_quote" else [],
                provider_errors=["reference surface retired (constant-IV template)"],
            )
        if not self.deps.yfinance:
            return _ivol_unavailable(
                instrument, spot=spot, spot_state=spot_state,
                reason="yfinance option-chain adapter unavailable.",
                next_actions=["Configure the yfinance data adapter, then rerun."],
                sources=[], provider_errors=["yfinance adapter unavailable"],
            )
        from showme.engine.core.base_data_source import DataKind, DataRequest
        timeout = max(1.0, min(float(params.get("yfinance_timeout", 4)), 6.0))
        spot_explicit = "spot" in params and params.get("spot") is not None
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
        # Pull true underlying spot from the live chain so moneyness is
        # calculated against the real price, not a placeholder. Caller can
        # still override by passing explicit `spot` in params.
        if not spot_explicit and isinstance(meta, dict):
            for key in ("underlyingPrice", "underlying_price", "spot", "last", "regularMarketPrice"):
                value = meta.get(key)
                try:
                    candidate = float(value) if value is not None else None
                except (TypeError, ValueError):
                    candidate = None
                if candidate is not None and math.isfinite(candidate) and candidate > 0:
                    spot = candidate
                    spot_state = "live_chain" if spot_state == "synthetic_anchor" else spot_state
                    break
        if spot_state == "synthetic_anchor":
            # Neither the quote nor the chain gave a real underlying price, so
            # strike moneyness (and every skew point) would be computed against
            # an invented number. Report that instead of a surface.
            return _ivol_unavailable(
                instrument, spot=spot, spot_state=spot_state,
                reason="No live underlying price was returned by the quote or option-chain adapters, so strike moneyness cannot be computed.",
                next_actions=["Retry when the quote adapter responds, or pass an explicit spot."],
                sources=["yfinance"], provider_errors=["no live underlying price"],
            )
        expiries = meta.get("expiries", []) if isinstance(meta, dict) else []
        expiries = expiries or []
        if not expiries:
            return _ivol_unavailable(
                instrument, spot=spot, spot_state=spot_state,
                reason=f"The option-chain provider returned no expirations for {instrument.symbol}.",
                next_actions=["Retry during market hours; the provider listed no option expirations."],
                sources=["yfinance"], provider_errors=["yfinance options expiries empty"],
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
        dropped_cells: list[dict[str, Any]] = []
        surface_rows = _surface_rows(raw_calls, raw_puts, spot=spot, dropped=dropped_cells)
        if not surface_rows and dropped_cells:
            # Every chain cell was a solver failure or below intrinsic. There is
            # no live IV to show, and the reference template would substitute
            # invented constant IVs, so report the empty state explicitly.
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "reason": "Every option-chain cell lacked a usable implied volatility (solver failure or mid below intrinsic).",
                    "symbol": instrument.symbol,
                    "spot": spot,
                    "data_state": spot_state,
                    "expiries": targets,
                    "rows": [],
                    "surface": [],
                    "series": [],
                    "dropped_cells": dropped_cells,
                    "summary": {
                        "contracts": 0,
                        "expiries": 0,
                        "source_mode": "provider_unavailable",
                        "dropped_invalid_iv": len(dropped_cells),
                    },
                    "methodology": "Live implied volatility surface from option-chain impliedVolatility. Cells with IV below 1 percent or a quoted mid below intrinsic value are dropped.",
                    "field_dictionary": _IVOL_FIELDS,
                    "next_actions": ["Retry during market hours or with a different expiry set; no usable implied vol was quoted."],
                },
                sources=["yfinance"],
                metadata={"live": False, "fallback": True,
                          "spot_source": spot_state,
                          "provider_errors": ["yfinance implied volatility cells all dropped"]},
            )
        if not surface_rows:
            # Chains came back with no call or put rows at all. The reference
            # template would substitute invented constant IVs, so report the
            # empty state explicitly instead (DATA POLICY: never template data).
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "reason": "The option chain returned no call or put rows for the requested expiries.",
                    "symbol": instrument.symbol,
                    "spot": spot,
                    "data_state": spot_state,
                    "expiries": targets,
                    "rows": [],
                    "surface": [],
                    "series": [],
                    "dropped_cells": dropped_cells,
                    "summary": {
                        "contracts": 0,
                        "expiries": 0,
                        "source_mode": "provider_unavailable",
                        "dropped_invalid_iv": len(dropped_cells),
                    },
                    "methodology": "Live implied volatility surface from option-chain impliedVolatility. No rows were returned, so no surface is shown.",
                    "field_dictionary": _IVOL_FIELDS,
                    "next_actions": ["Retry during market hours or with a different expiry set; the provider returned empty chains."],
                },
                sources=["yfinance"],
                metadata={"live": False, "fallback": True,
                          "spot_source": spot_state,
                          "provider_errors": ["yfinance implied volatility rows empty"]},
            )
        stats, series = _ivol_atm_term_and_skew(surface_rows)
        now = datetime.now(timezone.utc)
        front_expiry = str(series[0]["t"]) if series else None
        front_days = _ivol_front_days(front_expiry, now)
        warnings: list[str] = []
        if front_days is not None and front_days < 3:
            warnings.append(
                f"Front expiry {front_expiry} is {front_days} calendar day(s) away; implied vol is very "
                "sensitive to the time-to-expiry convention below about 3 days."
            )
        earliest = min((str(r["expiry"]) for r in surface_rows if r.get("expiry")), default=None)
        if front_expiry and earliest and front_expiry != earliest:
            warnings.append(
                f"Front ATM IV and skew use {front_expiry}: the nearest listed expiry {earliest} has no "
                f"two-sided strike (call and put) within {round(_ATM_MAX_DISTANCE * 100)}% of spot, so it is not used for them."
            )
        as_of = _ivol_as_of(raw_calls, raw_puts)
        return FunctionResult(code=self.code, instrument=instrument,
                              data={"status": "ok",
                                    "symbol": instrument.symbol,
                                    "spot": spot,
                                    "source_mode": "live_yfinance",
                                    "as_of": as_of,
                                    "as_of_basis": (
                                        "Newest option lastTradeDate across the fetched chains; a proxy for the "
                                        "snapshot time, which the provider does not publish."
                                        if as_of else
                                        "The provider supplied no lastTradeDate, so the snapshot time is unknown."
                                    ),
                                    "iv_convention": (
                                        "Implied vols are taken as reported by yfinance impliedVolatility. The "
                                        "provider's time-to-expiry and pricing model are not disclosed and are not recomputed here."
                                    ),
                                    "warnings": warnings,
                                    "expiries": targets,
                                    "rows": surface_rows,
                                    "surface": surface_rows,
                                    "series": series,
                                    "summary": {
                                        "contracts": len(surface_rows),
                                        "expiries": len(set(row["expiry"] for row in surface_rows)),
                                        "calls": sum(1 for row in surface_rows if row["option_type"] == "CALL"),
                                        "puts": sum(1 for row in surface_rows if row["option_type"] == "PUT"),
                                        "source_mode": "live_yfinance",
                                        "dropped_invalid_iv": len(dropped_cells),
                                        "front_days_to_expiry": front_days,
                                        **stats,
                                    },
                                    "dropped_cells": dropped_cells,
                                    "methodology": (
                                        "Live implied volatility surface from option-chain impliedVolatility by expiry, "
                                        "strike, and option type. Cells with IV below 1 percent (solver failure) or a "
                                        "quoted mid below intrinsic value are dropped and counted in summary.dropped_invalid_iv. "
                                        "ATM IV = mean of call and put IV at the listed strike nearest spot quoted on both sides. "
                                        "Skew (90-110) = IV(put at 90% moneyness) minus IV(call at 110% moneyness) on the front "
                                        "expiry, each linearly interpolated on its own strikes; null when a point is outside the listed strikes."
                                    ),
                                    "field_dictionary": _IVOL_FIELDS},
                              sources=["yfinance"],
                              metadata={"live": True, "data_mode": "live_yfinance",
                                        "calls": sum(1 for row in surface_rows if row["option_type"] == "CALL"),
                                        "puts": sum(1 for row in surface_rows if row["option_type"] == "PUT")})
