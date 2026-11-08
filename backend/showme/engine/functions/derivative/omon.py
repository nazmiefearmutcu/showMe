"""OMON — Option Monitor (single-name option chain).

De-garbaged: fetches a real listed option chain from yfinance (keyless) for the
nearest expiry of a single underlier — strikes, bid/ask, open interest, volume
and implied volatility — and computes Black-Scholes greeks via the shared
pricer in ``derivative/ovme.py``. Falls back to a clearly-labelled
``provider_unavailable`` shape only on a genuine network/data outage.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import (
    BaseFunction,
    FunctionRegistry,
    FunctionResult,
)
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.derivative.ovme import _bs_price

# Continuously-compounded risk-free rate used for greeks. Kept as a documented
# constant so the chain stays keyless; OVME uses the same 5% default.
_RISK_FREE_RATE = 0.05
_DAYS_PER_YEAR = 365.0

# Implied vol below this floor is a failed inversion (yfinance reports e.g. 1e-5
# for deep-ITM quotes the solver could not invert), not a real vol.
_IV_FLOOR = 0.001

# The chain is "live" only when its newest option trade is this recent. Older
# trades are the last trading session or a delayed feed and are labelled so.
_LIVE_TRADE_WINDOW = timedelta(minutes=60)

async def _resolve_spot(
    deps: Any, instrument: Instrument, params: dict[str, Any],
) -> float | None:
    """Resolve the underlying spot for the option monitor.

    Resolution order:

    1. An explicit, finite, positive ``params["spot"]`` always wins.
    2. Otherwise the live spot is pulled from the yfinance QUOTE adapter
       (``deps.yfinance`` -> :class:`DataKind.QUOTE` -> ``.last``).
    3. When neither signal yields a price, returns ``None``. No placeholder is
       substituted: moneyness and delta must not be computed around a
       made-up underlier price (ASOF-1).
    """
    if "spot" in params and params.get("spot") is not None:
        try:
            value = float(params["spot"])
        except (TypeError, ValueError):
            value = None
        if value is not None and value > 0 and math.isfinite(value):
            return value
    yfinance = getattr(deps, "yfinance", None)
    if yfinance is None:
        return None
    try:
        timeout = max(1.0, min(float(params.get("yfinance_timeout", 3)), 4.0))
    except (TypeError, ValueError):
        timeout = 3.0
    try:
        quote = await asyncio.wait_for(
            yfinance.fetch(DataRequest(
                kind=DataKind.QUOTE, instrument=instrument,
                extra={"timeout": timeout, "offline_ok": True},
            )),
            timeout=timeout + 0.5,
        )
    except Exception:
        return None
    # The QUOTE adapter exposes ``.last`` on its result object; tolerate a
    # dict-shaped quote too so a mock that returns a plain dict still works.
    last: Any = None
    if quote is not None:
        last = getattr(quote, "last", None)
        if last is None and isinstance(quote, dict):
            for key in ("last", "lastPrice", "price", "regularMarketPrice"):
                if quote.get(key) is not None:
                    last = quote.get(key)
                    break
    try:
        value = float(last) if last is not None else 0.0
    except (TypeError, ValueError):
        return None
    if value > 0 and math.isfinite(value):
        return value
    return None


def _num(value: Any) -> float | None:
    """Coerce a pandas/NumPy/JSON cell to a finite float, else None."""
    try:
        if value is None:
            return None
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _years_to_expiry(expiry: str) -> float:
    """Fraction of a year from now (UTC) to an ISO expiry date (YYYY-MM-DD)."""
    try:
        exp = datetime.strptime(expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return 0.0
    now = datetime.now(timezone.utc)
    days = (exp - now).total_seconds() / 86400.0
    # Treat expiry day as having a small positive tau so greeks stay finite.
    return max(days, 0.5) / _DAYS_PER_YEAR


def _as_utc(value: Any) -> datetime | None:
    """Coerce a yfinance ``lastTradeDate`` cell (Timestamp/datetime/str) to UTC."""
    if value is None or value != value:  # NaN / NaT compare unequal to themselves
        return None
    dt: Any = value
    if not isinstance(dt, datetime):
        to_py = getattr(dt, "to_pydatetime", None)
        if callable(to_py):
            try:
                dt = to_py()
            except Exception:
                return None
        elif isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _below_intrinsic(mid: float | None, spot: float | None, strike: float, is_call: bool) -> bool:
    """True when the quoted mid is under intrinsic value (no-arbitrage violation).

    Intrinsic value is a lower bound for both American and European options, so
    a mid below it means the implied vol is undefined for that quote.
    """
    if mid is None or not spot or spot <= 0:
        return False
    intrinsic = max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)
    return mid + 1e-6 < intrinsic


def _fetch_chain_sync(underlier: str, expiry: str | None) -> dict[str, Any]:
    """Blocking yfinance call — run via ``asyncio.to_thread``.

    Returns a dict with ``spot``, the resolved ``expiry``, the list of available
    expiries, and per-side row records keyed by strike.
    """
    import yfinance as yf  # local import keeps module import cheap

    ticker = yf.Ticker(underlier)

    expiries = list(ticker.options or ())
    if not expiries:
        raise ValueError(f"no listed option expiries for {underlier!r}")

    chosen = expiry if expiry in expiries else expiries[0]

    chain = ticker.option_chain(chosen)
    calls_df = chain.calls
    puts_df = chain.puts

    # Resolve a spot price for greeks / moneyness.
    spot: float | None = None
    try:
        info = ticker.fast_info
        for key in ("last_price", "lastPrice", "regularMarketPrice"):
            try:
                spot = _num(getattr(info, key, None))
            except Exception:
                spot = None
            if spot:
                break
    except Exception:
        spot = None

    def _records(df: Any) -> list[dict[str, Any]]:
        if df is None or getattr(df, "empty", True):
            return []
        cols = [
            "strike",
            "bid",
            "ask",
            "openInterest",
            "volume",
            "impliedVolatility",
            "lastPrice",
            "lastTradeDate",
        ]
        present = [c for c in cols if c in df.columns]
        return df[present].to_dict(orient="records")

    return {
        "spot": spot,
        "expiry": chosen,
        "expiries": expiries,
        "calls": _records(calls_df),
        "puts": _records(puts_df),
    }


@FunctionRegistry.register
class OMONFunction(BaseFunction):
    """Bloomberg-style OMON: full option chain monitor for a single underlier."""

    code = "OMON"
    name = "Option Monitor"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF, AssetClass.DERIVATIVE)
    category = "derivative"

    _METHODOLOGY = (
        "Listed option chain pulled live from yfinance for the nearest (or "
        "requested) expiry: strikes, best bid/ask, open interest, traded volume "
        "and implied volatility per side. Delta is computed with Black-Scholes "
        "(same pricer as OVME) using each leg's own implied vol, the live spot, "
        f"a {int(_RISK_FREE_RATE * 100)}% risk-free rate, and the calendar time "
        "to expiry."
    )

    _FIELD_DICTIONARY = {
        "strike": "Option strike price",
        "moneyness": "Strike divided by live spot price",
        "call_bid": "Best bid for the call option",
        "call_ask": "Best ask for the call option",
        "call_oi": "Open interest for the call option",
        "call_volume": "Traded volume for the call option today",
        "call_iv": "Implied volatility for the call option",
        "call_delta": "Black-Scholes delta for the call option",
        "put_bid": "Best bid for the put option",
        "put_ask": "Best ask for the put option",
        "put_oi": "Open interest for the put option",
        "put_volume": "Traded volume for the put option today",
        "put_iv": "Implied volatility for the put option",
        "put_delta": "Black-Scholes delta for the put option",
    }

    def _unavailable(
        self,
        instrument: Instrument | None,
        underlier: str,
        expiry: str | None,
        reason: str,
    ) -> FunctionResult:
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "provider_unavailable",
                "underlier": underlier,
                "expiry": expiry,
                "rows": [],
                "series": [],
                "cards": [],
                "methodology": self._METHODOLOGY,
                "field_dictionary": self._FIELD_DICTIONARY,
                "next_actions": [
                    "Verify the underlier ticker has listed options.",
                    "Retry once network access to yfinance is restored.",
                ],
            },
            sources=["yfinance"],
            warnings=[f"Live option chain unavailable: {reason}"],
            metadata={"underlier": underlier, "expiry": expiry},
        )

    async def execute(
        self, instrument: Instrument | None = None, **params: Any
    ) -> FunctionResult:
        underlier = (
            (instrument.symbol if instrument else None)
            or params.get("underlier")
            or "AAPL"
        ).upper()
        requested_expiry = params.get("expiry")

        try:
            chain = await asyncio.to_thread(
                _fetch_chain_sync, underlier, requested_expiry
            )
        except Exception as exc:  # network / parse / no-options
            return self._unavailable(
                instrument, underlier, requested_expiry, str(exc) or type(exc).__name__
            )

        expiry: str = chain["expiry"]
        spot = _num(chain.get("spot"))
        if spot is None or spot <= 0:
            # The chain didn't carry a usable underlying price — anchor on the
            # live quote adapter (or an explicit `spot` param) instead of
            # leaving greeks/moneyness blank.
            spot_instrument = instrument or Instrument(
                symbol=underlier, asset_class=AssetClass.EQUITY
            )
            resolved = await _resolve_spot(self.deps, spot_instrument, params)
            spot = _num(resolved)
        if spot is not None and spot <= 0:
            spot = None
        # No real spot: moneyness, ATM IV and delta stay blank rather than being
        # computed around an invented price, and the chain is not labelled live.
        spot_unavailable = spot is None
        tau = _years_to_expiry(expiry)

        # Merge calls and puts on strike.
        merged: dict[float, dict[str, Any]] = {}
        # Quotes whose IV is undefined (failed inversion or below no-arbitrage
        # bound). Their IV and delta are null, never 0.0 / -1.0 placeholders.
        iv_undefined = {"count": 0}

        def _ingest(records: list[dict[str, Any]], side: str) -> None:
            is_call = side == "call"
            for rec in records:
                strike = _num(rec.get("strike"))
                if strike is None:
                    continue
                row = merged.setdefault(strike, {"strike": round(strike, 4)})
                bid = _num(rec.get("bid"))
                ask = _num(rec.get("ask"))
                iv_raw = _num(rec.get("impliedVolatility"))
                oi = _num(rec.get("openInterest"))
                vol = _num(rec.get("volume"))
                mid = (bid + ask) / 2.0 if bid is not None and ask is not None and ask > 0 else None
                has_quote = bid is not None or ask is not None
                iv_bad = (
                    iv_raw is None
                    or iv_raw < _IV_FLOOR
                    or _below_intrinsic(mid, spot, strike, is_call)
                )
                if iv_bad and has_quote:
                    iv_undefined["count"] += 1
                iv = None if iv_bad else iv_raw
                row[f"{side}_bid"] = bid
                row[f"{side}_ask"] = ask
                row[f"{side}_oi"] = int(oi) if oi is not None else None
                row[f"{side}_volume"] = int(vol) if vol is not None else None
                row[f"{side}_iv"] = round(iv, 4) if iv is not None else None
                delta = None
                if spot and iv and iv > 0 and tau > 0 and strike > 0:
                    # _bs_price(S, K, T, r, sigma, q, is_call) — q=0 dividend yield.
                    delta = _bs_price(
                        spot, strike, tau, _RISK_FREE_RATE, iv, 0.0, is_call
                    ).get("delta")
                row[f"{side}_delta"] = delta

        _ingest(chain.get("calls", []), "call")
        _ingest(chain.get("puts", []), "put")

        # Newest option trade across the chain = the chain's real timestamp.
        trade_times = [
            ts
            for rec in list(chain.get("calls", [])) + list(chain.get("puts", []))
            if (ts := _as_utc(rec.get("lastTradeDate"))) is not None
        ]
        last_trade = max(trade_times) if trade_times else None
        now_utc = datetime.now(timezone.utc)
        is_live = last_trade is not None and (now_utc - last_trade) <= _LIVE_TRADE_WINDOW

        rows: list[dict[str, Any]] = []
        for strike in sorted(merged):
            row = merged[strike]
            row.setdefault("call_bid", None)
            row.setdefault("call_ask", None)
            row.setdefault("call_oi", None)
            row.setdefault("call_volume", None)
            row.setdefault("call_iv", None)
            row.setdefault("call_delta", None)
            row.setdefault("put_bid", None)
            row.setdefault("put_ask", None)
            row.setdefault("put_oi", None)
            row.setdefault("put_volume", None)
            row.setdefault("put_iv", None)
            row.setdefault("put_delta", None)
            row["moneyness"] = round(strike / spot, 4) if spot else None
            rows.append(row)

        if not rows:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "empty",
                    "underlier": underlier,
                    "expiry": expiry,
                    "rows": [],
                    "series": [],
                    "cards": [],
                    "methodology": self._METHODOLOGY,
                    "field_dictionary": self._FIELD_DICTIONARY,
                },
                sources=["yfinance"],
                warnings=[f"No option strikes returned for {underlier} {expiry}."],
                metadata={"underlier": underlier, "expiry": expiry},
            )

        # IV-skew series for the chart_grammar (x=strike, series=call_iv/put_iv).
        series = [
            {
                "strike": r["strike"],
                "call_iv": r.get("call_iv"),
                "put_iv": r.get("put_iv"),
            }
            for r in rows
        ]

        # ATM IV = average of call/put IV at the strike nearest spot.
        atm_iv: float | None = None
        if spot:
            atm_row = min(rows, key=lambda r: abs(r["strike"] - spot))
            atm_ivs = [
                v for v in (atm_row.get("call_iv"), atm_row.get("put_iv")) if v is not None
            ]
            if atm_ivs:
                atm_iv = round(sum(atm_ivs) / len(atm_ivs), 4)

        total_call_oi = sum(r["call_oi"] for r in rows if r.get("call_oi"))
        total_put_oi = sum(r["put_oi"] for r in rows if r.get("put_oi"))

        warnings: list[str] = []
        if spot_unavailable:
            warnings.append(
                "Underlying spot price unavailable (no live quote and no spot "
                "param); moneyness, ATM IV and delta are not computed."
            )
        if iv_undefined["count"]:
            warnings.append(
                f"Implied vol undefined for {iv_undefined['count']} quote(s) "
                "(failed inversion or quote below the no-arbitrage bound); "
                "shown as blank, delta not computed."
            )
        if last_trade is None:
            warnings.append(
                "Option chain has no trade timestamps; freshness cannot be verified, "
                "so the chain is not labelled live."
            )
        elif not is_live:
            warnings.append(
                f"Not live: newest option trade is {last_trade.isoformat()} UTC "
                "(last session or delayed feed)."
            )

        cards = [
            {
                "underlier": underlier,
                "expiry": expiry,
                "spot": round(spot, 4) if spot else None,
                "atm_iv": atm_iv,
                "total_call_oi": total_call_oi,
                "total_put_oi": total_put_oi,
            }
        ]

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "underlier": underlier,
                "expiry": expiry,
                "expiries": chain.get("expiries", []),
                "spot": round(spot, 4) if spot else None,
                "rows": rows,
                "series": series,
                "cards": cards,
                "summary": {
                    "underlier": underlier,
                    "expiry": expiry,
                    "spot": round(spot, 4) if spot else None,
                    "atm_iv": atm_iv,
                    "total_call_oi": total_call_oi,
                    "total_put_oi": total_put_oi,
                    "strike_count": len(rows),
                    "iv_undefined_count": iv_undefined["count"],
                    "last_trade_at": last_trade.isoformat() if last_trade else None,
                },
                "methodology": self._METHODOLOGY,
                "field_dictionary": self._FIELD_DICTIONARY,
            },
            sources=["yfinance"],
            warnings=warnings,
            metadata={
                "underlier": underlier,
                "expiry": expiry,
                # as_of is the newest option trade date, not the fetch date.
                "as_of": last_trade.date().isoformat() if last_trade else None,
                "as_of_timestamp": last_trade.isoformat() if last_trade else None,
                "fetched_at": now_utc.isoformat(),
                "strike_count": len(rows),
                "live": is_live and not spot_unavailable,
                "data_mode": (
                    "spot_unavailable"
                    if spot_unavailable
                    else (
                        "live_yfinance"
                        if is_live
                        else ("last_trade_yfinance" if last_trade else "yfinance_no_trade_time")
                    )
                ),
            },
        )
