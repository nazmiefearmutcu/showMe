"""RPAR — Risk parity portfolio construction (ERC weights)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.return_series import align_return_series, close_to_daily_returns
from showme.engine.services.risk_parity import (
    equal_risk_contribution,
    naive_inverse_vol,
    risk_contributions,
)


_FIAT = frozenset(
    {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK", "CNY", "TRY", "MXN", "BRL", "INR", "KRW", "ZAR"}
)


def _yahoo_symbol(sym: str) -> str:
    """Map a canonical desk symbol to its Yahoo ticker.

    AAPL -> AAPL, GC=F -> GC=F (already Yahoo), BTCUSDT/BTCUSD -> BTC-USD,
    EURUSD -> EURUSD=X.
    """
    s = (sym or "").strip().upper()
    if not s or "=" in s or s.startswith("^"):
        return s
    for quote in ("USDT", "USDC", "USD"):
        if len(s) > len(quote) and s.endswith(quote):
            base = s[: -len(quote)]
            if base.isalpha() and 2 <= len(base) <= 10:
                return f"{base}-USD"
    if len(s) == 6 and s.isalpha() and s[:3] in _FIAT and s[3:] in _FIAT:
        return f"{s}=X"
    return s


async def _yahoo_daily_returns(symbol: str, days: int) -> pd.Series:
    """Keyless Yahoo chart-API daily returns (the RPAR history fallback).

    Uses the same tier the price panes are built on (``fetch_yahoo_bars``),
    so a yfinance-adapter outage can no longer blank the whole allocation.
    """
    try:
        from showme.server_routes import bars as bars_route

        yahoo_range = "1y" if days <= 400 else "2y" if days <= 800 else "5y"
        rows = await bars_route.fetch_yahoo_bars(_yahoo_symbol(symbol), "1d", yahoo_range)
        if not rows:
            return pd.Series(dtype=float)
        closes = pd.Series(
            [float(row["c"]) for row in rows if row.get("c") is not None],
            index=pd.to_datetime(
                [int(row["t"]) for row in rows if row.get("c") is not None],
                unit="ms",
            ).normalize(),
        ).sort_index()
        return closes.pct_change().dropna()
    except Exception:  # noqa: BLE001 - outage degrades to the caller's template
        return pd.Series(dtype=float)


def _template_returns(symbols: list[str], days: int) -> pd.DataFrame:
    periods = max(60, min(days, 504))
    index = pd.date_range(end=datetime.now(timezone.utc).date(), periods=periods, freq="B")
    periods = len(index)
    t = np.arange(periods, dtype=float)
    rows = {}
    for i, sym in enumerate(symbols):
        rows[sym] = 0.0002 + i * 0.00002 + np.cos((t + i * 5) / (13 + i)) * (0.005 + i * 0.0008)
    return pd.DataFrame(rows, index=index)


_COVARIANCE_MODELS = ("sample_cov", "ledoit_wolf", "exp_cov", "oracle_approximating")
_DEFAULT_COVARIANCE_MODEL = "ledoit_wolf"  # manifest default
_DEFAULT_RISK_TARGET = 0.10  # manifest default, annualized decimal
_DEFAULT_METHOD = "erc"  # equal-risk-contribution parity, the function's name and manifest intent
_EXP_COV_HALFLIFE_DAYS = 63  # about one quarter of trading days
_MIN_COMPLETE_ROWS = 10
# lookback_window manifest options mapped to calendar days; days (default 504) wins when sent.
_LOOKBACK_DAYS = {"90d": 90, "180d": 180, "1y": 365, "2y": 730, "5y": 1825}
_DEFAULT_DAYS = 504
# The history fetch is daily closes only; other cadences are an explicit input_error.
_DAILY_FREQUENCIES = frozenset({"1d", "daily"})
# Per-symbol history timeout, and one overall budget for the whole live fetch.
# The budget stays under the 14 s route timeout so an honest provider_unavailable
# state is returned instead of the route's generic timeout envelope.
_SYMBOL_TIMEOUT_SECONDS = 8.0
_FETCH_BUDGET_SECONDS = 12.0


def _shrink_to_identity(sample: np.ndarray, alpha: float) -> np.ndarray:
    p = sample.shape[0]
    mu = float(np.trace(sample)) / p
    return (1.0 - alpha) * sample + alpha * mu * np.eye(p)


def _ledoit_wolf(centred: np.ndarray) -> np.ndarray:
    """Ledoit & Wolf (2004) shrinkage of the sample covariance toward a scaled identity."""
    n, p = centred.shape
    sample = centred.T @ centred / n
    mu = float(np.trace(sample)) / p
    delta2 = float(np.sum((sample - mu * np.eye(p)) ** 2))
    if delta2 <= 0.0:
        return sample
    sq_norm = np.sum(centred * centred, axis=1)
    quad = np.sum((centred @ sample) * centred, axis=1)
    beta_bar = float(np.sum(sq_norm**2) - 2.0 * np.sum(quad) + n * np.sum(sample * sample)) / (n * n)
    return _shrink_to_identity(sample, min(beta_bar, delta2) / delta2)


def _oracle_approximating(centred: np.ndarray) -> np.ndarray:
    """Chen, Wiesel, Eldar & Hero (2010) oracle approximating shrinkage toward a scaled identity."""
    n, p = centred.shape
    sample = centred.T @ centred / n
    trace = float(np.trace(sample))
    trace_sq = float(np.sum(sample * sample))
    numerator = (1.0 - 2.0 / p) * trace_sq + trace * trace
    denominator = (n + 1.0 - 2.0 / p) * (trace_sq - trace * trace / p)
    rho = 1.0 if denominator <= 0.0 else min(1.0, max(0.0, numerator / denominator))
    return _shrink_to_identity(sample, rho)


def _exp_weighted(raw: np.ndarray, halflife: int) -> np.ndarray:
    t = raw.shape[0]
    decay = 0.5 ** (1.0 / halflife)
    weights = decay ** np.arange(t - 1, -1, -1, dtype=float)
    weights /= weights.sum()
    centred = raw - weights @ raw
    return (centred * weights[:, None]).T @ centred


def estimate_covariance(returns: pd.DataFrame, model: str) -> tuple[np.ndarray, str, list[str]]:
    """Daily covariance for the requested estimator.

    Returns ``(matrix, effective_model, notes)``. Shrinkage estimators use complete
    rows; too few of them, or an unknown model name, falls back to sample_cov and
    says so in ``notes``.
    """
    notes: list[str] = []
    requested = (model or _DEFAULT_COVARIANCE_MODEL).lower()
    if requested not in _COVARIANCE_MODELS:
        notes.append(f"Unknown covariance_model {requested!r}; used sample_cov.")
        requested = "sample_cov"
    if requested == "sample_cov":
        return returns.cov().to_numpy(dtype=float), "sample_cov", notes
    complete = returns.dropna().to_numpy(dtype=float)
    if complete.shape[0] < _MIN_COMPLETE_ROWS:
        notes.append(f"{requested} needs {_MIN_COMPLETE_ROWS}+ complete return rows; used sample_cov.")
        return returns.cov().to_numpy(dtype=float), "sample_cov", notes
    if requested == "exp_cov":
        return _exp_weighted(complete, _EXP_COV_HALFLIFE_DAYS), requested, notes
    centred = complete - complete.mean(axis=0)
    if requested == "ledoit_wolf":
        return _ledoit_wolf(centred), requested, notes
    return _oracle_approximating(centred), requested, notes


def _scale_to_risk_target(weights: np.ndarray, cov: np.ndarray, risk_target: float) -> tuple[float, str | None]:
    """Scale factor that makes the portfolio volatility equal risk_target."""
    port_vol = float(np.sqrt(max(float(weights @ cov @ weights), 0.0)))
    if port_vol <= 1e-12:
        return 1.0, "Portfolio volatility is zero; weights were not scaled to risk_target."
    return risk_target / port_vol, None


@FunctionRegistry.register
class RPARFunction(BaseFunction):
    code = "RPAR"
    name = "Risk Parity (ERC)"
    category = "portfolio"
    description = "Compute equal-risk-contribution weights for given universe."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # The manifest names the universe input ``universe``; the pane sends
        # ``symbols``. Both are accepted (``symbols`` wins). Without a universe the
        # call is an explicit needs_input state, never a hard-coded basket.
        symbols = params.get("symbols") or params.get("universe") or []
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
        symbols = [str(s).strip() for s in symbols if str(s).strip()]
        if not symbols:
            symbol = params.get("symbol") or (instrument.symbol if instrument else None)
            symbols = [str(symbol).strip()] if symbol else []
        days, lookback_error = _resolve_days(params)
        lookback_window = params.get("lookback_window")
        frequency = params.get("frequency")
        target = params.get("target")  # optional list of weights
        method = (params.get("method") or _DEFAULT_METHOD).lower()
        covariance_model = str(params.get("covariance_model") or _DEFAULT_COVARIANCE_MODEL).lower()
        raw_risk_target = params.get("risk_target")
        try:
            risk_target = _DEFAULT_RISK_TARGET if raw_risk_target is None else float(raw_risk_target)
        except (TypeError, ValueError):
            risk_target = float("nan")
        if not np.isfinite(risk_target) or risk_target <= 0.0:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_error",
                    "reason": f"risk_target must be a positive annualized volatility decimal, got {raw_risk_target!r}.",
                    "next_actions": ["Pass risk_target as a decimal such as 0.10 for 10% annualized volatility."],
                },
                sources=[],
                warnings=["RPAR was not computed: invalid risk_target."],
            )
        if lookback_error:
            return _input_error(
                lookback_error,
                ["Pass lookback_window as one of 90d, 180d, 1Y, 2Y, 5Y, or pass days as a calendar-day count."],
            )
        if frequency not in (None, "") and str(frequency).strip().lower() not in _DAILY_FREQUENCIES:
            return _input_error(
                f"frequency {frequency!r} is not supported: RPAR fetches daily closes only.",
                ["Pass frequency=1d or omit it."],
            )
        if not symbols:
            return _unavailable_allocation(
                [],
                risk_target,
                covariance_model,
                status="needs_input",
                reason="No universe was supplied, so there is nothing to allocate across.",
                next_actions=["Pass symbols (or universe) as a comma-separated list of tickers, e.g. AAPL,MSFT,GLD."],
                fallback_reason="universe_missing",
            )
        budget, budget_error = _parse_risk_budget(params.get("risk_budget"), symbols)
        if budget_error:
            return _input_error(
                budget_error,
                ["Pass risk_budget with one positive share per universe symbol, e.g. AAPL:0.5,MSFT:0.5."],
            )
        # S12 BugHunt: default flipped to LIVE when yfinance is available.
        # Previous behavior silently returned a deterministic template (with
        # source `risk_parity_model`) on every call that did not explicitly
        # set `live_risk=true` or `method=erc`. Callers can still opt back
        # into the fast template by passing `model=true`.
        force_model = _truthy(params.get("model"))
        live_param = params.get("live_risk")
        if live_param is None:
            live_param = params.get("live")
        if live_param is None:
            live = bool(self.deps.yfinance) and not force_model
        else:
            live = _truthy(live_param)
        # Data policy: without measured return history there are no weights. The
        # declared controls are echoed back so the caller can see what was requested.
        if force_model:
            return _unavailable_allocation(
                symbols,
                risk_target,
                covariance_model,
                status="needs_input",
                reason="model=true requests a reference template, which has no measured volatilities or weights.",
                next_actions=[
                    "Remove model=true to build weights from return history.",
                    "Pass live_risk=true with a configured yfinance provider.",
                ],
                fallback_reason="model_requested",
            )
        if not live or not self.deps.yfinance:
            no_provider = not self.deps.yfinance
            return _unavailable_allocation(
                symbols,
                risk_target,
                covariance_model,
                status="provider_unavailable" if no_provider else "needs_input",
                reason=(
                    "yfinance is not configured, so no return history is available."
                    if no_provider
                    else "live_risk=false: no return history was requested."
                ),
                next_actions=(
                    ["Configure the yfinance provider, then retry with live_risk=true."]
                    if no_provider
                    else ["Pass live_risk=true to build weights from return history."]
                ),
                fallback_reason="yfinance_unavailable" if no_provider else "live_disabled",
            )
        sources = ["yfinance"]
        async def _ret(sym: str) -> tuple[str, pd.Series]:
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
                    timeout=_SYMBOL_TIMEOUT_SECONDS,
                )
                series = close_to_daily_returns(df)
                if series.dropna().shape[0] < 10:
                    # Owner (2026-09-16): "bu fonksiyon bir daha hata
                    # vermeyecek" - the yfinance adapter can come back empty
                    # for mapped crypto/FX pairs (BTCUSDT/EURUSD). Fall back
                    # to the keyless Yahoo chart API (same tier the price
                    # panes use) before ever degrading to the template.
                    series = await _yahoo_daily_returns(sym, days)
                return sym, series
            except Exception:
                try:
                    return sym, await _yahoo_daily_returns(sym, days)
                except Exception:  # noqa: BLE001
                    return sym, pd.Series(dtype=float)
        try:
            rs = await asyncio.wait_for(
                asyncio.gather(*(_ret(s) for s in symbols)),
                timeout=_FETCH_BUDGET_SECONDS,
            )
        except (asyncio.TimeoutError, TimeoutError):
            # Per-symbol timeouts stack with the Yahoo fallback; one overall budget
            # keeps the call bounded and reports the state explicitly.
            return _unavailable_allocation(
                symbols,
                risk_target,
                covariance_model,
                status="provider_unavailable",
                reason=(
                    f"Return history for {len(symbols)} symbol(s) did not arrive within the "
                    f"{_FETCH_BUDGET_SECONDS:.0f}s fetch budget; no weights were built."
                ),
                next_actions=["Retry the call, or use fewer symbols; the history providers were slow."],
                fallback_reason="fetch_budget_exceeded",
            )
        # Audit Q3 #7: pairwise policy keeps crypto+equity covariance
        # honest. Legacy intersection-only dropna threw away 70%+ of
        # rows for mixed universes and tilted weights to crypto.
        df = align_return_series(rs, policy="pairwise")
        if df.shape[0] < 10:
            # No synthetic return series: that would turn a cosine into a risk model.
            return _unavailable_allocation(
                symbols,
                risk_target,
                covariance_model,
                status="provider_unavailable",
                reason=(
                    "yfinance and the Yahoo fallback returned insufficient return history "
                    f"(fewer than 10 aligned rows, got {int(df.shape[0])}); no weights were built."
                ),
                next_actions=["Choose symbols with a shared trading calendar and longer history, or retry the provider."],
                fallback_reason="yfinance_returned_insufficient_history",
            )
        cov_daily, cov_effective, cov_notes = estimate_covariance(df, covariance_model)
        cov = cov_daily * 252
        control_warnings: list[str] = []
        budget_applied = budget is not None and method != "inverse_vol"
        if method == "inverse_vol":
            w = naive_inverse_vol(cov)
            info = {"method": "inverse_vol"}
            if budget is not None:
                control_warnings.append("risk_budget is applied only to method=erc; inverse_vol ignored it.")
        else:
            tgt = None
            if budget is not None:
                cols = [str(c) for c in df.columns]
                uncovered = [c for c in cols if c.upper() not in budget]
                if uncovered:
                    return _input_error(
                        f"risk_budget does not cover aligned column(s) {', '.join(uncovered)}.",
                        ["Pass one risk_budget share per symbol that has usable history."],
                    )
                tgt = np.asarray([budget[c.upper()] for c in cols], dtype=float)
                dropped = [s for s in symbols if s.upper() not in {c.upper() for c in cols}]
                if dropped:
                    control_warnings.append(
                        "risk_budget was renormalized over symbols with usable history; "
                        f"dropped {', '.join(dropped)}."
                    )
            elif target:
                tgt = np.asarray(target, dtype=float)
            w, info = equal_risk_contribution(
                cov,
                target=tgt,
                max_iter=int(params.get("max_iter", 500)),
            )
            info["method"] = "erc"
        scale, scale_warning = _scale_to_risk_target(w, cov, risk_target)
        w = w * scale
        info = {**info, "risk_target": risk_target, "scale_factor": scale}
        rc = risk_contributions(w, cov)
        rows = [
            {
                "symbol": symbol,
                "weight": float(w[i]),
                "weight_pct": float(w[i] * 100),
                "risk_contribution_pct": float(rc["risk_contributions_pct"][i] * 100),
                "annualized_vol": float(np.sqrt(cov[i, i])),
                "method": info.get("method"),
            }
            for i, symbol in enumerate(df.columns)
        ]
        warnings: list[str] = list(cov_notes) + control_warnings
        if scale_warning:
            warnings.append(scale_warning)
        if info.get("converged") is False:
            warnings.append(
                f"RPAR ERC did not converge after {info.get('iterations')} iterations "
                f"(max risk-share gap {float(info.get('residual', float('nan'))):.4g}); "
                "the weights are not equal-risk and should not be used as ERC."
            )
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "symbols": list(df.columns),
                "weights": dict(zip(df.columns, w.tolist())),
                "portfolio_vol": rc["portfolio_vol"],
                "risk_contributions_pct": dict(zip(df.columns, rc["risk_contributions_pct"])),
                "samples": int(df.shape[0]),
                "info": info,
                "rows": rows,
                "fallback": False,
                "fallback_reason": None,
                "covariance_model": cov_effective,
                "covariance_model_requested": covariance_model,
                "risk_target": risk_target,
                "controls": {
                    "lookback_days": days,
                    "lookback_window_requested": lookback_window,
                    "frequency": "1d",
                    "risk_budget_applied": budget_applied,
                    "paper_mode_requested": params.get("paper_mode"),
                    "paper_mode_effect": "RPAR has no order path; weights are research output in every mode.",
                },
                "gross_exposure": float(w.sum()),
                "summary": {
                    "method": info.get("method"),
                    "symbols": len(rows),
                    "portfolio_vol": rc["portfolio_vol"],
                    "risk_target": risk_target,
                },
                "methodology": (
                    f"Estimate the annualized covariance matrix with {cov_effective} from daily returns. "
                    "ERC mode solves for weights whose risk contributions are equal (or match the target "
                    "shares) with a damped multiplicative fixed-point iteration; inverse-vol mode is a faster "
                    "approximation, not true ERC. Weights are then scaled so portfolio volatility equals "
                    "risk_target, so they sum to gross exposure rather than 1. The lookback is the days "
                    "parameter, or lookback_window (90d, 180d, 1Y, 2Y, 5Y) when days is absent. Frequency is "
                    "daily only. risk_budget sets the ERC risk shares when supplied (inverse_vol ignores it). "
                    "paper_mode is reported only: RPAR has no order path, so its weights are research output "
                    "in every mode."
                ),
                "field_dictionary": {
                    "weight_pct": "Portfolio allocation weight in percent (of the risk-target-scaled book).",
                    "risk_contribution_pct": "Share of total portfolio variance contribution.",
                    "annualized_vol": "Single-asset annualized volatility from the covariance diagonal.",
                    "portfolio_vol": "Annualized portfolio volatility sqrt(w' covariance w); equals risk_target when scaled.",
                    "gross_exposure": "Sum of the scaled weights; above 1 means leverage to reach risk_target.",
                    "covariance_model": "Estimator actually used (may differ from the request when a fallback applied).",
                },
            },
            sources=sources,
            warnings=warnings,
            metadata={"live": True, "fallback": False, "fallback_reason": None},
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_days(params: dict[str, Any]) -> tuple[int, str | None]:
    """Calendar-day history length: explicit days, else the lookback_window mapping, else 504."""
    if params.get("days") is not None:
        return int(params["days"]), None
    lookback = params.get("lookback_window")
    if lookback is None or str(lookback).strip() == "":
        return _DEFAULT_DAYS, None
    key = str(lookback).strip().lower()
    if key not in _LOOKBACK_DAYS:
        return _DEFAULT_DAYS, f"lookback_window {lookback!r} is not one of 90d, 180d, 1Y, 2Y, 5Y."
    return _LOOKBACK_DAYS[key], None


def _parse_risk_budget(raw: Any, symbols: list[str]) -> tuple[dict[str, float] | None, str | None]:
    """Per-symbol risk shares keyed by upper-case symbol; None when no budget was supplied.

    Accepts a mapping ({"AAPL": 0.5}) or a string ("AAPL:0.5,MSFT:0.5"). Every universe
    symbol needs a positive share and no other symbol may appear.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, None
    pairs: list[tuple[str, Any]] = []
    if isinstance(raw, dict):
        pairs = [(str(k), v) for k, v in raw.items()]
    elif isinstance(raw, str):
        for part in raw.split(","):
            if not part.strip():
                continue
            sep = ":" if ":" in part else "=" if "=" in part else None
            if sep is None:
                return None, f"risk_budget entry {part.strip()!r} must look like SYMBOL:share."
            key, _, value = part.partition(sep)
            pairs.append((key.strip(), value.strip()))
    else:
        return None, 'risk_budget must be a SYMBOL-to-share mapping such as {"AAPL": 0.5, "MSFT": 0.5}.'
    budget: dict[str, float] = {}
    for key, value in pairs:
        try:
            share = float(value)
        except (TypeError, ValueError):
            return None, f"risk_budget share for {key!r} is not a number: {value!r}."
        if not np.isfinite(share) or share <= 0.0:
            return None, f"risk_budget share for {key!r} must be a positive number, got {value!r}."
        budget[key.strip().upper()] = share
    wanted = {str(s).strip().upper() for s in symbols}
    missing = sorted(wanted - set(budget))
    extra = sorted(set(budget) - wanted)
    if missing:
        return None, f"risk_budget has no share for {', '.join(missing)}."
    if extra:
        return None, f"risk_budget names symbols outside the universe: {', '.join(extra)}."
    return budget, None


