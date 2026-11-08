"""FXFC, FXIP, WCRS, FRD, OVDV - FX function suite."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions._fred_csv import fetch_fred_csv_series
from showme.engine.functions.fx._frankfurter import fetch_frankfurter_rate, fetch_frankfurter_rates_dated
from showme.engine.services.fx_hedge import decimal_rate_error


_MAJOR_PAIRS = [
    "EURUSD",
    "USDJPY",
    "GBPUSD",
    "USDCHF",
    "AUDUSD",
    "USDCAD",
    "NZDUSD",
    "EURGBP",
    "EURJPY",
    "EURCHF",
    "GBPJPY",
]
_DEFAULT_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "TRY", "CHF"]
# H-4 honesty (2026-09-08): _REFERENCE_RATES / _REFERENCE_SPOTS /
# _seed_usd_value are 2024-era constants used ONLY as a labelled fallback
# when every live spot provider fails. The vintage is stamped into the
# fallback payloads (``reference_as_of``) so the UI can show
# "reference (2024-06)" instead of implying a current market level.
_REFERENCE_AS_OF = "2024-06"
_REFERENCE_RATES = {
    "USD": 0.045,
    "EUR": 0.035,
    "GBP": 0.044,
    "JPY": 0.005,
    "CHF": 0.012,
    "AUD": 0.041,
    "CAD": 0.038,
    "NZD": 0.052,
    "TRY": 0.45,
}
_REFERENCE_SPOTS = {
    "EURUSD": 1.0835,
    "GBPUSD": 1.256,
    "USDJPY": 154.2,
    "AUDUSD": 0.662,
    "USDCAD": 1.368,
    "USDCHF": 0.913,
    "EURGBP": 0.862,
    "EURJPY": 167.1,
    "GBPJPY": 193.7,
}

# Annualization factor for daily FX log returns (FX trades ~252 sessions/yr).
_FX_ANNUALIZATION = math.sqrt(252.0)
# Standard OTC tenors -> approximate trailing trading-day window used to size
# the realized-vol estimate at each point on the ATM term structure.
_TENOR_WINDOW_DAYS = {
    "1W": 5,
    "2W": 10,
    "1M": 21,
    "2M": 42,
    "3M": 63,
    "6M": 126,
    "9M": 189,
    "1Y": 252,
    "2Y": 504,
}
# OVDV#5: below this many daily returns a realized-vol estimate is statistically weak.
_OVDV_MIN_RELIABLE_RETURNS = 21
# OVDV#5: managed, crawling-peg or hard-pegged currencies. Their realized vol reflects
# a managed rate path, not an option-market level. Examples, not an exhaustive list.
_OVDV_MANAGED_CCYS = frozenset(
    {"TRY", "CNY", "CNH", "SAR", "AED", "HKD", "ARS", "EGP", "NGN", "PKR", "VND", "BDT", "QAR", "OMR", "BHD", "JOD", "KWD"}
)


@FunctionRegistry.register
class FXFCFunction(BaseFunction):
    """FXFC - FX forecasts from forward carry plus realized-vol bands."""

    code = "FXFC"
    name = "FX Forecasts"
    asset_classes = (AssetClass.FX,)
    category = "fx"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        base, quote, pair = _pair_from(instrument, params)
        rate_error = _rate_input_error(params)
        if rate_error:
            return _rate_error_result(self.code, instrument, pair, base, quote, rate_error)
        spot_quote_info: dict[str, Any] = {}
        spot, spot_source, source_mode = await _resolve_spot(
            self, pair, params, quote_info=spot_quote_info
        )
        # FXFC#2: only explicit policy-rate inputs drive the forward. The
        # 2024-06 reference table is not used here (DATA POLICY).
        r_base = _fxfc_policy_rate(params.get("r_base"))
        r_quote = _fxfc_policy_rate(params.get("r_quote"))
        rates_ready = r_base is not None and r_quote is not None
        rate_source = "user_inputs" if rates_ready else "none"
        missing_rates = [c for c, r in ((base, r_base), (quote, r_quote)) if r is None]
        tenors = _parse_tenors(params.get("tenors"), default=("1M", "3M", "6M", "12M"))
        # Band vol per tenor: an explicit input, or live realized FX vol. No
        # constant is substituted; with neither, the bands are null.
        vol_curve, vol_source, rv_source, vol_warning = await _fxfc_vol_curve(
            self, pair, tenors, params
        )
        rows = []
        for i, tenor in enumerate(tenors):
            t = tenor["years"]
            forward = _forward(spot, r_base, r_quote, t) if rates_ready else None
            vol = vol_curve[i] if vol_curve is not None else None
            band = spot * vol * (t ** 0.5) if (vol is not None and forward is not None) else None
            rows.append(
                {
                    "pair": pair,
                    "horizon": tenor["label"],
                    "tenor_years": round(t, 6),
                    "spot": round(spot, 6),
                    "forecast": round(forward, 6) if forward is not None else None,
                    "lower_band": round(forward - band, 6) if band is not None else None,
                    "upper_band": round(forward + band, 6) if band is not None else None,
                    "forward_points": round(forward - spot, 6) if forward is not None else None,
                    "vol_annualized": round(vol, 6) if vol is not None else None,
                    "source_mode": source_mode,
                }
            )
        now = _fxfc_now()
        market_open = _fx_market_open(now)
        spot_quote = _fxfc_spot_quote(spot_source, spot_quote_info, now)
        warnings: list[str] = []
        if missing_rates:
            warnings.append(
                f"policy rate not supplied for {', '.join(missing_rates)}: the CIP forward and bands are withheld "
                "(no reference-table or generic rate is substituted). Supply r_base and r_quote to compute them."
            )
        if source_mode == "reference_model":
            warnings.append(f"live spot unavailable; using labelled reference spot (vintage {_REFERENCE_AS_OF})")
        if vol_warning:
            warnings.append(vol_warning)
        spot_quote_status = spot_quote["spot_quote_status"]
        if spot_quote_status == "stale":
            warnings.append(
                f"yfinance spot quote is stale: its market time {spot_quote['spot_quote_time']} is "
                f"{spot_quote['spot_quote_age_minutes']} min before the fetch (threshold "
                f"{int(_FXFC_QUOTE_STALE_AFTER.total_seconds() // 60)} min); treat the spot as stale."
            )
        elif spot_quote_status == "off_session":
            warnings.append(
                f"yfinance spot quote time {spot_quote['spot_quote_time']} is outside the approximate "
                "FX session (Sun 22:00 to Fri 22:00 UTC): it is a last print, not a live level."
            )
        elif spot_quote_status == "quote_time_unavailable":
            warnings.append(
                "yfinance spot carries no upstream quote time, so its market age is unknown "
                f"(only the fetch time {now.isoformat()} is known)."
            )
            if not market_open:
                warnings.append(
                    "yfinance FX quote was fetched while the spot FX market is closed "
                    f"(weekend, fetched {now.isoformat()}); the level may be the last Friday print."
                )
        data = {
            "status": (
                "needs_input"
                if not rates_ready
                else ("ok" if vol_curve is not None else "bands_unavailable")
            ),
            "reason": (
                f"policy rate not supplied for {', '.join(missing_rates)} (r_base / r_quote)"
                if missing_rates
                else (vol_warning if vol_curve is None else None)
            ),
            "pair": pair,
            "base": base,
            "quote": quote,
            "spot": round(spot, 6),
            "spot_fetched_at": now.isoformat(),
            "fx_market_open_at_fetch": market_open,
            **spot_quote,
            "base_rate": r_base,
            "quote_rate": r_quote,
            "rate_source": rate_source,
            "vol_annualized": _fxfc_headline_vol(tenors, vol_curve),
            "vol_source": vol_source,
            "source_mode": source_mode,
            "forecast": rows,
            "curve": rows,
            "methodology": (
                "FXFC uses covered-interest-parity (CIP) forward carry as the deterministic forward path. "
                "Forecast = spot * (1 + quote_rate * T) / (1 + base_rate * T). This is a no-arbitrage "
                "forward level, not a consensus or predictive forecast. "
                "Bands are spot * sigma_T * sqrt(T), where sigma_T is the live realized FX vol over a "
                "trailing window sized to the tenor (yfinance daily closes), or an explicit vol_annualized "
                "input. When neither is available the bands are null; no constant vol is substituted. "
                "Bands are model bands, not vendor analyst forecasts."
            ),
            "field_dictionary": {
                "spot": "Quote currency units per one base currency unit.",
                "spot_fetched_at": "UTC time the spot was fetched (our clock, not the quote's market time).",
                "spot_quote_time": "The quote's own market time (UTC) when the provider supplied it; null otherwise.",
                "spot_quote_time_source": "upstream_market_time when spot_quote_time comes from the provider; null when no quote time is known.",
                "spot_quote_age_minutes": "Minutes between spot_quote_time and the fetch; null when spot_quote_time is unknown.",
                "spot_quote_status": "fresh (quote within 60 min and inside the FX session), stale (older than 60 min), off_session (quote time outside the FX session), quote_time_unavailable (no provider quote time), or not_applicable (spot not from yfinance).",
                "fx_market_open_at_fetch": "Whether the approximate spot-FX session (Sun 22:00 to Fri 22:00 UTC) was open at fetch time.",
                "forecast": "Covered-interest-parity forward-implied level for the tenor (a CIP forward, not a consensus forecast); null until r_base and r_quote are supplied.",
                "base_rate": "Base-currency annual rate (decimal) supplied as r_base; null when not supplied. No reference table is substituted.",
                "quote_rate": "Quote-currency annual rate (decimal) supplied as r_quote; null when not supplied.",
                "rate_source": "user_inputs when both r_base and r_quote are supplied, otherwise none.",
                "forward_points": "forecast - spot in quote currency units; null when the forward is withheld.",
                "vol_annualized": "Annualized band vol for the tenor (decimal); null when no vol source is available.",
                "vol_source": "live_realized_vol (yfinance daily closes), user_inputs, or none.",
                "lower_band": "forecast - spot * vol_annualized * sqrt(T); null when no vol source is available.",
                "upper_band": "forecast + spot * vol_annualized * sqrt(T); null when no vol source is available.",
                "source_mode": "live_yfinance_quote when a fresh quote was fetched; reference_model otherwise.",
            },
        }
        return FunctionResult(
            code=self.code,
            instrument=instrument or Instrument(symbol=pair, asset_class=AssetClass.FX),
            data=data,
            sources=_unique(
                [
                    spot_source,
                    "covered_interest_parity_formula",
                    rv_source or "",
                    "user_inputs_policy_rates" if rates_ready else "",
                ]
            ),
            warnings=warnings,
            metadata=(
                {"data_mode": "delayed_reference", "reference_as_of": _REFERENCE_AS_OF}
                if source_mode == "reference_model"
                else {"data_mode": source_mode}
            ),
        )


async def _fxfc_vol_curve(
    fn: BaseFunction,
    pair: str,
    tenors: list[dict[str, Any]],
    params: dict[str, Any],
) -> tuple[list[float] | None, str, str | None, str | None]:
    """Band vol per tenor for FXFC: ``(curve, vol_source, rv_source, warning)``.

    Precedence: an explicit ``vol_annualized`` / ``vol`` input (flat, labelled
    user_inputs), then live realized vol from the shared ATM term structure.
    ``curve`` is None when no vol can be sourced honestly.
    """
    explicit = params.get("vol_annualized", params.get("vol"))
    if explicit not in (None, ""):
        flat = max(0.0001, float(explicit))
        return [flat for _ in tenors], "user_inputs", None, None
    if not _truthy(params.get("live", True)):
        return (
            None,
            "none",
            None,
            "live=false: realized-vol history not requested; supply vol_annualized to view model bands",
        )
    curve, vol_source, _data_mode, rv_source, warning = await _atm_term_structure(
        fn, pair, tenors, params
    )
    if curve is None:
        return None, "none", None, warning or "realized vol unavailable; no band vol substituted"
    return curve, vol_source, rv_source, None


def _fxfc_headline_vol(tenors: list[dict[str, Any]], curve: list[float] | None) -> float | None:
    """The 1M band vol (or the first tenor when 1M is not requested), decimal."""
    if not curve:
        return None
    for i, tenor in enumerate(tenors):
        if str(tenor["label"]).upper() == "1M":
            return round(curve[i], 6)
    return round(curve[0], 6)


def _fxfc_policy_rate(explicit: Any) -> float | None:
    """FXFC policy rate: only an explicit input counts (FXFC#2).

    The 2024-06 reference table and its 0.04 generic fallback are not used on
    the FXFC forward path; a missing rate yields None so the forward is withheld.
    """
    if explicit in (None, ""):
        return None
    try:
        value = float(explicit)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _fxfc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fx_market_open(now: datetime) -> bool:
    """Approximate spot-FX session: open Sun 22:00 UTC to Fri 22:00 UTC.

    No holiday calendar. A quote fetched outside this window is a last print,
    not a live market level.
    """
    utc = now.astimezone(timezone.utc)
    weekday = utc.weekday()  # Mon=0 ... Sun=6
    minutes = utc.hour * 60 + utc.minute
    if weekday == 5:  # Saturday
        return False
    if weekday == 6:  # Sunday: opens at 22:00 UTC
        return minutes >= 22 * 60
    if weekday == 4:  # Friday: closes at 22:00 UTC
        return minutes < 22 * 60
    return True


_FXFC_QUOTE_STALE_AFTER = timedelta(minutes=60)


def _fxfc_spot_quote(spot_source: str, quote_info: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Quote-time state of the FXFC spot: provenance, age and a status flag.

    Only a provider-supplied quote time counts as a quote time. A quote without
    one reports ``quote_time_unavailable`` rather than the fetch time.
    """
    unknown: dict[str, Any] = {
        "spot_quote_time": None,
        "spot_quote_time_source": None,
        "spot_quote_age_minutes": None,
    }
    if spot_source != "yfinance":
        return {**unknown, "spot_quote_status": "not_applicable"}
    ts = quote_info.get("timestamp")
    if quote_info.get("timestamp_source") != "upstream_market_time" or not isinstance(ts, datetime):
        return {**unknown, "spot_quote_status": "quote_time_unavailable"}
    ts = ts.astimezone(timezone.utc)
    age = max(now.astimezone(timezone.utc) - ts, timedelta(0))
    if age > _FXFC_QUOTE_STALE_AFTER:
        status = "stale"
    elif not _fx_market_open(ts):
        status = "off_session"
    else:
        status = "fresh"
    return {
        "spot_quote_time": ts.isoformat(),
        "spot_quote_time_source": "upstream_market_time",
        "spot_quote_age_minutes": round(age.total_seconds() / 60, 2),
        "spot_quote_status": status,
    }


@FunctionRegistry.register
class FXIPFunction(BaseFunction):
    """FXIP - FX Information Portal."""

    code = "FXIP"
    name = "FX Information Portal"
    asset_classes = (AssetClass.FX,)
    category = "fx"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        base, quote, pair = _pair_from(instrument, params)
        rate_error = _rate_input_error(params)
        if rate_error:
            return _rate_error_result(self.code, instrument, pair, base, quote, rate_error)
        spot, spot_source, source_mode = await _resolve_spot(self, pair, params)
        r_base, base_rate_source = _fxip_rate(base, params.get("r_base"))
        r_quote, quote_rate_source = _fxip_rate(quote, params.get("r_quote"))
        # FXIP#2 follow-up: with an unlisted currency and no caller rate there
        # is no honest rate, so forwards and carry are null, not invented.
        rates_missing = r_base is None or r_quote is None
        missing_currencies = [c for c, r in ((base, r_base), (quote, r_quote)) if r is None]
        fwd_1m = None if rates_missing else round(_forward(spot, r_base, r_quote, 1 / 12), 6)
        fwd_3m = None if rates_missing else round(_forward(spot, r_base, r_quote, 0.25), 6)
        carry = None if rates_missing else round(r_quote - r_base, 6)
        atm_vol = float(params.get("atm_vol", params.get("vol", 0.0845)))
        rows = [
            {"metric": "spot", "value": round(spot, 6), "unit": f"{quote} per {base}", "source": spot_source},
            {"metric": "base_rate", "value": r_base, "unit": "decimal annual", "source": base_rate_source},
            {"metric": "quote_rate", "value": r_quote, "unit": "decimal annual", "source": quote_rate_source},
            {"metric": "1m_forward", "value": fwd_1m, "unit": "rate", "source": "covered_interest_parity"},
            {"metric": "3m_forward", "value": fwd_3m, "unit": "rate", "source": "covered_interest_parity"},
            {"metric": "atm_vol_1m_pct", "value": round(atm_vol * 100, 3), "unit": "percent", "source": "reference_vol_assumption"},
            {"metric": "carry_annualized", "value": carry, "unit": "decimal annual", "source": "rate_differential"},
        ]
        history, history_source = await _history_rows(self, pair, params)
        data = {
            "pair": pair,
            "base": base,
            "quote": quote,
            "spot": round(spot, 6),
            "daily_change_pct": _daily_change(history),
            "one_month_forward": fwd_1m,
            "three_month_forward": fwd_3m,
            # FXIP#1: the 1M ATM vol is an assumption (default 8.45 %), not a
            # market implied vol, so the key says "assumed".
            "assumed_vol_atm_1m_pct": round(atm_vol * 100, 3),
            "carry_annualized": carry,
            "source_mode": source_mode,
            "rate_basis": {"base": base_rate_source, "quote": quote_rate_source},
            "rows": rows,
            "history": history,
            "methodology": (
                "FXIP combines a spot quote, policy-rate inputs, forward levels from covered interest parity, "
                "and an optional Yahoo/ECB price history. The ATM volatility is an explicit assumption, not a market "
                "quote. Policy rates are caller inputs or dated reference constants (see rate_basis)."
            ),
            "field_dictionary": {
                "daily_change_pct": "Last history close change versus previous close, in percent; null when no usable history exists.",
                "one_month_forward": "1M covered-interest-parity forward.",
                "three_month_forward": "3M covered-interest-parity forward.",
                "assumed_vol_atm_1m_pct": "ASSUMED ATM volatility for 1M, in percent. Not a market implied vol.",
                "carry_annualized": "quote_rate - base_rate (positive means a long-base holder pays; negative means a long-base holder earns).",
                "rate_basis": f"Per-rate source: user_input, or reference_policy_rate_{_REFERENCE_AS_OF} (dated reference constant, not current).",
            },
        }
        sources = [spot_source, "covered_interest_parity_formula"]
        if any(src.startswith("reference_policy_rate") for src in (base_rate_source, quote_rate_source)):
            sources.append("reference_policy_rate")
        if history_source:
            sources.append(history_source)
        warnings: list[str] = []
        # manual_input + any live_* counts as a real spot; warn only for
        # the static reference_model fallback.
        if source_mode == "reference_model":
            warnings.append(f"live spot unavailable; using labelled reference spot (vintage {_REFERENCE_AS_OF})")
        # FXIP#2: the policy rates are 2024-06 reference constants unless the
        # caller supplied them; forwards and carry inherit that vintage.
        if any(src.startswith("reference_policy_rate") for src in (base_rate_source, quote_rate_source)):
            warnings.append(
                f"policy rates are reference constants (vintage {_REFERENCE_AS_OF}), not current rates; "
                "forwards and carry use them"
            )
        metadata: dict[str, Any] = (
            {"data_mode": "delayed_reference", "reference_as_of": _REFERENCE_AS_OF}
            if source_mode == "reference_model"
            else {"data_mode": source_mode}
        )
        if rates_missing:
            # No honest policy rate for an unlisted currency: explicit state,
            # never a substituted constant.
            data.update(
                {
                    "status": "needs_input",
                    "data_mode": "explicit_unavailable",
                    "reason": (
                        "No policy rate for "
                        + ", ".join(missing_currencies)
                        + f" in the {_REFERENCE_AS_OF} reference table; forwards and carry are unavailable."
                    ),
                    "next_actions": [
                        "Supply r_base and/or r_quote as decimal annual rates (e.g. 0.04) for the missing currency.",
                        "Forwards and carry are computed once both policy rates are known.",
                    ],
                }
            )
            warnings.append(
                "no reference policy rate for " + ", ".join(missing_currencies) + "; forwards and carry are null"
            )
            metadata = {"data_mode": "explicit_unavailable"}
        return FunctionResult(
            code=self.code,
            instrument=instrument or Instrument(symbol=pair, asset_class=AssetClass.FX),
            data=data,
            sources=_unique(sources),
            warnings=warnings,
            metadata=metadata,
        )


@FunctionRegistry.register
class WCRSFunction(BaseFunction):
    """WCRS - World Cross Rates matrix."""

    code = "WCRS"
    name = "World Cross Rates"
    category = "fx"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        bases = _currency_list(params.get("bases") or params.get("base"), default=_DEFAULT_CURRENCIES[:5])
        quotes = _currency_list(params.get("quotes"), default=_DEFAULT_CURRENCIES)
        history_budget = max(0.5, min(3.0, float(params.get("history_timeout", 2.5))))
        # History gate mirrors the matrix live gate (_wcrs_fx_live): an explicit
        # ``live_fx=false``, or ``live=false`` when live_fx is absent, turns both
        # off, so a pure reference matrix never mixes in live change values.
        live_enabled = _wcrs_fx_live(params)
        if live_enabled:
            # The per-currency history legs run concurrently with the matrix
            # fetch so the bounded history budget (max 3s) cannot stack on
            # top of the matrix latency.
            (matrix, source_mode, sources, as_of), (legs, leg_sources) = await asyncio.gather(
                _cross_matrix(self, bases, quotes, params),
                _usd_history_legs(
                    self,
                    _unique([*bases, *quotes]),
                    params,
                    budget=history_budget,
                ),
            )
        else:
            matrix, source_mode, sources, as_of = await _cross_matrix(self, bases, quotes, params)
            legs, leg_sources = {}, {}
        rows = []
        heatmap = []
        for base in bases:
            for quote in quotes:
                rate = float(matrix.get(base, {}).get(quote, 1.0 if base == quote else 0.0) or 0.0)
                heatmap.append({"base": base, "quote": quote, "pair": f"{base}{quote}", "rate": rate})
                if base == quote or rate <= 0:
                    continue
                # No keyless bid/ask source is wired, so bid, ask and spread are
                # null. A constructed spread (mid * 0.9999 / 1.0001) is the same
                # 0.02% for every pair and must never be shown as a market spread.
                # Real daily change from the derived cross history; null when
                # no usable history exists — never the old placeholder 0.0.
                change_pct: float | None = None
                if live_enabled:
                    history = _cross_history_points(base, quote, legs)
                else:
                    history = []
                if len(history) >= 2:
                    change_pct = _daily_change(history)
                row = {
                    "base": base,
                    "quote": quote,
                    "pair": f"{base}{quote}",
                    "rate": round(rate, 8),
                    "bid": None,
                    "ask": None,
                    "spread_pips": None,
                    "change_pct": change_pct,
                    "source_mode": source_mode,
                    "as_of": as_of,
                }
                if history:
                    # UI convention (WCRS/GLCO panes): per-row ``history`` is
                    # the numeric daily cross-close series, ascending.
                    row["history"] = [point["close"] for point in history]
                    row_sources = _unique([
                        leg_sources.get(base, ""),
                        leg_sources.get(quote, ""),
                    ])
                    if row_sources:
                        row["history_source"] = ",".join(row_sources)
                rows.append(row)
        data = {
            "status": "ok",
            "matrix": matrix,
            "rows": rows,
            "surface": heatmap,
            "source_mode": source_mode,
            "as_of": as_of,
            "methodology": (
                "WCRS builds a cross-rate matrix from live exchangerate.host quotes when available, "
                "else from the keyless ECB daily reference fix (Frankfurter), which is delayed to the "
                "fix date in as_of and is never presented as live. "
                "If both fail, it falls back to a labelled reference matrix (vintage in as_of). "
                "The daily change % and the per-row history are derived from keyless daily history legs "
                "(one USD leg per currency, cross = leg(quote)/leg(base)); when history is unavailable the "
                "change is null, never a placeholder 0.00%."
            ),
            "field_dictionary": {
                "rate": "Mid cross rate: quote currency units per one base currency unit.",
                "bid": "Real bid is null: no keyless bid/ask source is wired, so no bid is invented.",
                "ask": "Real ask is null: no keyless bid/ask source is wired, so no ask is invented.",
                "spread_pips": "Real spread in pips is null for the same reason; it is never constructed from the mid.",
                "change_pct": "Real daily percent change of the cross rate from the last two daily closes; null when no history is available.",
                "history": "Numeric daily cross-close series (ascending) for the sparkline; absent when history is unavailable.",
                "history_source": "Provider tier(s) the daily history legs came from (yfinance / ecb).",
                "source_mode": "live_exchangerate_host, official_daily_fix (ECB daily reference fix, dated by as_of), or reference_cross_rate_matrix.",
                "as_of": "Date of the rates: the ECB fix date for official_daily_fix, the stamped vintage for the reference matrix, null for live quotes without a provider timestamp.",
            },
        }
        if source_mode.startswith("live_"):
            warnings: list[str] = []
            metadata: dict[str, Any] = {"data_mode": source_mode}
        elif source_mode == "official_daily_fix":
            warnings = [
                "live cross-rate provider unavailable; showing the ECB daily reference fix "
                f"dated {as_of or 'unknown'} (delayed, not live)"
            ]
            metadata = {"data_mode": "delayed_reference", "as_of": as_of, "reference_as_of": as_of}
        else:
            warnings = [f"live cross-rate provider unavailable; using labelled reference matrix (vintage {_REFERENCE_AS_OF})"]
            metadata = {"data_mode": "delayed_reference", "reference_as_of": _REFERENCE_AS_OF}
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=data,
            sources=sources,
            warnings=warnings,
            metadata=metadata,
        )


