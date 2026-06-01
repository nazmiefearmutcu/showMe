"""FXFC, FXIP, WCRS, FRD, OVDV - FX function suite."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


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


@FunctionRegistry.register
class FXFCFunction(BaseFunction):
    """FXFC - FX forecasts from forward carry plus volatility bands."""

    code = "FXFC"
    name = "FX Forecasts"
    asset_classes = (AssetClass.FX,)
    category = "fx"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        base, quote, pair = _pair_from(instrument, params)
        spot, spot_source, source_mode = await _resolve_spot(self, pair, params)
        r_base = _rate_for(base, params.get("r_base"))
        r_quote = _rate_for(quote, params.get("r_quote"))
        vol = float(params.get("vol_annualized", params.get("vol", 0.085)))
        tenors = _parse_tenors(params.get("tenors"), default=("1M", "3M", "6M", "12M"))
        rows = []
        for tenor in tenors:
            t = tenor["years"]
            forward = _forward(spot, r_base, r_quote, t)
            band = spot * vol * (t ** 0.5)
            confidence = max(35.0, min(92.0, 78.0 - t * 9.0))
            rows.append(
                {
                    "pair": pair,
                    "horizon": tenor["label"],
                    "tenor_years": round(t, 6),
                    "spot": round(spot, 6),
                    "forecast": round(forward, 6),
                    "lower_band": round(forward - band, 6),
                    "upper_band": round(forward + band, 6),
                    "forward_points": round(forward - spot, 6),
                    "confidence": round(confidence, 2),
                    "source_mode": source_mode,
                }
            )
        data = {
            "pair": pair,
            "base": base,
            "quote": quote,
            "spot": round(spot, 6),
            "base_rate": r_base,
            "quote_rate": r_quote,
            "vol_annualized": vol,
            "forecast": rows,
            "curve": rows,
            "methodology": (
                "FXFC uses covered-interest-parity forward carry as the deterministic forecast path. "
                "Forecast = spot * (1 + quote_rate * T) / (1 + base_rate * T). "
                "Bands are spot * annualized_vol * sqrt(T), so they are model bands, not vendor analyst forecasts."
            ),
            "field_dictionary": {
                "spot": "Quote currency units per one base currency unit.",
                "forecast": "Covered-interest-parity forward-implied level for the tenor.",
                "forward_points": "forecast - spot in quote currency units.",
                "lower_band": "Model lower band using spot * vol * sqrt(T).",
                "upper_band": "Model upper band using spot * vol * sqrt(T).",
                "confidence": "Deterministic model confidence score; lower for longer tenors.",
                "source_mode": "live_yfinance_quote when a fresh quote was fetched; reference_model otherwise.",
            },
        }
        return FunctionResult(
            code=self.code,
            instrument=instrument or Instrument(symbol=pair, asset_class=AssetClass.FX),
            data=data,
            sources=[spot_source, "covered_interest_parity_formula"],
            # Only warn when the spot came from the static reference template
            # — manual_input and any live_* source mode are real values.
            warnings=[] if source_mode != "reference_model" else ["live spot unavailable; using labelled reference spot"],
        )


@FunctionRegistry.register
class FXIPFunction(BaseFunction):
    """FXIP - FX Information Portal."""

    code = "FXIP"
    name = "FX Information Portal"
    asset_classes = (AssetClass.FX,)
    category = "fx"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        base, quote, pair = _pair_from(instrument, params)
        spot, spot_source, source_mode = await _resolve_spot(self, pair, params)
        r_base = _rate_for(base, params.get("r_base"))
        r_quote = _rate_for(quote, params.get("r_quote"))
        atm_vol = float(params.get("atm_vol", params.get("vol", 0.0845)))
        rows = [
            {"metric": "spot", "value": round(spot, 6), "unit": f"{quote} per {base}", "source": spot_source},
            {"metric": "base_rate", "value": r_base, "unit": "decimal annual", "source": "reference_policy_rate"},
            {"metric": "quote_rate", "value": r_quote, "unit": "decimal annual", "source": "reference_policy_rate"},
            {"metric": "1m_forward", "value": round(_forward(spot, r_base, r_quote, 1 / 12), 6), "unit": "rate", "source": "covered_interest_parity"},
            {"metric": "3m_forward", "value": round(_forward(spot, r_base, r_quote, 0.25), 6), "unit": "rate", "source": "covered_interest_parity"},
            {"metric": "atm_vol_1m_pct", "value": round(atm_vol * 100, 3), "unit": "percent", "source": "reference_vol_assumption"},
            {"metric": "carry_annualized", "value": round(r_quote - r_base, 6), "unit": "decimal annual", "source": "rate_differential"},
        ]
        history, history_source = await _history_rows(self, pair, params)
        data = {
            "pair": pair,
            "base": base,
            "quote": quote,
            "spot": round(spot, 6),
            "daily_change_pct": _daily_change(history),
            "one_month_forward": round(_forward(spot, r_base, r_quote, 1 / 12), 6),
            "three_month_forward": round(_forward(spot, r_base, r_quote, 0.25), 6),
            "implied_vol_atm_1m": round(atm_vol * 100, 3),
            "carry_annualized": round(r_quote - r_base, 6),
            "source_mode": source_mode,
            "rows": rows,
            "history": history,
            "methodology": (
                "FXIP combines a spot quote, reference policy-rate assumptions, forward levels from covered interest parity, "
                "and an optional Yahoo/ECB price history. IV is an explicit ATM volatility assumption unless a vendor is configured."
            ),
            "field_dictionary": {
                "daily_change_pct": "Last history close change versus previous close, in percent.",
                "one_month_forward": "1M covered-interest-parity forward.",
                "three_month_forward": "3M covered-interest-parity forward.",
                "implied_vol_atm_1m": "ATM volatility assumption for 1M, in percent.",
                "carry_annualized": "quote_rate - base_rate.",
            },
        }
        sources = [spot_source, "covered_interest_parity_formula", "reference_policy_rate"]
        if history_source:
            sources.append(history_source)
        return FunctionResult(
            code=self.code,
            instrument=instrument or Instrument(symbol=pair, asset_class=AssetClass.FX),
            data=data,
            sources=_unique(sources),
            # manual_input + any live_* counts as a real spot; warn only for
            # the static reference_model fallback.
            warnings=[] if source_mode != "reference_model" else ["live spot unavailable; using labelled reference spot"],
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
        matrix, source_mode, sources = await _cross_matrix(self, bases, quotes, params)
        rows = []
        heatmap = []
        for base in bases:
            for quote in quotes:
                rate = float(matrix.get(base, {}).get(quote, 1.0 if base == quote else 0.0) or 0.0)
                heatmap.append({"base": base, "quote": quote, "pair": f"{base}{quote}", "rate": rate})
                if base == quote or rate <= 0:
                    continue
                pip_factor = 100 if quote == "JPY" else 10000
                bid = rate * 0.9999
                ask = rate * 1.0001
                rows.append(
                    {
                        "base": base,
                        "quote": quote,
                        "pair": f"{base}{quote}",
                        "rate": round(rate, 8),
                        "bid": round(bid, 8),
                        "ask": round(ask, 8),
                        "spread_pips": round((ask - bid) * pip_factor, 3),
                        "change_pct": 0.0,
                        "source_mode": source_mode,
                    }
                )
        data = {
            "status": "ok",
            "matrix": matrix,
            "rows": rows,
            "surface": heatmap,
            "source_mode": source_mode,
            "methodology": (
                "WCRS builds a cross-rate matrix from live exchangerate.host quotes when available. "
                "If the provider fails, it falls back to a labelled reference matrix; bid/ask are display spreads around the mid."
            ),
            "field_dictionary": {
                "rate": "Mid cross rate: quote currency units per one base currency unit.",
                "bid": "Display bid calculated as mid * 0.9999.",
                "ask": "Display ask calculated as mid * 1.0001.",
                "spread_pips": "Ask-bid spread converted to pips using JPY-aware pip sizing.",
                "source_mode": "live_exchangerate_host or reference_cross_rate_matrix.",
            },
        }
        warnings = [] if source_mode == "live_exchangerate_host" else ["live cross-rate provider unavailable; using labelled reference matrix"]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=data,
            sources=sources,
            warnings=warnings,
        )


@FunctionRegistry.register
class FRDFunction(BaseFunction):
    """FRD - Forward rates via covered interest parity."""

    code = "FRD"
    name = "FX Forward Rates"
    asset_classes = (AssetClass.FX,)
    category = "fx"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        base, quote, pair = _pair_from(instrument, params)
        spot, spot_source, source_mode = await _resolve_spot(self, pair, params)
        r_base = _rate_for(base, params.get("r_base"))
        r_quote = _rate_for(quote, params.get("r_quote"))
        tenors = _parse_tenors(params.get("tenors"), default=("1W", "1M", "3M", "6M", "1Y"))
        rows = []
        for tenor in tenors:
            t = tenor["years"]
            fwd = _forward(spot, r_base, r_quote, t)
            rows.append(
                {
                    "pair": pair,
                    "tenor": tenor["label"],
                    "tenor_years": round(t, 6),
                    "spot": round(spot, 6),
                    "forward": round(fwd, 6),
                    "forward_points": round(fwd - spot, 6),
                    "base_rate": r_base,
                    "quote_rate": r_quote,
                    "source_mode": source_mode,
                }
            )
        data = {
            "pair": pair,
            "base": base,
            "quote": quote,
            "S": round(spot, 6),
            "F": rows[2]["forward"] if len(rows) > 2 else rows[-1]["forward"],
            "r_base": r_base,
            "r_quote": r_quote,
            "T": rows[2]["tenor_years"] if len(rows) > 2 else rows[-1]["tenor_years"],
            "rows": rows,
            "curve": rows,
            "methodology": (
                "Covered interest parity: F = S * (1 + r_quote * T) / (1 + r_base * T). "
                "S is quote currency per base currency. Rates are annual decimals and T is year fraction."
            ),
            "field_dictionary": {
                "S": "Spot rate, quote currency per one base currency.",
                "F": "Forward rate for the highlighted/default tenor.",
                "r_base": "Annual risk-free/reference rate for the base currency.",
                "r_quote": "Annual risk-free/reference rate for the quote currency.",
                "T": "Tenor in years.",
                "forward_points": "Forward - spot.",
            },
        }
        return FunctionResult(
            code=self.code,
            instrument=instrument or Instrument(symbol=pair, asset_class=AssetClass.FX),
            data=data,
            sources=[spot_source, "covered_interest_parity_formula", "reference_policy_rate"],
            warnings=[] if source_mode == "live_yfinance_quote" else ["live spot unavailable; using labelled reference spot"],
        )


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

        # Smile inputs: explicit overrides win; otherwise scale 25d RR/BF to
        # the live ATM so the wings track the real vol level instead of being
        # fixed constants. RR sign follows the term-structure slope.
        rr_25_override = params.get("risk_reversal_25d", params.get("rr_25d"))
        bf_25_override = params.get("butterfly_25d", params.get("bf_25d"))

        surface = []
        series = []
        prev_atm: float | None = None
        atm_1m: float | None = None
        for i, tenor in enumerate(tenors):
            label = tenor["label"]
            term = atm_curve[i]
            slope_sign = 1.0
            if prev_atm is not None:
                slope_sign = 1.0 if term >= prev_atm else -1.0
            rr_25 = float(rr_25_override) if rr_25_override not in (None, "") else slope_sign * 0.06 * term
            bf_25 = float(bf_25_override) if bf_25_override not in (None, "") else 0.015 * term
            for delta in deltas:
                wing = {
                    "10P": bf_25 + 0.5 * abs(rr_25) - rr_25 / 2,
                    "25P": bf_25 - rr_25 / 2,
                    "ATM": 0.0,
                    "25C": bf_25 + rr_25 / 2,
                    "10C": bf_25 + 0.5 * abs(rr_25) + rr_25 / 2,
                }.get(delta, 0.0)
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
            prev_atm = term

        if atm_1m is None and atm_curve:
            atm_1m = atm_curve[min(1, len(atm_curve) - 1)]

        # Headline RR/BF (1M-ish) echoed on the card.
        head_term = atm_1m if atm_1m is not None else (atm_curve[0] if atm_curve else 0.0)
        head_rr = float(rr_25_override) if rr_25_override not in (None, "") else 0.06 * head_term
        head_bf = float(bf_25_override) if bf_25_override not in (None, "") else 0.015 * head_term

        as_of = datetime.now(timezone.utc).isoformat()
        warnings: list[str] = []
        if rv_warning:
            warnings.append(rv_warning)

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
            "deltas": deltas,
            "atm_vol_pct": round(head_term * 100, 4),
            "atm_1m_vol_pct": round((atm_1m or 0.0) * 100, 4),
            "risk_reversal_25d_pct": round(head_rr * 100, 4),
            "butterfly_25d_pct": round(head_bf * 100, 4),
            "cards": {
                "pair": pair,
                "atm_vol_pct": round(head_term * 100, 4),
                "risk_reversal_25d_pct": round(head_rr * 100, 4),
                "butterfly_25d_pct": round(head_bf * 100, 4),
                "vol_source": vol_source,
                "data_mode": data_mode,
                "as_of": as_of,
            },
            "methodology": (
                "OVDV anchors the ATM volatility term structure to live FX realized "
                "volatility: each tenor's ATM vol is the annualized standard deviation "
                "(x sqrt(252)) of daily log returns of the pair from yfinance, measured "
                "over a trailing window sized to that tenor (1W=5d ... 1Y=252d). The "
                "25-delta risk-reversal (RR) and butterfly (BF) smile is overlaid as a "
                "labelled model around the real ATM (RR scaled to ~6% of ATM with sign "
                "following the term slope, BF ~1.5% of ATM): 25P uses BF - RR/2, 25C uses "
                "BF + RR/2, 10P/10C add wing curvature. Explicit atm_vol/RR/BF inputs "
                "override the live anchor. If yfinance history is unavailable the surface "
                "falls back to a labelled reference vol and vol_source/data_mode say so."
            ),
            "field_dictionary": {
                "tenor": "Option expiry bucket.",
                "delta": "FX delta bucket: put wing, ATM, or call wing.",
                "vol": "Displayed implied volatility in percent.",
                "vol_decimal": "Same volatility as annual decimal.",
                "atm_vol_pct": "ATM (1M-anchor) annualized vol from live realized vol, in percent.",
                "risk_reversal_25d_pct": "25D call vol minus 25D put vol, in percent.",
                "butterfly_25d_pct": "Average 25D wing premium versus ATM, in percent.",
                "vol_source": "live_realized_vol (yfinance) or reference_fx_vol_model.",
                "data_mode": "DELAYED_REFERENCE when anchored to yfinance realized vol; MODELED on fallback.",
            },
            "next_actions": [
                "Override atm_vol / risk_reversal_25d / butterfly_25d to quote a desk surface.",
                "Switch the pair to inspect another currency's realized-vol term structure.",
            ],
        }
        sources = ["model:fx_vol_smile"]
        if rv_source:
            sources.insert(0, rv_source)
        return FunctionResult(
            code=self.code,
            instrument=instrument or Instrument(symbol=pair, asset_class=AssetClass.FX),
            data=data,
            sources=_unique(sources),
            warnings=warnings,
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


async def _resolve_spot(fn: BaseFunction, pair: str, params: dict[str, Any]) -> tuple[float, str, str]:
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
    return _template_spot(pair), "reference_fx_spot", "reference_model"


async def _atm_term_structure(
    fn: BaseFunction,
    pair: str,
    tenors: list[dict[str, Any]],
    params: dict[str, Any],
) -> tuple[list[float], str, str, str | None, str | None]:
    """Build a per-tenor ATM-vol curve anchored to live FX realized vol.

    Returns ``(atm_curve, vol_source, data_mode, rv_source, warning)`` where
    ``atm_curve`` is one annualized-vol decimal per requested tenor.

    Order of precedence:
      1. explicit ``atm_vol`` input (flat curve, user-quoted) — labelled input.
      2. live realized vol from yfinance daily history (the real anchor).
      3. labelled reference vol fallback on any network/data failure.
    """
    explicit_atm = params.get("atm_vol", params.get("vol"))
    if explicit_atm not in (None, ""):
        atm = float(explicit_atm)
        # honour the historical reference-model term slope so an explicit ATM
        # still produces a non-flat surface.
        curve = [max(0.0001, atm + i * 0.0015) for i in range(len(tenors))]
        return curve, "user_inputs", "MODELED", None, None

    closes = await _close_series(fn, pair, params)
    returns = _log_returns(closes)
    if len(returns) >= 4:
        curve: list[float] = []
        for tenor in tenors:
            window = _TENOR_WINDOW_DAYS.get(tenor["label"].upper())
            if window is None:
                window = max(5, min(252, int(round(tenor["years"] * 252))))
            win = returns[-window:] if len(returns) >= window else returns
            atm = _annualized_vol(win)
            curve.append(atm if atm and atm > 0 else _reference_atm_vol(pair))
        return curve, "live_realized_vol", "DELAYED_REFERENCE", "yfinance", None

    # Fallback: no usable history — labelled reference vol with a term slope.
    ref = _reference_atm_vol(pair)
    curve = [max(0.0001, ref + i * 0.0015) for i in range(len(tenors))]
    return (
        curve,
        "reference_fx_vol_model",
        "MODELED",
        None,
        "live realized-vol history unavailable; using labelled reference FX vol",
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


def _reference_atm_vol(pair: str) -> float:
    """Labelled fallback ATM vol (decimal) when no live history is available."""
    base = pair[:3].upper()
    quote = pair[3:6].upper()
    if "TRY" in (base, quote):
        return 0.22
    if "JPY" in (base, quote):
        return 0.095
    return 0.085


async def _history_rows(fn: BaseFunction, pair: str, params: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    days = int(float(params.get("days", 90)))
    start = datetime.now(timezone.utc) - timedelta(days=max(5, days))
    inst = Instrument(symbol=pair, asset_class=AssetClass.FX)
    timeout = float(params.get("yfinance_timeout", params.get("timeout", 4)))
    if fn.deps.yfinance:
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


def _daily_change(history: list[dict[str, Any]]) -> float:
    if len(history) < 2:
        return 0.0
    prev = _num(history[-2].get("close"))
    last = _num(history[-1].get("close"))
    if not prev or last is None:
        return 0.0
    return round((last / prev - 1.0) * 100.0, 4)


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


async def _cross_matrix(
    fn: BaseFunction,
    bases: list[str],
    quotes: list[str],
    params: dict[str, Any],
) -> tuple[dict[str, dict[str, float]], str, list[str]]:
    if _truthy(params.get("live", True)) and fn.deps.exchangerate_host:
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
            return live_rows, "live_exchangerate_host", ["exchangerate_host"]
    seed = {ccy: _seed_usd_value(ccy) for ccy in _unique([*bases, *quotes])}
    matrix = {
        base: {
            quote: (seed[base] / seed[quote] if seed.get(base) and seed.get(quote) else 0.0)
            for quote in quotes
        }
        for base in bases
    }
    return matrix, "reference_cross_rate_matrix", ["reference_cross_rate_matrix"]


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