def _input_error(reason: str, next_actions: list[str]) -> FunctionResult:
    """Explicit caller-input state for RPAR: nothing was fetched and no weights exist."""
    return FunctionResult(
        code="RPAR",
        instrument=None,
        data={
            "status": "input_error",
            "reason": reason,
            "next_actions": list(next_actions),
        },
        sources=[],
        warnings=[f"RPAR was not computed: {reason}"],
    )


def _unavailable_allocation(
    symbols: list[str],
    risk_target: float,
    covariance_model: str,
    *,
    status: str,
    reason: str,
    next_actions: list[str],
    fallback_reason: str,
) -> FunctionResult:
    """Explicit missing-data state for RPAR: no weights, no volatilities, controls echoed."""
    clean = list(dict.fromkeys(str(s) for s in symbols if str(s)))
    return FunctionResult(
        code="RPAR",
        instrument=None,
        data={
            "status": status,
            "reason": reason,
            "next_actions": list(next_actions),
            "symbols": clean,
            "weights": {},
            "portfolio_vol": None,
            "risk_contributions_pct": {},
            "samples": 0,
            "info": {"method": None},
            "rows": [],
            "fallback": True,
            "fallback_reason": fallback_reason,
            "covariance_model": None,
            "covariance_model_requested": covariance_model,
            "risk_target": risk_target,
            "gross_exposure": None,
            "summary": {
                "method": None,
                "symbols": len(clean),
                "portfolio_vol": None,
                "risk_target": risk_target,
            },
            "methodology": (
                "No weights are produced without measured return history. When history exists, RPAR estimates "
                "the annualized covariance from daily returns, solves for equal-risk-contribution weights, and "
                "scales them so portfolio volatility equals risk_target."
            ),
            "field_dictionary": {
                "status": "needs_input or provider_unavailable; reason and next_actions say what is missing.",
                "risk_target": "Requested annualized volatility decimal; applied only when weights exist.",
                "covariance_model_requested": "Estimator requested; no covariance is estimated without returns.",
            },
        },
        sources=[],
        warnings=[reason],
        metadata={"live": False, "fallback": True, "fallback_reason": fallback_reason},
    )