@FunctionRegistry.register
class FRDFunction(BaseFunction):
    """FRD - Forward rates via covered interest parity.

    Policy-rate legs come from keyless FRED series when live or from caller input;
    a leg with neither returns provider_unavailable, never a stale constant (FRD#1). Manifest input names
    are honoured (FRD#2). Day count and forward-point units are stated (FRD#4).
    """

    code = "FRD"
    name = "FX Forward Rates"
    asset_classes = (AssetClass.FX,)
    category = "fx"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        params = _frd_canonical_params(params)
        base, quote, pair = _frd_pair(instrument, params)
        rate_error = _rate_input_error(params)
        if rate_error:
            return _rate_error_result(self.code, instrument, pair, base, quote, rate_error, day_count=_FRD_DAY_COUNT)
        spot, spot_source, source_mode = await _resolve_spot(self, pair, params)
        base_leg, quote_leg = await asyncio.gather(
            _frd_policy_rate(self, base, params.get("r_base"), params),
            _frd_policy_rate(self, quote, params.get("r_quote"), params),
        )
        rate_sources = {"base": base_leg["source"], "quote": quote_leg["source"]}
        rate_as_of = {"base": base_leg["as_of"], "quote": quote_leg["as_of"]}
        rate_warnings = [leg["warning"] for leg in (base_leg, quote_leg) if leg["warning"]]
        spot_warnings = (
            []
            if source_mode == "live_yfinance_quote"
            else [
                f"live spot unavailable; using labelled reference spot (vintage {_REFERENCE_AS_OF})"
                if source_mode == "reference_model"
                else f"spot is {source_mode}, not a live exchange quote"
            ]
        )
        warnings = spot_warnings + rate_warnings
        sources = _unique(
            [spot_source, "covered_interest_parity_formula", base_leg["source"], quote_leg["source"]]
        )
        metadata = (
            {"data_mode": "delayed_reference", "reference_as_of": _REFERENCE_AS_OF}
            if source_mode == "reference_model"
            else {"data_mode": source_mode}
        )
        if base_leg["rate"] is None or quote_leg["rate"] is None:
            # No honest rate for a leg: return an explicit state, never a made-up rate.
            return FunctionResult(
                code=self.code,
                instrument=instrument or Instrument(symbol=pair, asset_class=AssetClass.FX),
                data={
                    "status": "provider_unavailable",
                    "reason": "a currency leg has no caller-supplied rate and no live policy rate from FRED; no forward computed",
                    "next_actions": [
                        "Pass the policy rates explicitly as r_base and r_quote (decimal, e.g. 0.035 for 3.5%) to compute a forward.",
                        "Retry when the FRED policy-rate series (DFF, ECBDFR and the other central bank series) are reachable.",
                    ],
                    "pair": pair,
                    "base": base,
                    "quote": quote,
                    "S": round(spot, 6),
                    "rows": [],
                    "curve": [],
                    "rate_sources": rate_sources,
                    "rate_as_of": rate_as_of,
                    "day_count": _FRD_DAY_COUNT,
                },
                sources=sources,
                warnings=warnings,
                metadata=metadata,
            )
        r_base = float(base_leg["rate"])
        r_quote = float(quote_leg["rate"])
        tenors = _parse_tenors(params.get("tenors"), default=("1W", "1M", "3M", "6M", "1Y"))
        pip_factor = 100.0 if quote == "JPY" else 10000.0
        rows = []
        for tenor in tenors:
            t = tenor["years"]
            fwd = _forward(spot, r_base, r_quote, t, _FRD_DAY_COUNT)
            # Annualized carry implied by the forward, on the same ACT/360 accrual
            # the forward uses: (F/S - 1) / (T x 365/360) x 100, in percent.
            carry_pct = (fwd / spot - 1.0) / (t * 365.0 / 360.0) * 100.0 if spot else None
            rows.append(
                {
                    "pair": pair,
                    "tenor": tenor["label"],
                    "tenor_years": round(t, 6),
                    "spot": round(spot, 6),
                    "forward": round(fwd, 6),
                    "forward_points": round(fwd - spot, 6),
                    "forward_points_pips": round((fwd - spot) * pip_factor, 4),
                    "implied_carry": round(carry_pct, 6) if carry_pct is not None else None,
                    "base_rate": r_base,
                    "quote_rate": r_quote,
                    "source_mode": source_mode,
                }
            )
        # Headline tenor: the 3M row when requested, else the last one. Every
        # top-level figure below comes from this same row, so they agree.
        headline = rows[2] if len(rows) > 2 else rows[-1]
        data = {
            "pair": pair,
            "base": base,
            "quote": quote,
            "S": round(spot, 6),
            "spot": round(spot, 6),
            "F": headline["forward"],
            "forward_rate": headline["forward"],
            "tenor": headline["tenor"],
            "forward_points": headline["forward_points"],
            "implied_carry": headline["implied_carry"],
            "data_mode": source_mode,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "r_base": r_base,
            "r_quote": r_quote,
            "rate_sources": rate_sources,
            "rate_as_of": rate_as_of,
            "rate_units": "decimal annual",
            "T": headline["tenor_years"],
            "day_count": _FRD_DAY_COUNT,
            "forward_points_unit": (
                "price (quote currency per base); forward_points_pips gives pips "
                "(x10000, x100 for a JPY quote)"
            ),
            "rows": rows,
            "curve": rows,
            "methodology": (
                "Covered interest parity: F = S * (1 + r_quote * T) / (1 + r_base * T). "
                "S is quote currency per base currency. Rates are annual decimals; T is the "
                "tenor year fraction on ACT/360 (house convention for both legs). Each rate "
                "comes from a live FRED series (rate_sources shows fred:<series>) or from the "
                "caller; a leg with neither returns status provider_unavailable and no forward."
            ),
            "field_dictionary": {
                "S": "Spot rate, quote currency per one base currency.",
                "F": "Forward rate for the highlighted/default tenor.",
                "r_base": "Annual policy/overnight reference rate for the base currency.",
                "r_quote": "Annual policy/overnight reference rate for the quote currency.",
                "rate_sources": (
                    "Source of each rate leg: caller_input or fred:<series id>. "
                    "A leg with neither gives provider_unavailable (source 'unavailable')."
                ),
                "T": "Tenor in years.",
                "forward_rate": "Forward for the headline tenor (same value as F).",
                "forward_points": "Forward - spot, in price units (quote currency per base), headline tenor.",
                "forward_points_pips": "(Forward - spot) in pips: x10000, or x100 for a JPY quote.",
                "implied_carry": "Annualized carry implied by the forward, in percent: (F/S - 1) / (T x 365/360) x 100.",
                "tenor": "Headline tenor label (the row behind F).",
                "data_mode": "Spot source mode for this forward (live_yfinance_quote, manual_input, reference_model, ...).",
                "as_of": "UTC time this forward was computed (the spot's own time is in spot_source).",
                "day_count": "Day-count convention applied to both rate legs.",
            },
        }
        return FunctionResult(
            code=self.code,
            instrument=instrument or Instrument(symbol=pair, asset_class=AssetClass.FX),
            data=data,
            sources=sources,
            warnings=warnings,
            metadata=metadata,
        )


