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


_PRIOR_COV_ESTIMATORS = ("sample_cov", "ledoit_wolf", "exp_cov")
_EXP_COV_SPAN = 180  # EWMA span in trading days (PyPortfolioOpt convention)


def _ledoit_wolf_covariance(x: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit & Wolf (2004) shrinkage toward the scaled identity mu * I.

    ``x`` holds one row per period and one column per asset (daily returns).
    Returns ``(covariance, delta)`` where ``covariance = (1 - delta) * S + delta * mu * I``
    on the unbiased (ddof=1) scale and ``delta`` in [0, 1] is the shrinkage
    intensity. Math: S is the 1/T sample covariance, mu = tr(S)/N,
    d^2 = ||S - mu I||_F^2, b^2 = min(d^2, (1/T^2) sum_t ||x_t x_t' - S||_F^2),
    delta = b^2 / d^2.
    """
    t, n = x.shape
    xc = x - x.mean(axis=0)
    s_mle = xc.T @ xc / t
    mu = float(np.trace(s_mle)) / n
    d2 = float(np.sum((s_mle - mu * np.eye(n)) ** 2))
    if d2 <= 0.0:
        delta = 0.0
    else:
        norms_sq = np.sum(xc ** 2, axis=1)
        b2 = (float(np.sum(norms_sq ** 2)) - t * float(np.sum(s_mle ** 2))) / (t ** 2)
        delta = min(max(min(b2, d2) / d2, 0.0), 1.0)
    scale = t / (t - 1)  # MLE -> unbiased, same scale as DataFrame.cov()
    shrunk = (1.0 - delta) * s_mle + delta * mu * np.eye(n)
    return shrunk * scale, delta


def _exp_weighted_covariance(x: np.ndarray, span: int) -> np.ndarray:
    """EWMA covariance with reliability-weight correction (unbiased scale)."""
    t = x.shape[0]
    alpha = 2.0 / (span + 1.0)
    w = (1.0 - alpha) ** np.arange(t - 1, -1, -1, dtype=float)
    w = w / w.sum()
    mean = w @ x
    xc = x - mean
    cov = (xc * w[:, None]).T @ xc
    return cov / (1.0 - float(np.sum(w ** 2)))


def _prior_covariance(df: pd.DataFrame, estimator: str) -> tuple[np.ndarray, float | None]:
    """Daily-scale covariance for the requested estimator plus LW intensity."""
    if estimator == "sample_cov":
        return df.cov().values, None
    clean = df.dropna()
    x = clean.values.astype(float)
    if estimator == "ledoit_wolf":
        cov, delta = _ledoit_wolf_covariance(x)
        return cov, delta
    return _exp_weighted_covariance(x, _EXP_COV_SPAN), None


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
        # BLAK#3: the prior covariance estimator is an honest input. An unknown
        # value is refused explicitly instead of silently using the sample cov.
        estimator = str(params.get("prior_covariance") or "ledoit_wolf").strip().lower()
        if estimator not in _PRIOR_COV_ESTIMATORS:
            return FunctionResult(
                code=self.code, instrument=None,
                data={
                    "status": "input_error",
                    "reason": (f"prior_covariance {estimator!r} is not supported; "
                               f"use one of {', '.join(_PRIOR_COV_ESTIMATORS)}"),
                    "next_actions": ["Choose sample_cov, ledoit_wolf or exp_cov."],
                },
                warnings=[f"unsupported prior_covariance: {estimator}"],
            )
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
        mcap_lookup, mcap_data_state, mcap_sources, mcap_proxied = (
            await _resolve_market_caps_detail(self.deps, symbols, market_caps)
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
        cov_daily, shrinkage_delta = _prior_covariance(df, estimator)
        cov = cov_daily * 252
        cols = list(df.columns)
        mcaps = np.array([next((m for s, _, m in results if s == c), 0.0) for c in cols])
        # BLAK#2: partial coverage used to keep the "real" label while the
        # unresolved names got weight 0. Any requested name without a market
        # value now sends the whole prior to the labelled equal-weight fallback.
        mcap_resolved = [s for s in symbols if float(mcap_lookup.get(s) or 0.0) > 0]
        mcap_missing = [s for s in symbols if s not in mcap_resolved]
        mcap_partial = mcap_data_state == "partial"
        if mcap_partial or mcaps.sum() <= 0:
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
        if mcap_partial:
            warnings.append(
                f"market cap resolved for {len(mcap_resolved)}/{len(symbols)} symbols; "
                f"no market value for {', '.join(mcap_missing)}; equal-weight prior used "
                "for the whole universe"
            )
        elif mcap_data_state == "approximate":
            warnings.append(
                "market_weight set to equal-weight prior; real market cap unavailable"
            )
        elif mcap_data_state == "proxy":
            warnings.append(
                "fund AUM (totalAssets) used as market-value proxy for "
                + ", ".join(mcap_proxied)
                + "; not a market capitalization"
            )
        excluded_no_returns = [s for s in symbols if s not in cols]
        if excluded_no_returns:
            warnings.append(
                "symbols excluded from the prior (no aligned return rows): "
                + ", ".join(excluded_no_returns)
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
                "market_cap_coverage": {
                    "resolved": len(mcap_resolved),
                    "requested": len(symbols),
                    "missing": mcap_missing,
                },
                "prior_covariance_estimator": estimator,
                "shrinkage_intensity": shrinkage_delta,
                "prior_covariance": {
                    a: {b: float(cov[i][j]) for j, b in enumerate(cols)}
                    for i, a in enumerate(cols)
                },
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
                    "market_cap_data_state": "'real' when every requested symbol has a market value, 'partial' or 'approximate' when the equal-weight fallback fires.",
                    "prior_covariance_estimator": "Estimator applied to the return series: sample_cov, ledoit_wolf (Ledoit-Wolf 2004 shrinkage toward mu*I) or exp_cov (EWMA, span 180 days).",
                    "shrinkage_intensity": "Ledoit-Wolf weight on the mu*I target (0 to 1); null for sample_cov and exp_cov.",
                    "prior_covariance": "Annualized prior covariance matrix actually used for pi and the posterior.",
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


def _positive_float(value: Any) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


async def _market_cap_from_yfinance(deps: Any, symbol: str) -> tuple[float, str | None]:
    """REFDATA pull for equity-style symbols.

    Returns ``(value, source)``; ``(0.0, None)`` on any failure. Funds carry no
    ``marketCap`` in yfinance, so for ETF / mutual-fund quote types the total
    net assets (``totalAssets``) is used as a labelled market-value proxy. For
    operating companies ``totalAssets`` is balance-sheet assets and is never
    used as a market cap.
    """
    yfin = getattr(deps, "yfinance", None)
    if yfin is None:
        return 0.0, None
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
        return 0.0, None
    mcap = _positive_float(getattr(meta, "market_cap", None))
    if mcap > 0:
        return mcap, "yfinance_refdata"
    extras = getattr(meta, "extras", None)
    raw = (extras.get("raw") or {}) if isinstance(extras, dict) else {}
    if str(raw.get("quoteType") or "").upper() in {"ETF", "MUTUALFUND"}:
        aum = _positive_float(raw.get("totalAssets"))
        if aum > 0:
            return aum, "yfinance_fund_aum"
    return 0.0, None


async def _resolve_market_caps(
    deps: Any,
    symbols: list[str],
    overrides: dict[str, Any] | None,
) -> tuple[dict[str, float], str, list[str]]:
    """Resolve market caps; see ``_resolve_market_caps_detail``."""
    lookup, state, sources, _proxied = await _resolve_market_caps_detail(
        deps, symbols, overrides
    )
    return lookup, state, sources


async def _resolve_market_caps_detail(
    deps: Any,
    symbols: list[str],
    overrides: dict[str, Any] | None,
) -> tuple[dict[str, float], str, list[str], list[str]]:
    """Resolve real market caps for the universe.

    Returns ``(symbol → mcap, data_state, extra_sources)`` where data_state is
    ``"real"`` when every symbol resolved to a market cap, ``"proxy"`` when
    every symbol resolved but at least one value is ETF / fund AUM (a proxy,
    not a market cap), ``"partial"`` when only some symbols resolved and
    ``"approximate"`` when none did (the equal-weight fallback fires).
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
        return lookup, "real", extra_sources, []

    async def _resolve(sym: str) -> tuple[str, float, str | None]:
        if sym in lookup:
            return sym, lookup[sym], None
        if _looks_like_crypto(sym):
            mcap = await _market_cap_from_coingecko(deps, sym)
            if mcap > 0:
                return sym, mcap, "coingecko"
        mcap, src = await _market_cap_from_yfinance(deps, sym)
        if mcap > 0:
            return sym, mcap, src
        return sym, 0.0, None

    results = await asyncio.gather(*(_resolve(s) for s in symbols))
    proxied: list[str] = []
    for sym, mcap, src in results:
        if mcap > 0:
            lookup[sym] = mcap
            if src and src not in extra_sources:
                extra_sources.append(src)
            if src == "yfinance_fund_aum":
                proxied.append(sym)
    resolved = sum(1 for s in symbols if lookup.get(s, 0.0) > 0)
    if symbols and resolved == len(symbols):
        # Fund AUM (ETF / mutual-fund totalAssets) is a proxy for market value,
        # never a market cap, so it must not carry the "real" label.
        data_state = "proxy" if proxied else "real"
    elif resolved:
        data_state = "partial"
    else:
        data_state = "approximate"
    return lookup, data_state, extra_sources, proxied
