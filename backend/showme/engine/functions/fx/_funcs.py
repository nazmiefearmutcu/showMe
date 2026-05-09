"""FXFC, FXIP, WCRS, FRD, OVDV - FX function suite."""

from __future__ import annotations

import asyncio
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
            warnings=[] if source_mode == "live_yfinance_quote" else ["live spot unavailable; using labelled reference spot"],
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
            warnings=[] if source_mode.startswith("live") else ["live spot unavailable; using labelled reference spot"],
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
    """OVDV - FX Option Volatility Surface."""

    code = "OVDV"
    name = "FX Option Volatility Surface"
    asset_classes = (AssetClass.FX, AssetClass.DERIVATIVE)
    category = "fx"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        base, quote, pair = _pair_from(instrument, params)
        tenors = _parse_tenors(params.get("tenors"), default=("1W", "1M", "3M", "6M", "1Y"))
        deltas = ["10P", "25P", "ATM", "25C", "10C"]
        atm_vol = float(params.get("atm_vol", params.get("vol", 0.085)))
        rr_25 = float(params.get("risk_reversal_25d", params.get("rr_25d", 0.002)))
        bf_25 = float(params.get("butterfly_25d", params.get("bf_25d", 0.0015)))
        surface = []
        for i, tenor in enumerate(tenors):
            term = atm_vol + i * 0.0015
            for delta in deltas:
                wing = {"10P": 0.006, "25P": bf_25 - rr_25 / 2, "ATM": 0.0, "25C": bf_25 + rr_25 / 2, "10C": 0.006}.get(delta, 0.0)
                vol = max(0.0001, term + wing)
                surface.append(
                    {
                        "pair": pair,
                        "tenor": tenor["label"],
                        "tenor_years": round(tenor["years"], 6),
                        "delta": delta,
                        "vol": round(vol * 100, 4),
                        "vol_decimal": round(vol, 6),
                        "source_mode": "reference_fx_vol_smile_model",
                    }
                )
        data = {
            "pair": pair,
            "base": base,
            "quote": quote,
            "surface": surface,
            "tenors": [t["label"] for t in tenors],
            "deltas": deltas,
            "atm_vol_pct": round(atm_vol * 100, 4),
            "risk_reversal_25d_pct": round(rr_25 * 100, 4),
            "butterfly_25d_pct": round(bf_25 * 100, 4),
            "methodology": (
                "OVDV renders a labelled FX volatility smile/surface model. ATM vol is shifted by tenor; "
                "25-delta puts/calls use butterfly +/- half risk-reversal; 10-delta wings add extra smile curvature. "
                "No live OTC FX vol vendor is configured, so source_mode marks the surface as a reference model."
            ),
            "field_dictionary": {
                "tenor": "Option expiry bucket.",
                "delta": "FX delta bucket: put wing, ATM, or call wing.",
                "vol": "Displayed implied volatility in percent.",
                "vol_decimal": "Same volatility as annual decimal.",
                "risk_reversal_25d_pct": "25D call vol minus 25D put vol, in percent.",
                "butterfly_25d_pct": "Average 25D wing premium versus ATM, in percent.",
            },
        }
        return FunctionResult(
            code=self.code,
            instrument=instrument or Instrument(symbol=pair, asset_class=AssetClass.FX),
            data=data,
            sources=["reference_fx_vol_smile_model"],
            warnings=["live OTC FX volatility vendor is not configured; using labelled reference surface"],
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


def _forward(spot: float, r_base: float, r_quote: float, years: float) -> float:
    return spot * (1 + r_quote * years) / (1 + r_base * years)


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