# WB1-G11 FRD-only helpers. The shared _rate_for / _pair_from / _forward helpers
# are deliberately left unchanged because FXIP and FXFC use them.
_FRD_DAY_COUNT = "ACT/360"
_FRD_POLICY_LOOKBACK_DAYS = 400
_FRD_FETCH_TIMEOUT_S = 6.0
# Keyless FRED series for each currency's policy / overnight reference rate.
# Values are percent and are converted to decimals. A series with no
# observation inside the lookback window leaves that leg without a rate (FRD#1).
_FRD_POLICY_SERIES: dict[str, str] = {
    "USD": "DFF",  # effective federal funds rate, daily
    "EUR": "ECBDFR",  # ECB deposit facility rate, daily
    "GBP": "IUDSOIA",  # SONIA overnight rate, daily
    "JPY": "IRSTCI01JPM156N",  # call/interbank rate, monthly (OECD via FRED)
    "AUD": "IRSTCI01AUM156N",  # call rate, monthly (OECD via FRED)
    "CAD": "IRSTCI01CAM156N",  # call rate, monthly (OECD via FRED)
    "CHF": "IRSTCI01CHM156N",  # call rate, monthly (last observation 2024-03)
}


def _frd_canonical_params(params: dict[str, Any]) -> dict[str, Any]:
    """Map manifest input names onto the handler's parameter names (FRD#2)."""
    out = dict(params)
    if out.get("r_base") in (None, "") and out.get("r_dom") not in (None, ""):
        out["r_base"] = out["r_dom"]
    if out.get("r_quote") in (None, "") and out.get("r_for") not in (None, ""):
        out["r_quote"] = out["r_for"]
    if out.get("spot") in (None, "") and out.get("spot_override") not in (None, ""):
        out["spot"] = out["spot_override"]
    if out.get("tenors") in (None, "") and out.get("tenor") not in (None, ""):
        out["tenors"] = out["tenor"]
    return out


