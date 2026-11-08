"""GEX — Gamma Exposure (dealer hedging structure).

Honesty contract: GEX is computed only from a live yfinance option chain and a
spot level that the caller supplied or a live quote. When either is missing the
function returns an explicit non-ok state (``needs_input`` /
``provider_unavailable`` / ``input_error``) with a reason and next actions. It
never serves a modeled strike grid, a default spot, or invented open interest
and implied vol.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.services.gamma_exposure import chain_gex

# Manifest defaults (manifest/seeds/gex_seed.py) for the model inputs.
DEFAULT_RISK_FREE = 0.045
DEFAULT_DIVIDEND_YIELD = 0.015
DEFAULT_EXPIRIES = 3  # manifest expiry_filter default: next_3
MAX_EXPIRIES = 3  # latency cap on per-expiry chain fetches
_RATE_BOUNDS = (0.0, 0.10)  # manifest min/max for risk_free and dividend_yield
_EXPIRY_FILTER_COUNTS = {"next_1": 1, "next_3": 3, "next_6": 6}
_SUPPORTED_CHOICES = {
    "iv_source": ("market",),
    "oi_source": ("exchange",),
    "dealer_assumption": ("short_calls_long_puts",),
}

DATA_MODE_LIVE = "live_yfinance"
DATA_MODE_LAST_SESSION = "last_session_yfinance"
DATA_MODE_UNSTAMPED = "snapshot_time_unknown"
DATA_MODE_UNAVAILABLE = "unavailable"

# summary.source_mode is derived from the snapshot state, never hard-coded, so
# a Friday-stamped chain served on Sunday cannot be labelled live (GEX#6).
_SOURCE_MODE_BY_DATA_MODE = {
    DATA_MODE_LIVE: "live_chain",
    DATA_MODE_LAST_SESSION: "last_session_chain",
    DATA_MODE_UNSTAMPED: "snapshot_time_unknown",
}

_GEX_FIELDS = {
    "strike": "Option strike bucket.",
    "gex": "Dealer-perspective gamma exposure in dollars per 1% underlying move.",
    "value": "Same as gex, provided for chart rendering.",
    "gamma_flip": "Spot level where total dealer GEX changes sign (zero crossing re-evaluated on a ±10% spot grid over the same chain); null when no crossing lies in that range.",
    "call_wall": "Strike with the largest absolute dealer call gamma exposure; gex is that call-side value (negative).",
    "put_wall": "Strike with the largest absolute dealer put gamma exposure; gex is that put-side value (positive).",
}

_METHODOLOGY = (
    "Dealer GEX assumes dealers are short call open interest and long put open interest. "
    "Black-Scholes gamma = N'(d1) / (S * sigma * sqrt(T)); exposure = gamma * OI * contract_size * S^2 * 1%. "
    "T runs to the 16:00 America/New_York expiry close for every expiry. "
    "Implied vol is each contract's market IV from the chain; a contract without a usable "
    "IV or expiry is left out and counted in excluded_contracts, never priced at a substitute vol."
)


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _as_utc_datetime(value: Any) -> datetime | None:
    """Parse a chain ``lastTradeDate`` stamp; None when it is missing or invalid."""
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            stamp = value
        else:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _rate_param(params: dict[str, Any], names: tuple[str, ...], default: float) -> float:
    for name in names:
        raw = params.get(name)
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a decimal rate between 0 and 0.10") from exc
        low, high = _RATE_BOUNDS
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{name}={raw!r} is outside the supported range 0 to 0.10")
        return value
    return default


def _expiry_count(params: dict[str, Any]) -> tuple[int, str | None]:
    """Number of nearest expiries to aggregate, plus a warning when capped."""
    if params.get("max_expiries") not in (None, ""):
        try:
            requested = int(params["max_expiries"])
        except (TypeError, ValueError) as exc:
            raise ValueError("max_expiries must be a whole number") from exc
    else:
        raw = params.get("expiry_filter")
        # The manifest control is a multiselect (default ["next_3"]): the widest
        # selected window wins; any unknown choice is rejected, never ignored.
        choices = [str(c).strip().lower() for c in (raw if isinstance(raw, (list, tuple)) else [raw])
                   if c not in (None, "")]
        if not choices:
            requested = DEFAULT_EXPIRIES
        else:
            unknown = [c for c in choices if c not in _EXPIRY_FILTER_COUNTS]
            if unknown:
                supported = ", ".join(_EXPIRY_FILTER_COUNTS)
                raise ValueError(f"expiry_filter={unknown[0]!r} is not supported by GEX; supported: {supported}")
            requested = max(_EXPIRY_FILTER_COUNTS[c] for c in choices)
    requested = max(1, requested)
    if requested > MAX_EXPIRIES:
        return MAX_EXPIRIES, (
            f"Requested {requested} expiries; GEX aggregates at most {MAX_EXPIRIES} per request."
        )
    return requested, None


def _validate_choices(params: dict[str, Any]) -> None:
    for key, allowed in _SUPPORTED_CHOICES.items():
        raw = params.get(key)
        if raw in (None, ""):
            continue
        if str(raw).strip().lower() not in allowed:
            raise ValueError(f"{key}={raw!r} is not supported by GEX; supported: {', '.join(allowed)}")


def _shape_gex_payload(
    raw: dict[str, Any],
    *,
    symbol: str,
    expiries: list[str],
    as_of: str | None,
    data_mode: str,
    model_inputs: dict[str, Any],
) -> dict[str, Any]:
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
        "underlying": symbol,
        "spot": raw.get("spot"),
        "as_of": as_of,
        "data_mode": data_mode,
        "iv_source": "market",
        "oi_source": "exchange",
        "dealer_assumption": "short_calls_long_puts",
        "model_inputs": model_inputs,
        "expiries": expiries,
        "rows": rows,
        "curve": rows,
        "summary": {
            "net_gex": raw.get("net_gex"),
            "call_gex_total": raw.get("call_gex_total"),
            "put_gex_total": raw.get("put_gex_total"),
            "gamma_flip": raw.get("gamma_flip"),
            "call_wall": (raw.get("call_wall") or {}).get("strike"),
            "put_wall": (raw.get("put_wall") or {}).get("strike"),
            "gamma_flip_method": raw.get("gamma_flip_method"),
            "n_strikes": raw.get("n_strikes") or len(rows),
            "source_mode": _SOURCE_MODE_BY_DATA_MODE.get(data_mode, DATA_MODE_UNAVAILABLE),
            "synthetic": False,
            "degraded": False,
            "contracts_used": raw.get("contracts_used"),
            "excluded_contracts": raw.get("excluded"),
            "oi_missing_contracts": raw.get("oi_missing"),
        },
        "call_wall": raw.get("call_wall"),
        "put_wall": raw.get("put_wall"),
        "methodology": _METHODOLOGY,
        "field_dictionary": _GEX_FIELDS,
    }


def _unavailable_payload(
    symbol: str,
    *,
    status: str,
    reason: str,
    next_actions: list[str],
    expiries: list[str] | None = None,
    model_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Honest non-ok state: no strikes, no gamma numbers, no placeholder spot."""
    return {
        "status": status,
        "symbol": symbol,
        "underlying": symbol,
        "reason": reason,
        "next_actions": next_actions,
        # Echo only a spot the caller or quote actually supplied, never a default.
        "spot": (model_inputs or {}).get("spot"),
        "as_of": None,
        "data_mode": DATA_MODE_UNAVAILABLE,
        "iv_source": "market",
        "oi_source": "exchange",
        "dealer_assumption": "short_calls_long_puts",
        "model_inputs": model_inputs or {},
        "expiries": expiries or [],
        "rows": [],
        "curve": [],
        "summary": {
            "net_gex": None,
            "call_gex_total": None,
            "put_gex_total": None,
            "gamma_flip": None,
            "call_wall": None,
            "put_wall": None,
            "gamma_flip_method": "spot_grid_zero_crossing",
            "n_strikes": 0,
            "source_mode": DATA_MODE_UNAVAILABLE,
            "synthetic": False,
            "degraded": False,
        },
        "call_wall": None,
        "put_wall": None,
        "methodology": _METHODOLOGY,
        "field_dictionary": _GEX_FIELDS,
    }


