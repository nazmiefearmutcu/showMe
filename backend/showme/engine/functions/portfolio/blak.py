"""BLAK — Black-Litterman expected returns + implied portfolio."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest, DataSourceError
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.return_series import align_return_series, close_to_daily_returns
from showme.engine.services.black_litterman import (
    implied_optimal_weights,
    implied_returns,
    posterior,
)

LOG = logging.getLogger("showme.blak")


def _template_returns(symbols: list[str], days: int) -> pd.DataFrame:
    periods = max(60, min(days, 504))
    index = pd.date_range(end=datetime.now(timezone.utc).date(), periods=periods, freq="B")
    periods = len(index)
    t = np.arange(periods, dtype=float)
    rows = {}
    for i, sym in enumerate(symbols):
        rows[sym] = 0.00025 + i * 0.00003 + np.sin((t + i * 7) / (11 + i)) * (0.006 + i * 0.001)
    return pd.DataFrame(rows, index=index)


@FunctionRegistry.register
class BLAKFunction(BaseFunction):
    code = "BLAK"
    name = "Black-Litterman"
    category = "portfolio"
    description = "Posterior expected returns combining market prior with views."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbols = params.get("symbols") or []
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbols:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=["symbols required"])
        days = int(params.get("days", 504))
        delta = float(params.get("delta", 2.5))
        tau = float(params.get("tau", 0.05))
        market_caps = params.get("market_caps") or {}  # symbol → mcap
        views = params.get("views") or []
        live = _truthy(params.get("live_returns") or params.get("live"))
        # B4: Do NOT pre-claim ``yfinance`` as the source. We only know what
        # was actually used after the live fetch decides whether it has
        # enough rows to skip the synthetic fallback.
        sources: list[str] = []
        live_fetch_errors: list[str] = []
        live_fetch_ok_symbols: list[str] = []
        # Fix A7-C6 / Bug #13: dollar-volume was being used as a market-cap
        # proxy which made BTC dominate at ~99.99% and ETH collapse to ~0%.
        # Pull real market cap (circulating supply × price) up-front.
        # For crypto we route through the CoinGecko adapter when wired; for
        # other classes we use a yfinance REFDATA pass. Anything we cannot
        # resolve falls back to an equal-weight prior with data_state set to
        # ``approximate`` so the UI can surface the degradation.
        mcap_lookup, mcap_data_state, mcap_sources = await _resolve_market_caps(
            self.deps, symbols, market_caps
        )

        async def _ret(sym: str) -> tuple[str, pd.Series, float]:
            # B4: narrow the catch to expected provider failures so genuine
            # bugs (NameError, type errors, etc.) surface at the call site
            # instead of being papered over with an empty series.
            try:
                inst = Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
                if self.deps.symbol_registry:
                    r = await self.deps.symbol_registry.resolve(sym)
                    if r:
                        inst = r
                df = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.OHLCV, instrument=inst,
                        start=datetime.now(timezone.utc) - timedelta(days=days),
                        interval="1d",
                    )),
                    timeout=8,
                )
                rets = close_to_daily_returns(df)
                mcap = float(mcap_lookup.get(sym) or 0.0)
                if rets is not None and not rets.empty:
                    live_fetch_ok_symbols.append(sym)
                return sym, rets, mcap
            except asyncio.CancelledError:
                raise
            except (asyncio.TimeoutError, DataSourceError) as exc:
                LOG.warning("BLAK live fetch failed for %s: %s", sym, exc)
                live_fetch_errors.append(f"{sym}: {type(exc).__name__}: {exc}")
                return sym, pd.Series(dtype=float), float(mcap_lookup.get(sym) or 0.0)
            except Exception as exc:  # noqa: BLE001
                # Last-resort catch for unexpected provider quirks (httpx
                # transport errors, yfinance JSONDecode, etc). Still surface
                # the message so the response is honest about what failed.
                LOG.warning("BLAK live fetch unexpected error for %s: %s", sym, exc)
                live_fetch_errors.append(f"{sym}: {type(exc).__name__}: {exc}")
                return sym, pd.Series(dtype=float), float(mcap_lookup.get(sym) or 0.0)
        if live and self.deps.yfinance:
            results = await asyncio.gather(*(_ret(s) for s in symbols))
            # Audit Q3 #7: pairwise covariance for mixed universes.
            df = align_return_series(
                ((s, r) for s, r, _ in results), policy="pairwise"
            )
        else:
            results = [(s, pd.Series(dtype=float), 1.0) for s in symbols]
            df = pd.DataFrame()
        used_synthetic = False
        if df.shape[0] < 10:
            df = _template_returns(symbols, days)
            # Keep the resolved mcap lookup; we still want real weights even
            # when the return series falls back to the deterministic template.
            results = [(s, pd.Series(dtype=float), float(mcap_lookup.get(s, 0.0))) for s in symbols]
            used_synthetic = True
            # B4: be honest about the source. Only flag synthetic when we
            # actually fell back; partial-success live runs keep yfinance.
            sources = ["synthetic_fallback"]
        else:
            sources = ["yfinance"] if live else ["computed_return_model"]
        cov = df.cov().values * 252
        cols = list(df.columns)
        mcaps = np.array([next((m for s, _, m in results if s == c), 0.0) for c in cols])
        if mcaps.sum() <= 0:
            mcaps = np.ones(len(cols))
            mcap_data_state = "approximate"
        w_mkt = mcaps / mcaps.sum()
        pi = implied_returns(cov, w_mkt, delta=delta)
        # Build P / Q from views.
        # Audit Q3 #23 — `view_type` explicit:
        #   * "spread"   (default): legacy behaviour, row sums to 0
        #                (relative view, "long X over short Y").
        #   * "absolute": each long/short asset gets ITS OWN row; row sum
        #                is +1 (long) or -1 (short). Use for "I expect X
        #                to return 5%" (not "X minus Y").
        # Each view dict accepts a `view_type` override; without it we use
        # the global `params.get("view_type")` or fall back to "spread"
        # for backward compatibility.
        global_view_type = (params.get("view_type") or "spread").lower()
        P_rows: list[list[float]] = []
        Q: list[float] = []
        for v in views:
            vt = (v.get("view_type") or global_view_type).lower()
            longs = v.get("long", []) or []
            shorts = v.get("short", []) or []
            expected = float(v.get("expected", 0.05))
            if vt == "absolute":
                # One row per asset.
                for s in longs:
                    if s in cols:
                        row = [0.0] * len(cols)
                        row[cols.index(s)] = 1.0
                        P_rows.append(row)
                        Q.append(expected)
                for s in shorts:
                    if s in cols:
                        row = [0.0] * len(cols)
                        row[cols.index(s)] = -1.0
                        P_rows.append(row)
                        Q.append(expected)
            else:
                row = [0.0] * len(cols)
                for s in longs:
                    if s in cols:
                        row[cols.index(s)] = 1.0 / max(len(longs), 1)
                for s in shorts:
                    if s in cols:
                        row[cols.index(s)] = -1.0 / max(len(shorts), 1)
                if any(x != 0 for x in row):
                    P_rows.append(row)
                    Q.append(expected)
        P = np.asarray(P_rows) if P_rows else None
        Qv = np.asarray(Q) if Q else None
        pi_bl, sigma_bl = posterior(cov, w_mkt, P, Qv, delta=delta, tau=tau)
        w_opt = implied_optimal_weights(pi_bl, sigma_bl, delta=delta)
        rows = [
            {
                "symbol": sym,
                "market_weight": float(w_mkt[idx]),
                "prior_return": float(pi[idx]),
                "posterior_return": float(pi_bl[idx]),
                "optimal_weight": float(w_opt[idx]),
                "view_active": any(row[idx] != 0 for row in P_rows),
            }
            for idx, sym in enumerate(cols)
        ]
        # Surface mcap provenance alongside the existing return-source mix.
        for src in mcap_sources:
            if src not in sources:
                sources.append(src)
        warnings: list[str] = []
        if mcap_data_state == "approximate":
            warnings.append(
                "market_weight set to equal-weight prior; real market cap unavailable"
            )
        if used_synthetic and live:
            warnings.append(
                "live return fetch produced fewer than 10 aligned rows; "
                "synthetic deterministic returns used"
            )
        if live and live_fetch_errors:
            warnings.append(
                f"{len(live_fetch_errors)} live fetch error(s); see live_fetch_errors for details"
            )
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "status": "ok",
                "symbols": cols,
                "rows": rows,
                "market_weights": dict(zip(cols, w_mkt.tolist())),
                "implied_returns_prior": dict(zip(cols, pi.tolist())),
                "posterior_returns": dict(zip(cols, pi_bl.tolist())),
                "implied_optimal_weights": dict(zip(cols, w_opt.tolist())),
                "market_cap_data_state": mcap_data_state,
                # B4 surfaced fields so the UI can flag the synthetic fallback.
                "live_fetch_errors": list(live_fetch_errors),
                "live_fetch_ok_symbols": sorted(set(live_fetch_ok_symbols)),
                "return_data_state": (
                    "synthetic_fallback" if used_synthetic
                    else ("live" if live else "computed")
                ),
                "partial_live": bool(live and live_fetch_ok_symbols and used_synthetic),
                "delta": delta, "tau": tau,
                "n_views": len(P_rows),
                "samples": int(df.shape[0]),
                "summary": {
                    "symbols": len(cols),
                    "n_views": len(P_rows),
                    "samples": int(df.shape[0]),
                    "tau": tau,
                    "delta": delta,
                    "market_cap_data_state": mcap_data_state,
                },
                "methodology": (
                    "Black-Litterman starts with market-cap implied equilibrium returns pi = delta * covariance * market_weights, "
                    "then blends optional investor views through posterior returns using tau-scaled covariance."
                ),
                "field_dictionary": {
                    "market_weight": "Market-cap weight used as the prior portfolio (circulating supply x price; equal-weight fallback when unavailable).",
                    "prior_return": "Implied equilibrium return before applying views.",
                    "posterior_return": "Black-Litterman expected return after blending views.",
                    "optimal_weight": "Mean-variance implied weight from posterior return and covariance.",
                    "view_active": "Whether the symbol participates in at least one submitted view row.",
                    "market_cap_data_state": "'real' when sourced from a price-provider, 'approximate' when the equal-weight fallback fires.",
                },
            },
            sources=sources,
            warnings=warnings,
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _looks_like_crypto(symbol: str) -> bool:
    upper = str(symbol or "").upper()
    return (
        upper.endswith(("USDT", "USDC", "BUSD", "DAI"))
        or upper in {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "MATIC", "LINK", "TRX", "TON", "SHIB", "LTC", "BCH", "UNI", "ATOM"}
    )


async def _market_cap_from_coingecko(deps: Any, symbol: str) -> float:
    """Best-effort circulating-supply * price from the CoinGecko adapter.

    Returns 0.0 on any failure path so the caller can fall back. The adapter
    is the same one bundled with showMe's DES pane; if it is not wired into
    the FunctionDeps container we silently skip.
    """
    coingecko = getattr(deps, "coingecko", None)
    if coingecko is None:
        return 0.0
    try:
        if hasattr(coingecko, "quote"):
            payload = await coingecko.quote(symbol)
        else:
            return 0.0
    except Exception:
        return 0.0
    if not isinstance(payload, dict):
        return 0.0
    mcap = payload.get("usd_market_cap") or payload.get("market_cap")
    try:
        return float(mcap or 0.0)
    except (TypeError, ValueError):
        return 0.0


async def _market_cap_from_yfinance(deps: Any, symbol: str) -> float:
    """REFDATA pull for equity-style symbols. Returns 0.0 on any failure."""
    yfin = getattr(deps, "yfinance", None)
    if yfin is None:
        return 0.0
    try:
        inst = Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)
        if getattr(deps, "symbol_registry", None):
            r = await deps.symbol_registry.resolve(symbol)
            if r:
                inst = r
        meta = await asyncio.wait_for(
            yfin.fetch(DataRequest(kind=DataKind.REFDATA, instrument=inst)),
            timeout=4,
        )
    except Exception:
        return 0.0
    mcap = getattr(meta, "market_cap", None)
    try:
        return float(mcap or 0.0)
    except (TypeError, ValueError):
        return 0.0


async def _resolve_market_caps(
    deps: Any,
    symbols: list[str],
    overrides: dict[str, Any] | None,
) -> tuple[dict[str, float], str, list[str]]:
    """Resolve real market caps for the universe.

    Returns ``(symbol → mcap, data_state, extra_sources)`` where data_state is
    ``"real"`` when at least one symbol resolved through a provider and
    ``"approximate"`` when the equal-weight fallback will need to fire.
    Overrides are honoured first so callers can inject deterministic values
    in tests.
    """
    lookup: dict[str, float] = {}
    extra_sources: list[str] = []
    overrides = overrides or {}
    for sym in symbols:
        if sym in overrides:
            try:
                value = float(overrides[sym])
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                lookup[sym] = value
    if lookup and len(lookup) == len(symbols):
        return lookup, "real", extra_sources

    async def _resolve(sym: str) -> tuple[str, float, str | None]:
        if sym in lookup:
            return sym, lookup[sym], None
        if _looks_like_crypto(sym):
            mcap = await _market_cap_from_coingecko(deps, sym)
            if mcap > 0:
                return sym, mcap, "coingecko"
        mcap = await _market_cap_from_yfinance(deps, sym)
        if mcap > 0:
            return sym, mcap, "yfinance_refdata"
        return sym, 0.0, None

    results = await asyncio.gather(*(_resolve(s) for s in symbols))
    for sym, mcap, src in results:
        if mcap > 0:
            lookup[sym] = mcap
            if src and src not in extra_sources:
                extra_sources.append(src)
    data_state = "real" if lookup else "approximate"
    return lookup, data_state, extra_sources