def _ccy_code(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text if len(text) == 3 and text.isalpha() else None


def _frd_pair(instrument: Instrument | None, params: dict[str, Any]) -> tuple[str, str, str]:
    """Pair precedence: explicit pair, then base+quote inputs, then symbol/instrument."""
    if not params.get("pair"):
        base_ccy = _ccy_code(params.get("base"))
        quote_ccy = _ccy_code(params.get("quote"))
        if base_ccy and quote_ccy and base_ccy != quote_ccy:
            return base_ccy, quote_ccy, base_ccy + quote_ccy
    return _pair_from(instrument, params)


async def _frd_policy_rate(
    fn: BaseFunction, currency: str, explicit: Any, params: dict[str, Any]
) -> dict[str, Any]:
    """Resolve one rate leg: caller input, then live keyless FRED, else no rate.

    Returns ``{"rate", "source", "as_of", "warning"}``. ``rate`` is None whenever
    there is neither a caller input nor a live FRED observation.
    """
    ccy = currency.upper()
    if explicit not in (None, ""):
        try:
            value = float(explicit)
        except (TypeError, ValueError):
            value = math.nan
        if math.isfinite(value):
            return {"rate": value, "source": "caller_input", "as_of": None, "warning": None}
    series_id = _FRD_POLICY_SERIES.get(ccy)
    if series_id and _truthy(params.get("live", True)):
        try:
            frame = await asyncio.wait_for(
                fetch_fred_csv_series(
                    series_id,
                    client=getattr(fn, "_http_client", None),
                    timeout=_FRD_FETCH_TIMEOUT_S,
                    lookback_days=_FRD_POLICY_LOOKBACK_DAYS,
                ),
                timeout=_FRD_FETCH_TIMEOUT_S + 1,
            )
            if frame is not None and not frame.empty:
                value = float(frame["value"].iloc[-1])
                if math.isfinite(value) and -5.0 <= value <= 50.0:
                    return {
                        "rate": value / 100.0,
                        "source": f"fred:{series_id}",
                        "as_of": frame.index[-1].strftime("%Y-%m-%d"),
                        "warning": None,
                    }
        except Exception:  # noqa: BLE001 - any fetch/parse failure means no live rate
            pass
    # DATA POLICY (FRD#1): no live series and no caller input means no rate. The
    # 2024-06 constants in _REFERENCE_RATES are stale and are never used as current
    # rates here; the caller gets provider_unavailable instead of a forward.
    return {
        "rate": None,
        "source": "unavailable",
        "as_of": None,
        "warning": (
            f"{ccy} policy rate unavailable: no live FRED series and no caller-supplied rate "
            f"(the {_REFERENCE_AS_OF} reference constant is not used as a current rate)"
        ),
    }


@FunctionRegistry.register
class OVDVFunction(BaseFunction):
    """OVDV - FX Option Volatility Surface.

    The ATM volatility term structure is anchored to LIVE FX realized
    volatility: for each tenor we compute the annualized standard deviation
    of daily log returns of the pair (yfinance ``<PAIR>=X`` history) over a
    trailing window sized to that tenor, instead of a hardcoded vol constant.
    The 25-delta risk-reversal / butterfly smile is then overlaid as a
    clearly-labelled model perturbation around the real ATM anchor.
    """

    code = "OVDV"
    name = "FX Option Volatility Surface"
    asset_classes = (AssetClass.FX, AssetClass.DERIVATIVE)
    category = "fx"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        base, quote, pair = _pair_from(instrument, params)
        tenors = _parse_tenors(params.get("tenors"), default=("1W", "1M", "3M", "6M", "1Y"))
        deltas = ["10P", "25P", "ATM", "25C", "10C"]

        # --- anchor the ATM curve to live realized vol ------------------
        atm_curve, vol_source, data_mode, rv_source, rv_warning = await _atm_term_structure(
            self, pair, tenors, params
        )
        if atm_curve is None:
            # No usable history and no user ATM: say so explicitly, emit no vols.
            return _vol_unavailable(self, instrument, pair, tenors, rv_warning or "no vol source")

        # Smile: there is no keyless market option-quote source, so the 25d
        # risk reversal / butterfly are shown ONLY when the caller supplies
        # both quotes. Without them the wings are not emitted at all: a
        # model-invented smile must never be presented as implied vol.
        rr_25_override = params.get("risk_reversal_25d", params.get("rr_25d"))
        bf_25_override = params.get("butterfly_25d", params.get("bf_25d"))
        smile_quoted = rr_25_override not in (None, "") and bf_25_override not in (None, "")
        smile_deltas = deltas if smile_quoted else ["ATM"]
        rr_25 = float(rr_25_override) if smile_quoted else None
        bf_25 = float(bf_25_override) if smile_quoted else None

        surface = []
        series = []
        atm_1m: float | None = None
        wing_floor_cells: list[str] = []
        for i, tenor in enumerate(tenors):
            label = tenor["label"]
            term = atm_curve[i]
            for delta in smile_deltas:
                wing = 0.0
                if smile_quoted and rr_25 is not None and bf_25 is not None:
                    wing = {
                        "10P": bf_25 + 0.5 * abs(rr_25) - rr_25 / 2,
                        "25P": bf_25 - rr_25 / 2,
                        "ATM": 0.0,
                        "25C": bf_25 + rr_25 / 2,
                        "10C": bf_25 + 0.5 * abs(rr_25) + rr_25 / 2,
                    }.get(delta, 0.0)
                if term + wing < 0.0001:
                    # The quoted wing pushes this cell to or below the vol floor.
                    wing_floor_cells.append(f"{label} {delta}")
                vol = max(0.0001, term + wing)
                surface.append(
                    {
                        "pair": pair,
                        "tenor": label,
                        "tenor_years": round(tenor["years"], 6),
                        "delta": delta,
                        "vol": round(vol * 100, 4),
                        "vol_decimal": round(vol, 6),
                        "source_mode": vol_source,
                    }
                )
            series.append({"tenor": label, "atm_vol_pct": round(term * 100, 4)})
            if label.upper() in {"1M", "30D"}:
                atm_1m = term

        if atm_1m is None and atm_curve:
            atm_1m = atm_curve[min(1, len(atm_curve) - 1)]

        # Headline RR/BF echo the caller's quotes; None when not quoted.
        head_term = atm_1m if atm_1m is not None else (atm_curve[0] if atm_curve else 0.0)
        head_rr = rr_25
        head_bf = bf_25

        as_of = datetime.now(timezone.utc).isoformat()
        warnings: list[str] = []
        if rv_warning:
            warnings.append(rv_warning)
        if wing_floor_cells:
            # OVDV#2 residual: the 0.01 vol floor hides a quoted wing that is
            # non-positive, so the surface 25C-25P no longer equals the headline RR.
            warnings.append(
                f"quoted risk reversal/butterfly push {', '.join(wing_floor_cells)} to or below the "
                "0.01 vol floor; those surface cells show the floor value, so the surface 25C minus 25P "
                "does not equal the headline risk_reversal_25d_pct"
            )
        if vol_source == "live_realized_vol":
            # OVDV#5: a managed or pegged leg makes realized vol a managed-rate statistic.
            managed_legs = [c for c in (base, quote) if c.upper() in _OVDV_MANAGED_CCYS]
            if managed_legs:
                warnings.append(
                    f"{pair} involves managed or pegged currency {', '.join(managed_legs)}: its realized "
                    "vol reflects a managed rate path, not an option-market level"
                )

        data = {
            "pair": pair,
            "base": base,
            "quote": quote,
            "as_of": as_of,
            "data_mode": data_mode,
            "vol_source": vol_source,
            "surface": surface,
            "rows": surface,
            "series": series,
            "tenors": [t["label"] for t in tenors],
            "deltas": smile_deltas,
            "atm_vol_pct": round(head_term * 100, 4),
            "atm_1m_vol_pct": round((atm_1m or 0.0) * 100, 4),
            "smile_source": "user_quotes" if smile_quoted else "not_quoted",
            "risk_reversal_25d_pct": round(head_rr * 100, 4) if head_rr is not None else None,
            "butterfly_25d_pct": round(head_bf * 100, 4) if head_bf is not None else None,
            "cards": {
                "pair": pair,
                "atm_vol_pct": round(head_term * 100, 4),
                "risk_reversal_25d_pct": round(head_rr * 100, 4) if head_rr is not None else None,
                "butterfly_25d_pct": round(head_bf * 100, 4) if head_bf is not None else None,
                "vol_source": vol_source,
                "data_mode": data_mode,
                "as_of": as_of,
            },
            "methodology": (
                "OVDV anchors each tenor's ATM value to live FX realized volatility: the "
                "annualized standard deviation (x sqrt(252)) of daily log returns of the pair "
                "from yfinance over a trailing window sized to that tenor (1W=5d ... 1Y=252d). "
                "These are REALIZED vols, not option-implied vols. No keyless market option-quote "
                "source is wired, so the 25-delta risk reversal and butterfly are not modelled: "
                "they are null unless the caller supplies both risk_reversal_25d and butterfly_25d, "
                "in which case the wings are built from those user quotes (25P = BF - RR/2, "
                "25C = BF + RR/2, 10P/10C add wing curvature) and smile_source is user_quotes. "
                "An explicit atm_vol input gives a flat user-quoted ATM curve. If yfinance history "
                "is unavailable no surface is produced: status is provider_unavailable with a "
                "reason, and no reference or constant vol is substituted."
            ),
            "field_dictionary": {
                "tenor": "Option expiry bucket.",
                "delta": "ATM only unless both 25d quotes are supplied; then 10P/25P/ATM/25C/10C.",
                "vol": "Percent vol: realized (live_realized_vol) or user-quoted (user_inputs).",
                "vol_decimal": "Same volatility as annual decimal.",
                "atm_vol_pct": "ATM (1M-anchor) annualized vol, in percent; realized unless user-quoted.",
                "risk_reversal_25d_pct": "25D call vol minus 25D put vol, in percent; null unless user-quoted.",
                "butterfly_25d_pct": "25D butterfly, in percent; null unless user-quoted.",
                "smile_source": "user_quotes when both 25d quotes were supplied, otherwise not_quoted.",
                "vol_source": "live_realized_vol (yfinance realized vol) or user_inputs. With neither, status is provider_unavailable and no vols are emitted.",
                "data_mode": "delayed_reference when anchored to yfinance realized vol; modeled for a user-quoted ATM.",
            },
            "next_actions": [
                "Supply atm_vol together with risk_reversal_25d and butterfly_25d to overlay a desk-quoted smile.",
                "Switch the pair to inspect another currency's realized-vol term structure.",
            ],
        }
        sources: list[str] = []
        if rv_source:
            sources.append(rv_source)
        elif vol_source == "user_inputs":
            sources.append("user_inputs")
        if smile_quoted:
            sources.append("user_inputs_fx_smile")
        return FunctionResult(
            code=self.code,
            instrument=instrument or Instrument(symbol=pair, asset_class=AssetClass.FX),
            data=data,
            sources=_unique(sources),
            warnings=warnings,
        )


def _rate_input_error(params: dict[str, Any]) -> str | None:
    """XCON-6: refuse a percent-scale explicit rate (3.5 for 3.5 %) on any FX pane."""
    return decimal_rate_error("r_base", params.get("r_base")) or decimal_rate_error(
        "r_quote", params.get("r_quote")
    )


def _rate_error_result(
    code: str,
    instrument: Instrument | None,
    pair: str,
    base: str,
    quote: str,
    reason: str,
    day_count: str | None = None,
) -> FunctionResult:
    """Explicit input_error state: no spot fetch, no forward, no fabricated level."""
    data: dict[str, Any] = {
        "status": "input_error",
        "reason": reason,
        "pair": pair,
        "base": base,
        "quote": quote,
        "rows": [],
        "curve": [],
        "forecast": [],
        "forward_points": None,
        "forecast_value": None,
        "one_month_forward": None,
        "three_month_forward": None,
        "carry_annualized": None,
        "next_actions": ["Enter r_base and r_quote as decimal annual rates (3.5 % = 0.035)."],
    }
    if day_count is not None:
        data["day_count"] = day_count
    return FunctionResult(
        code=code,
        instrument=instrument or Instrument(symbol=pair, asset_class=AssetClass.FX),
        data=data,
        sources=["covered_interest_parity_formula"],
        warnings=[reason],
        metadata={"data_mode": "explicit_unavailable"},
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _pair_from(instrument: Instrument | None, params: dict[str, Any]) -> tuple[str, str, str]:
    raw = (
        params.get("pair")
        or params.get("symbol")
        or (instrument.symbol if instrument else None)
        or "EURUSD"
    )
    pair = _normalize_pair(str(raw))
    return pair[:3], pair[3:6], pair


def _normalize_pair(raw: str) -> str:
    value = raw.upper().strip().replace("/", "").replace("-", "").replace(" ", "")
    value = value.replace("=X", "")
    if len(value) >= 6 and value[:3].isalpha() and value[3:6].isalpha():
        return value[:6]
    return "EURUSD"


def _rate_for(currency: str, explicit: Any = None) -> float:
    if explicit not in (None, ""):
        try:
            return float(explicit)
        except Exception:
            pass
    return float(_REFERENCE_RATES.get(currency.upper(), 0.04))


def _fxip_rate(currency: str, explicit: Any = None) -> tuple[float | None, str]:
    """FXIP policy rate plus its provenance (FXIP#2).

    A caller-supplied rate is ``user_input``. Otherwise the value is the dated
    2024-06 reference constant, and the source label carries that vintage so
    the pane never presents it as a current policy rate. A currency missing
    from the reference table returns ``(None, "unavailable_no_reference_rate")``
    rather than an invented value. Kept separate from the shared ``_rate_for``
    so other FX functions keep their behaviour.
    """
    if explicit not in (None, ""):
        try:
            return float(explicit), "user_input"
        except Exception:
            pass
    key = currency.upper()
    if key not in _REFERENCE_RATES:
        return None, "unavailable_no_reference_rate"
    return float(_REFERENCE_RATES[key]), f"reference_policy_rate_{_REFERENCE_AS_OF}"


async def _resolve_spot(
    fn: BaseFunction,
    pair: str,
    params: dict[str, Any],
    quote_info: dict[str, Any] | None = None,
) -> tuple[float, str, str]:
    """Spot resolver shared by the FX functions.

    ``quote_info`` is an optional output dict. When the yfinance quote is used,
    it receives the quote's ``timestamp`` and ``timestamp_source`` so a caller
    can tell an upstream quote time from a fetch time. Other callers pass
    nothing and behave exactly as before.
    """
    if params.get("spot") not in (None, ""):
        return float(params["spot"]), "manual_input", "manual_input"
    instrument = Instrument(symbol=pair, asset_class=AssetClass.FX)
    timeout = float(params.get("quote_timeout", params.get("timeout", 4)))
    if _truthy(params.get("live", True)) and fn.deps.yfinance:
        try:
            quote = await asyncio.wait_for(
                fn.deps.yfinance.fetch(
                    DataRequest(
                        kind=DataKind.QUOTE,
                        instrument=instrument,
                        extra={"timeout": timeout},
                    )
                ),
                timeout=timeout + 1,
            )
            last = getattr(quote, "last", None)
            if last:
                if quote_info is not None:
                    quote_info["timestamp"] = getattr(quote, "timestamp", None)
                    quote_info["timestamp_source"] = getattr(quote, "timestamp_source", None)
                return float(last), "yfinance", "live_yfinance_quote"
        except Exception:
            pass
    if _truthy(params.get("live_fx") or params.get("live")) and fn.deps.ecb:
        try:
            df = await asyncio.wait_for(
                fn.deps.ecb.fx_pair(pair[:3], pair[3:6]),
                timeout=timeout + 1,
            )
            if getattr(df, "empty", True) is False:
                return float(df["value"].iloc[-1]), "ecb", "live_ecb_reference"
        except Exception:
            pass
    # H-4 de-staling (2026-09-09): keyless ECB-published reference rates
    # (Frankfurter) bridge the gap between the keyed providers above and
    # the stamped 2024-06 reference spots below. Any failure keeps the
    # honest labelled reference fallback untouched.
    # R3 L-4: same gate expression as the cross-matrix tier — `live=false`
    # turns the tier off, `live_fx=true` alone opts in, default on.
    if _truthy(params.get("live_fx") or params.get("live", True)):
        rate = await fetch_frankfurter_rate(
            pair[:3], pair[3:6], client=getattr(fn, "_http_client", None)
        )
        if rate is not None:
            return float(rate), "frankfurter_ecb", "live_official"
    return _template_spot(pair), "reference_fx_spot", "reference_model"


async def _atm_term_structure(
    fn: BaseFunction,
    pair: str,
    tenors: list[dict[str, Any]],
    params: dict[str, Any],
) -> tuple[list[float] | None, str, str, str | None, str | None]:
    """Build a per-tenor ATM-vol curve anchored to live FX realized vol.

    Returns ``(atm_curve, vol_source, data_mode, rv_source, warning)`` where
    ``atm_curve`` is one annualized-vol decimal per requested tenor, or ``None``
    when no vol can be sourced honestly (the caller reports provider_unavailable).

    Order of precedence:
      1. explicit ``atm_vol`` input (flat curve, user-quoted) — labelled input.
      2. live realized vol from yfinance daily history (the real anchor).
      3. none: no reference or constant vol is ever substituted.
    """
    explicit_atm = params.get("atm_vol", params.get("vol"))
    if explicit_atm not in (None, ""):
        atm = float(explicit_atm)
        # The user quoted one ATM level: report it flat across tenors. The
        # former invented +0.15vp-per-tenor slope was not a quote.
        curve = [max(0.0001, atm) for _ in tenors]
        return curve, "user_inputs", "modeled", None, None

    closes = await _close_series(fn, pair, params)
    returns = _log_returns(closes)
    if len(returns) >= 4:
        curve: list[float] = []
        window_notes: list[str] = []
        for tenor in tenors:
            window = _TENOR_WINDOW_DAYS.get(tenor["label"].upper())
            if window is None:
                window = max(5, min(252, int(round(tenor["years"] * 252))))
            win = returns[-window:] if len(returns) >= window else returns
            if len(win) < window:
                # OVDV#4: history shorter than the tenor window. The value is still
                # live realized vol, but over fewer days than its label implies.
                window_notes.append(
                    f"{tenor['label']} realized vol uses {len(win)} of the {window} daily returns "
                    "requested (history too short for that window)"
                )
            if len(win) < _OVDV_MIN_RELIABLE_RETURNS:
                # OVDV#5: e.g. 1W rests on 5 returns, which is a noisy estimate.
                window_notes.append(
                    f"{tenor['label']} realized vol rests on only {len(win)} daily returns; "
                    "the estimate is statistically weak"
                )
            atm = _annualized_vol(win)
            if atm is None or atm <= 0:
                # Never swap a single tenor for a constant: the whole curve is unavailable.
                return (
                    None,
                    "none",
                    "provider_unavailable",
                    None,
                    f"realized vol could not be computed for tenor {tenor['label']} from yfinance history; "
                    "no reference vol is substituted",
                )
            curve.append(atm)
        return curve, "live_realized_vol", "delayed_reference", "yfinance", ("; ".join(window_notes) or None)

    return (
        None,
        "none",
        "provider_unavailable",
        None,
        "live realized-vol history unavailable (yfinance returned no usable daily closes); "
        "no reference vol is substituted",
    )


def _vol_unavailable(
    fn: BaseFunction,
    instrument: Instrument | None,
    pair: str,
    tenors: list[dict[str, Any]],
    reason: str,
) -> FunctionResult:
    """Explicit honest state: no surface, no vols, the reason and next steps."""
    as_of = datetime.now(timezone.utc).isoformat()
    data = {
        "status": "provider_unavailable",
        "reason": reason,
        "next_actions": [
            "Retry when yfinance FX daily history is reachable.",
            "Supply atm_vol (decimal, e.g. 0.085) to view a user-quoted flat ATM curve.",
        ],
        "pair": pair,
        "as_of": as_of,
        "data_mode": "provider_unavailable",
        "vol_source": "none",
        "surface": [],
        "rows": [],
        "series": [],
        "tenors": [t["label"] for t in tenors],
        "deltas": [],
        "atm_vol_pct": None,
        "atm_1m_vol_pct": None,
        "smile_source": "not_quoted",
        "risk_reversal_25d_pct": None,
        "butterfly_25d_pct": None,
        "cards": {
            "pair": pair,
            "atm_vol_pct": None,
            "risk_reversal_25d_pct": None,
            "butterfly_25d_pct": None,
            "vol_source": "none",
            "data_mode": "provider_unavailable",
            "as_of": as_of,
        },
    }
    return FunctionResult(
        code=fn.code,
        instrument=instrument or Instrument(symbol=pair, asset_class=AssetClass.FX),
        data=data,
        sources=[],
        warnings=[reason],
    )


async def _close_series(fn: BaseFunction, pair: str, params: dict[str, Any]) -> list[float]:
    """Fetch >=1Y of daily closes for ``<PAIR>`` via the yfinance adapter."""
    if not getattr(fn, "deps", None) or not fn.deps.yfinance:
        return []
    days = int(float(params.get("history_days", 400)))
    start = datetime.now(timezone.utc) - timedelta(days=max(40, days))
    inst = Instrument(symbol=pair, asset_class=AssetClass.FX)
    timeout = float(params.get("yfinance_timeout", params.get("timeout", 6)))
    try:
        df = await asyncio.wait_for(
            fn.deps.yfinance.fetch(
                DataRequest(
                    kind=DataKind.OHLCV,
                    instrument=inst,
                    start=start,
                    interval="1d",
                    extra={"timeout": timeout},
                )
            ),
            timeout=timeout + 1,
        )
    except Exception:
        return []
    if df is None or getattr(df, "empty", True):
        return []
    closes: list[float] = []
    try:
        col = None
        for candidate in ("Close", "close", "Adj Close", "adj_close"):
            if candidate in df.columns:
                col = candidate
                break
        if col is None:
            return []
        for value in df[col].tolist():
            num = _num(value)
            if num is not None and num > 0:
                closes.append(num)
    except Exception:
        return []
    return closes


def _log_returns(closes: list[float]) -> list[float]:
    rets: list[float] = []
    for prev, cur in zip(closes, closes[1:]):
        if prev > 0 and cur > 0:
            rets.append(math.log(cur / prev))
    return rets


def _annualized_vol(returns: list[float]) -> float | None:
    n = len(returns)
    if n < 2:
        return None
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / n  # population stdev
    return math.sqrt(var) * _FX_ANNUALIZATION


async def _history_rows(fn: BaseFunction, pair: str, params: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    days = int(float(params.get("days", 90)))
    start = datetime.now(timezone.utc) - timedelta(days=max(5, days))
    inst = Instrument(symbol=pair, asset_class=AssetClass.FX)
    timeout = float(params.get("yfinance_timeout", params.get("timeout", 4)))
    extra: dict[str, Any] = {"timeout": timeout}
    # Optional deep-history gate: WCRS passes deep_history=False so its
    # bounded 14-day legs do not trigger the wrapper's 60-year depth race.
    if params.get("deep_history") is not None:
        extra["deep_history"] = params["deep_history"]
    if fn.deps.yfinance:
        try:
            df = await asyncio.wait_for(
                fn.deps.yfinance.fetch(
                    DataRequest(
                        kind=DataKind.OHLCV,
                        instrument=inst,
                        start=start,
                        interval="1d",
                        limit=days,
                        extra=extra,
                    )
                ),
                timeout=timeout + 1,
            )
            rows = _frame_rows(df, limit=days)
            if rows:
                return rows, "yfinance"
        except Exception:
            pass
    if fn.deps.ecb:
        try:
            df = await asyncio.wait_for(
                fn.deps.ecb.fx_pair(pair[:3], pair[3:6], start=start.strftime("%Y-%m-%d")),
                timeout=timeout + 1,
            )
            rows = []
            for idx, row in df.tail(days).iterrows():
                close = float(row.get("value"))
                rows.append(
                    {
                        "date": idx.date().isoformat() if hasattr(idx, "date") else str(idx),
                        "open": close,
                        "high": close,
                        "low": close,
                        "close": close,
                        "volume": 0,
                    }
                )
            if rows:
                return rows, "ecb"
        except Exception:
            pass
    return [], None


def _frame_rows(frame: Any, limit: int = 90) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    rows = []
    for idx, row in frame.tail(limit).iterrows():
        close = _num(row.get("Close", row.get("close")))
        if close is None:
            continue
        rows.append(
            {
                "date": idx.date().isoformat() if hasattr(idx, "date") else str(idx),
                "open": _num(row.get("Open", row.get("open"))) or close,
                "high": _num(row.get("High", row.get("high"))) or close,
                "low": _num(row.get("Low", row.get("low"))) or close,
                "close": close,
                "volume": _num(row.get("Volume", row.get("volume"))) or 0,
            }
        )
    return rows


def _daily_change(history: list[dict[str, Any]]) -> float | None:
    """HNT-09 fix (WCRS pattern): no usable history → None, never the old
    placeholder 0.0 that read as "the rate did not move"."""
    if len(history) < 2:
        return None
    prev = _num(history[-2].get("close"))
    last = _num(history[-1].get("close"))
    if not prev or last is None:
        return None
    return round((last / prev - 1.0) * 100.0, 4)


def _history_close_map(rows: list[dict[str, Any]]) -> dict[str, float]:
    """{date: close} from ``_history_rows`` points; unusable closes skipped."""
    series: dict[str, float] = {}
    for point in rows or []:
        date = str(point.get("date") or "")[:10]
        close = _num(point.get("close"))
        if date and close is not None and close > 0:
            series[date] = close
    return series


async def _usd_history_legs(
    fn: BaseFunction,
    currencies: list[str],
    params: dict[str, Any],
    *,
    budget: float,
) -> tuple[dict[str, dict[str, float]], dict[str, str]]:
    """Daily close legs for every non-USD currency via ``_history_rows``.

    Each leg is the source's ``USD{ccy}`` daily close (quote currency per
    USD). A single fetch per currency covers the whole matrix because any
    cross is the ratio of two USD legs, so the pane never fires one history
    request per pair. Currencies whose history is unavailable are simply
    absent — callers must render null, never 0.0.
    """
    unique = [c for c in _unique(currencies) if len(c) == 3 and c != "USD"]
    try:
        days = max(7, min(30, int(float(params.get("days", 14)))))
    except Exception:
        days = 14
    local_params = {**params, "days": days, "deep_history": False}
    tasks = {
        ccy: asyncio.create_task(_history_rows(fn, f"USD{ccy}", local_params))
        for ccy in unique
    }
    legs: dict[str, dict[str, float]] = {}
    sources: dict[str, str] = {}
    if tasks:
        done, pending = await asyncio.wait(tasks.values(), timeout=max(0.5, budget))
        for task in pending:
            task.cancel()
        for ccy, task in tasks.items():
            if task not in done or task.cancelled():
                continue
            try:
                rows, source = task.result()
            except Exception:  # noqa: BLE001 — missing leg degrades to null
                continue
            series = _history_close_map(rows)
            if len(series) >= 2:
                legs[ccy] = series
                if source:
                    sources[ccy] = source
    return legs, sources


def _cross_history_points(
    base: str,
    quote: str,
    legs: dict[str, dict[str, float]],
    *,
    limit: int = 14,
) -> list[dict[str, Any]]:
    """Derived daily cross closes: quote-per-base = leg(quote) / leg(base).

    ``USD`` is the implicit constant-1.0 leg. Returns ``[]`` when either leg
    is unavailable or the two series share fewer than two dates — callers
    must leave the change null rather than inventing a value.
    """
    base_leg = None if base == "USD" else legs.get(base)
    quote_leg = None if quote == "USD" else legs.get(quote)
    if base != "USD" and base_leg is None:
        return []
    if quote != "USD" and quote_leg is None:
        return []
    if base_leg is None and quote_leg is None:
        return []
    dates = set(base_leg) if base_leg is not None else set(quote_leg)
    if base_leg is not None and quote_leg is not None:
        dates &= set(quote_leg)
    if len(dates) < 2:
        return []
    points: list[dict[str, Any]] = []
    for date in sorted(dates)[-limit:]:
        base_value = 1.0 if base_leg is None else base_leg[date]
        quote_value = 1.0 if quote_leg is None else quote_leg[date]
        if base_value <= 0:
            continue
        close = quote_value / base_value
        if math.isfinite(close) and close > 0:
            points.append({"date": date, "close": round(close, 8)})
    return points


def _forward(spot: float, r_base: float, r_quote: float, years: float,
             day_count: str = "ACT/360") -> float:
    """Covered-interest-parity FX forward, supporting ACT/360 convention.

    D03-2026-05-24 (H22): OTC FX desks quote forwards with rates on
    ACT/360 day-count (USD, EUR, GBP all ACT/360 — JPY ACT/365 is the
    notable exception, but our cross-currency uses base/quote ACT/360 by
    convention). The ``years`` parameter is the calendar-year fraction;
    we convert to the rate's day-count internally.

    F = S * (1 + r_quote * τ_quote) / (1 + r_base * τ_base)

    where τ = (calendar_days/360) for ACT/360. Equivalent shortcut:
    τ_rate = years * (365/360) for ACT/360 vs ACT/365 conversion.
    """
    if day_count.upper() == "ACT/360":
        # Convert calendar year-fraction (365-day basis) to rate basis.
        years_rate = years * 365.0 / 360.0
    else:
        years_rate = years
    return spot * (1 + r_quote * years_rate) / (1 + r_base * years_rate)


def _parse_tenors(value: Any, default: tuple[str, ...]) -> list[dict[str, Any]]:
    raw_items: list[Any]
    if isinstance(value, str) and value.strip():
        raw_items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple)):
        raw_items = list(value)
    else:
        raw_items = list(default)
    out = []
    for item in raw_items:
        label = str(item).strip().upper()
        years = _tenor_to_years(label)
        if years > 0:
            out.append({"label": label, "years": years})
    return out or [{"label": "3M", "years": 0.25}]


def _tenor_to_years(label: str) -> float:
    try:
        if label.endswith("D"):
            return max(1.0, float(label[:-1])) / 365.0
        if label.endswith("W"):
            return max(1.0, float(label[:-1])) * 7.0 / 365.0
        if label.endswith("M"):
            return max(1.0, float(label[:-1])) / 12.0
        if label.endswith("Y"):
            return max(1.0, float(label[:-1]))
        return max(0.0, float(label))
    except Exception:
        return 0.0


def _wcrs_fx_live(params: dict[str, Any]) -> bool:
    """WCRS live-FX gate: an explicit ``live_fx`` (true or false) wins.

    Only when ``live_fx`` is absent does the generic ``live`` flag (default
    on) decide. The old ``_truthy(params.get("live_fx") or params.get("live",
    True))`` turned an explicit ``live_fx=false`` into True, so the opt-out
    was silently ignored.
    """
    raw = params.get("live_fx")
    if raw is None or raw == "":
        raw = params.get("live", True)
    return _truthy(raw)


async def _cross_matrix(
    fn: BaseFunction,
    bases: list[str],
    quotes: list[str],
    params: dict[str, Any],
) -> tuple[dict[str, dict[str, float]], str, list[str], str | None]:
    """Returns ``(matrix, source_mode, sources, as_of)``; ``as_of`` is the date
    the rates belong to (None when the provider gives no timestamp)."""
    if _truthy(params.get("live", True)) and _wcrs_fx_live(params) and fn.deps.exchangerate_host:
        timeout = float(params.get("timeout", 4))

        async def fetch_base(base: str) -> tuple[str, dict[str, float] | None]:
            try:
                rates = await asyncio.wait_for(
                    fn.deps.exchangerate_host.latest(base, quotes),
                    timeout=timeout,
                )
                if rates:
                    row = {q: float(rates.get(q, 1.0 if q == base else 0.0) or 0.0) for q in quotes}
                    row[base] = 1.0
                    return base, row
            except Exception:
                return base, None
            return base, None

        results = await asyncio.gather(*(fetch_base(base) for base in bases))
        live_rows = {base: row for base, row in results if row}
        if len(live_rows) == len(bases):
            return live_rows, "live_exchangerate_host", ["exchangerate_host"], None
    # H-4 de-staling (2026-09-09): keyless ECB reference rates (Frankfurter)
    # bridge the gap between the keyed exchangerate.host tier and the
    # stamped reference matrix. All-or-nothing across bases AND quotes — a
    # currency Frankfurter does not carry disables the tier, so no cell can
    # mix live and seeded levels under a live label.
    # Gate: _wcrs_fx_live. An explicit `live_fx` (true or false) wins; with
    # `live_fx` absent the generic `live` flag (default on) decides. The spot
    # tier in _resolve_spot still uses the older expression and is owned by
    # another group.
    if _wcrs_fx_live(params):
        timeout = float(params.get("timeout", 4))

        async def fetch_base_frankfurter(
            base: str,
        ) -> tuple[str, dict[str, float] | None, str | None]:
            try:
                rates, as_of = await asyncio.wait_for(
                    fetch_frankfurter_rates_dated(
                        base,
                        quotes,
                        timeout=timeout,
                        client=getattr(fn, "_http_client", None),
                    ),
                    timeout=timeout + 1,
                )
            except Exception:
                return base, None, None
            if not rates:
                return base, None, None
            if any(q != base and q not in rates for q in quotes):
                return base, None, None  # partial coverage is not live coverage
            row = {q: float(rates[q]) for q in quotes if q != base}
            row[base] = 1.0
            return base, row, as_of

        results = await asyncio.gather(*(fetch_base_frankfurter(base) for base in bases))
        live_rows = {base: row for base, row, _ in results if row}
        if len(live_rows) == len(bases):
            # One ECB fix per day: the legs should share a date. If they ever
            # differ, report the oldest so the label never overstates freshness.
            fix_dates = sorted({as_of for _, _, as_of in results if as_of})
            fix_date = fix_dates[0] if fix_dates else None
            # Not "live_": a daily ECB fix is delayed, not a live quote.
            return live_rows, "official_daily_fix", ["frankfurter_ecb"], fix_date
    seed = {ccy: _seed_usd_value(ccy) for ccy in _unique([*bases, *quotes])}
    matrix = {
        base: {
            quote: (seed[base] / seed[quote] if seed.get(base) and seed.get(quote) else 0.0)
            for quote in quotes
        }
        for base in bases
    }
    return matrix, "reference_cross_rate_matrix", ["reference_cross_rate_matrix"], _REFERENCE_AS_OF


def _seed_usd_value(currency: str) -> float:
    values = {
        "USD": 1.0,
        "EUR": 1.0835,
        "GBP": 1.256,
        "JPY": 1 / 154.2,
        "TRY": 1 / 32.2,
        "CHF": 1 / 0.913,
        "AUD": 0.662,
        "CAD": 1 / 1.368,
        "NZD": 0.61,
    }
    return float(values.get(currency.upper(), 1.0))


def _currency_list(value: Any, default: list[str]) -> list[str]:
    if isinstance(value, str) and value.strip():
        items = [item.strip().upper() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple)):
        items = [str(item).strip().upper() for item in value if str(item).strip()]
    else:
        items = list(default)
    return [item for item in _unique(items) if len(item) == 3] or list(default)


def _template_spot(pair: str) -> float:
    normalized = _normalize_pair(pair)
    if normalized in _REFERENCE_SPOTS:
        return _REFERENCE_SPOTS[normalized]
    base_usd = _seed_usd_value(normalized[:3])
    quote_usd = _seed_usd_value(normalized[3:6])
    return base_usd / quote_usd if base_usd and quote_usd else 1.0


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _unique(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()
        if not value or value in seen:
            continue
        out.append(value)
        seen.add(value)
    return out