@FunctionRegistry.register
class GEXFunction(BaseFunction):
    code = "GEX"
    name = "Gamma Exposure"
    asset_classes = (AssetClass.EQUITY,)
    category = "derivative"
    description = "Per-strike dealer gamma exposure + flip + walls."

    def _result(
        self,
        instrument: Instrument | None,
        data: dict[str, Any],
        *,
        sources: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> FunctionResult:
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=data,
            sources=sources or [],
            metadata=metadata or {},
        )

    async def _live_spot(self, inst: Instrument, timeout: float) -> float | None:
        try:
            quote = await asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.QUOTE, instrument=inst,
                    extra={"timeout": timeout},
                )),
                timeout=timeout + 0.5,
            )
        except Exception:
            return None
        return _positive(getattr(quote, "last", None))

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # The underlying must be a user choice. The router injects a default
        # symbol and flags it __explicit_symbol=False; GEX never prices a
        # guessed ticker (GEX#3 / data policy), so that case is needs_input.
        explicit = params.get("__explicit_symbol", True) is not False
        raw_symbol = ""
        if explicit:
            raw_symbol = str(params.get("symbol") or params.get("underlying") or "").strip()
            if instrument is not None and instrument.symbol:
                raw_symbol = str(instrument.symbol).strip()
        sym = raw_symbol.upper()
        live_options = _truthy(params.get("live_options") or params.get("deep"))
        if not sym:
            return self._result(instrument, _unavailable_payload(
                "", status="needs_input",
                reason="GEX needs an underlying symbol; none was supplied.",
                next_actions=["Pass symbol=<ticker>, for example SPY or NVDA"],
            ))
        spot_inst = instrument or Instrument(symbol=sym, asset_class=AssetClass.EQUITY)

        # 1. Validate every declared input before any network call.
        try:
            rate = _rate_param(params, ("risk_free", "rate"), DEFAULT_RISK_FREE)
            div_yield = _rate_param(params, ("dividend_yield", "div_yield"), DEFAULT_DIVIDEND_YIELD)
            _validate_choices(params)
            count, cap_warning = _expiry_count(params)
        except ValueError as exc:
            return self._result(instrument, _unavailable_payload(
                sym, status="input_error", reason=str(exc),
                next_actions=["Correct the input and run again"],
            ))
        timeout = max(1.0, min(float(params.get("yfinance_timeout", 2.5)), 3.0))

        # 2. Underlying spot: explicit input wins, otherwise the live quote.
        spot = _positive(params.get("spot"))
        spot_source: str | None = "explicit_input" if spot is not None else None
        if spot is None and self.deps.yfinance is not None and _truthy(params.get("live")):
            spot = await self._live_spot(spot_inst, timeout)
            if spot is not None:
                spot_source = "yfinance_quote"

        model_inputs: dict[str, Any] = {
            "spot": spot,
            "spot_source": spot_source,
            "risk_free": rate,
            "dividend_yield": div_yield,
            "time_basis": "calendar days / 365 to the 16:00 America/New_York expiry close",
            "as_of_basis": "latest option lastTradeDate in the fetched chain",
            "oi_basis": "yfinance openInterest (exchange, prior session); a missing value counts as zero and is disclosed",
            "iv_basis": "yfinance impliedVolatility per contract; a contract without a usable IV or expiry is excluded and disclosed",
            "contract_size": 100,
        }

        if not live_options:
            return self._result(instrument, _unavailable_payload(
                sym, status="needs_input",
                reason="GEX is computed from the live options chain; set live_options=true to request it.",
                next_actions=["Set live_options=true", "Use a liquid optionable underlying such as SPY or NVDA"],
                model_inputs=model_inputs,
            ))
        if self.deps.yfinance is None:
            return self._result(instrument, _unavailable_payload(
                sym, status="provider_unavailable",
                reason="Options chain provider (yfinance) is not configured, so GEX cannot be computed.",
                next_actions=["Configure the yfinance provider and run again"],
                model_inputs=model_inputs,
            ))
        if spot is None:
            if _truthy(params.get("live")):
                return self._result(instrument, _unavailable_payload(
                    sym, status="provider_unavailable",
                    reason=f"No live spot quote for {sym}; GEX needs the underlying price.",
                    next_actions=["Retry when the quote provider responds", "Or pass spot=<price> explicitly"],
                    model_inputs=model_inputs,
                ))
            return self._result(instrument, _unavailable_payload(
                sym, status="needs_input",
                reason="GEX needs the underlying spot: pass spot=<price>, or live=true so the quote supplies it.",
                next_actions=["Pass spot=<price>", "Or set live=true"],
                model_inputs=model_inputs,
            ))

        # 3. Expiry list, then the nearest ``count`` expiries.
        timeout = max(1.0, min(float(params.get("yfinance_timeout", 3)), 4.0))
        try:
            chains = await asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OPTIONS_CHAIN, instrument=spot_inst,
                    extra={"timeout": timeout})),
                timeout=timeout + 1,
            )
        except Exception:
            chains = {}
        listed = [str(e) for e in ((chains or {}).get("expiries") or []) if e]
        if not listed:
            return self._result(instrument, _unavailable_payload(
                sym, status="provider_unavailable",
                reason=f"yfinance returned no listed option expiries for {sym}.",
                next_actions=["Retry later", "Confirm the symbol has listed options"],
                model_inputs=model_inputs,
            ), sources=["yfinance_options"])
        expiries = listed[:count]

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

        all_calls: list[dict[str, Any]] = []
        all_puts: list[dict[str, Any]] = []
        stamps: list[datetime] = []
        for exp, ch in results:
            if not ch:
                continue
            for frame, bucket in ((ch.get("calls"), all_calls), (ch.get("puts"), all_puts)):
                if frame is None or len(frame) == 0:
                    continue
                for _, r in frame.iterrows():
                    stamp = _as_utc_datetime(r.get("lastTradeDate"))
                    if stamp is not None:
                        stamps.append(stamp)
                    bucket.append({
                        "strike": r.get("strike"),
                        "openInterest": r.get("openInterest"),
                        "impliedVolatility": r.get("impliedVolatility"),
                        "expiry": exp,
                    })

        if not all_calls and not all_puts:
            return self._result(instrument, _unavailable_payload(
                sym, status="provider_unavailable",
                reason=f"No live option rows for {sym} in the selected expiries ({', '.join(expiries)}).",
                next_actions=["Retry later", "Try another expiry_filter"],
                expiries=expiries, model_inputs=model_inputs,
            ), sources=["yfinance_options"])

        # 4. Snapshot time and data mode from the chain itself, not the request time.
        as_of_dt = max(stamps) if stamps else None
        as_of = as_of_dt.isoformat() if as_of_dt else None
        if as_of_dt is None:
            data_mode = DATA_MODE_UNSTAMPED
        elif as_of_dt.date() < datetime.now(timezone.utc).date():
            data_mode = DATA_MODE_LAST_SESSION
        else:
            data_mode = DATA_MODE_LIVE

        out = chain_gex(spot=spot, calls=all_calls, puts=all_puts, rate=rate,
                        div_yield=div_yield)
        out["symbol"] = sym
        out["expiries"] = expiries
        if not out.get("contracts_used"):
            return self._result(instrument, _unavailable_payload(
                sym, status="provider_unavailable",
                reason=(f"No option contract for {sym} in the selected expiries has a usable "
                        "implied volatility and expiry, so GEX cannot be computed honestly."),
                next_actions=["Retry later", "Try another expiry_filter"],
                expiries=expiries, model_inputs=model_inputs,
            ), sources=["yfinance_options"])
        shaped = _shape_gex_payload(
            out,
            symbol=sym,
            expiries=expiries,
            as_of=as_of,
            data_mode=data_mode,
            model_inputs=model_inputs,
        )
        sources = ["yfinance_options", "black_scholes_gamma_formula"]
        if spot_source == "yfinance_quote":
            sources.insert(0, "yfinance_quote")
        warnings = [cap_warning] if cap_warning else []
        excluded = out.get("excluded") or {}
        if excluded.get("implied_vol"):
            warnings.append(
                f"{excluded['implied_vol']} option contract(s) without a usable implied volatility "
                "were left out of GEX."
            )
        if excluded.get("strike") or excluded.get("expiry"):
            warnings.append(
                f"{int(excluded.get('strike', 0)) + int(excluded.get('expiry', 0))} option "
                "contract(s) without a usable strike or expiry were left out of GEX."
            )
        if out.get("oi_missing"):
            warnings.append(
                f"{out['oi_missing']} option contract(s) had no open interest value and count as zero."
            )
        if data_mode == DATA_MODE_LAST_SESSION:
            warnings.append(
                f"Option chain snapshot is from the last session ({as_of[:10]}), not the current session."
            )
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=shaped,
            sources=sources,
            warnings=warnings,
            metadata={
                "live": data_mode == DATA_MODE_LIVE,
                "data_mode": data_mode,
            },
        )


__all__ = ["GEXFunction"]
