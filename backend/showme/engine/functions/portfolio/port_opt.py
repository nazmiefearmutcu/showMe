"""PORT_OPT — Markowitz portfolio optimizer (multiple solver modes)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.return_series import align_return_series, close_to_daily_returns
from showme.engine.services.optimizer import (
    efficient_frontier, max_sharpe, min_volatility, risk_parity,
)


_DEFAULT_DAYS = 365 * 3
_MODES = frozenset({"frontier", "all", "max_sharpe", "min_vol", "risk_parity"})
# Manifest objective -> solver mode. Other manifest objectives are not solved here.
_OBJECTIVE_MODES = {"max_sharpe": "max_sharpe", "min_volatility": "min_vol"}
# Manifest window labels -> calendar days.
_WINDOW_DAYS = {"90d": 90, "180d": 180, "1y": 365, "2y": 730, "5y": 1825}
# Declared manifest choices this optimizer really applies. Anything else is
# reported in ``unapplied_inputs`` instead of being silently ignored.
_APPLIED_RISK_MODELS = frozenset({"sample_cov"})
_APPLIED_RETURN_MODELS = frozenset({"mean_historical"})
_APPLIED_FREQUENCIES = frozenset({"1d"})


@FunctionRegistry.register
class PortOptFunction(BaseFunction):
    code = "PORT_OPT"
    name = "Portfolio Optimizer"
    category = "portfolio"
    description = "Markowitz min-vol / max-Sharpe / risk-parity / efficient frontier."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # Fix A7-C3: GET ?symbols=AAPL,MSFT,NVDA arrives as a string and used
        # to iterate character-by-character into ["A","P","S"]. Mirror the
        # guard BLAK/RPAR already implement.
        symbols = params.get("symbols") or params.get("universe") or [
            "SPY", "QQQ", "IWM", "TLT", "GLD", "EFA", "EEM", "VNQ", "DBC",
        ]
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
        allow_short = bool(params.get("allow_short", False))
        live = _truthy(params.get("live_optimization") or params.get("live_returns") or params.get("live"))
        unapplied: list[str] = []

        # --- mode / objective -------------------------------------------------
        objective = params.get("objective")
        if params.get("mode"):
            mode = str(params["mode"]).lower()
            if objective is not None:
                unapplied.append("objective")
        elif objective is not None:
            objective_key = str(objective).lower()
            if objective_key not in _OBJECTIVE_MODES:
                return _input_error(
                    f"objective {objective!r} is not solved by PORT_OPT. "
                    f"Supported: {', '.join(sorted(_OBJECTIVE_MODES))}.",
                    next_actions=["Choose max_sharpe or min_volatility, or omit objective to get the frontier."],
                )
            mode = _OBJECTIVE_MODES[objective_key]
        else:
            mode = "frontier"
        if mode not in _MODES:
            return _input_error(
                f"mode {mode!r} is not supported. Supported: {', '.join(sorted(_MODES))}.",
                next_actions=["Pass mode as frontier, all, max_sharpe, min_vol or risk_parity."],
            )

        # --- lookback / rates / frontier size --------------------------------
        if params.get("days") is not None:
            days = int(params["days"])
            if params.get("window") is not None:
                # days wins over the window label; say so instead of silently
                # choosing one lookback.
                unapplied.append("window")
        elif params.get("window") is not None:
            window_key = str(params["window"]).strip().lower()
            if window_key not in _WINDOW_DAYS:
                return _input_error(
                    f"window {params['window']!r} is not supported. Supported: {', '.join(_WINDOW_DAYS)}.",
                    next_actions=["Pass window as one of 90d, 180d, 1Y, 2Y, 5Y, or pass days."],
                )
            days = _WINDOW_DAYS[window_key]
        else:
            days = _DEFAULT_DAYS
        rate_key = "risk_free" if params.get("risk_free") is not None else "risk_free_rate"
        rf = float(params.get(rate_key, 0.04))
        points = max(10, min(200, int(params.get("frontier_points", 40))))
        if params.get("frontier_points") is not None and mode not in ("frontier", "all"):
            # The frontier size only matters when a frontier is computed.
            unapplied.append("frontier_points")
        if params.get("provider_mode") is not None:
            # Declared in the manifest, but the handler always uses yfinance daily
            # closes and does not switch data modes.
            unapplied.append("provider_mode")

        risk_model = str(params.get("risk_model") or "sample_cov").lower()
        if risk_model not in _APPLIED_RISK_MODELS:
            unapplied.append("risk_model")
        return_model = str(params.get("return_model") or "mean_historical").lower()
        if return_model not in _APPLIED_RETURN_MODELS:
            unapplied.append("return_model")
        frequency = str(params.get("frequency") or "1d").lower()
        if frequency not in _APPLIED_FREQUENCIES:
            unapplied.append("frequency")
        if params.get("constraints"):
            unapplied.append("constraints")

        # --- live returns -----------------------------------------------------
        async def _ret(s: str) -> tuple[str, pd.Series]:
            try:
                if not self.deps.yfinance:
                    raise RuntimeError("no yfinance")
                inst = await self.deps.symbol_registry.resolve(s) if self.deps.symbol_registry else None
                if not inst:
                    inst = Instrument(symbol=s, asset_class=AssetClass.EQUITY)
                df = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.OHLCV, instrument=inst,
                        start=datetime.now(timezone.utc) - timedelta(days=days),
                        interval="1d",
                    )),
                    timeout=float(params.get("quote_timeout", 8)),
                )
                return s, close_to_daily_returns(df)
            except Exception:
                return s, pd.Series(dtype=float)
        dropped: list[str] = []
        if live and self.deps.yfinance:
            results = await asyncio.gather(*(_ret(s) for s in symbols))
            dropped = [s for s, series in results if series.empty]
            # Audit Q3 #7: pairwise for mean-variance optimization too —
            # mixed equity+crypto universes were losing 70% of rows.
            rets = align_return_series(results, policy="pairwise")
        else:
            rets = pd.DataFrame()
        warnings: list[str] = []
        if rets.empty or len(rets.columns) < 2:
            # No usable live returns. Synthetic template returns never stand in for
            # them (data policy), with LIVE off or on: no weights are computed.
            no_weights_meta = {"mode": mode, "days": days, "days_basis": "calendar_days",
                               "risk_free": rf, "allow_short": allow_short,
                               "live": False, "fallback": False}
            if not live:
                return FunctionResult(
                    code=self.code, instrument=None,
                    data={
                        "status": "needs_input",
                        "reason": (
                            "PORT_OPT optimises on live yfinance daily returns, and LIVE is off, "
                            "so no weights were computed."
                        ),
                        # The requested universe (not returns-backed): nothing was optimised.
                        "symbols": list(symbols),
                        "dropped_symbols": [],
                        "unapplied_inputs": unapplied,
                        "next_actions": [
                            "Turn LIVE on to optimise on yfinance daily closes for the universe.",
                        ],
                    },
                    sources=[],
                    warnings=[
                        "LIVE is off: no weights were computed (no template returns are used).",
                        *_unapplied_warning(unapplied),
                    ],
                    metadata=no_weights_meta,
                )
            # Live returns were requested but are not available for enough symbols.
            return FunctionResult(
                code=self.code, instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": (
                        "Live yfinance returns are unavailable for at least two of the "
                        "requested symbols, so no weights were computed."
                    ),
                    "dropped_symbols": dropped,
                    "unapplied_inputs": unapplied,
                    "next_actions": [
                        "Retry once the market-data provider is reachable.",
                    ],
                },
                sources=[],
                warnings=[
                    "Live yfinance returns unavailable: no weights were computed.",
                    *_unapplied_warning(unapplied),
                ],
                metadata=no_weights_meta,
            )
        else:
            sources = ["yfinance"]
            fallback = False
            if dropped:
                warnings.append(
                    f"Symbols with no live returns were dropped: {', '.join(dropped)}. "
                    f"The optimum covers only {', '.join(str(c) for c in rets.columns)}."
                )
        warnings.extend(_unapplied_warning(unapplied))
        status = "partial" if dropped else "ok"

        # --- solvers ----------------------------------------------------------
        out: dict[str, Any] = {
            "status": status,
            "symbols": list(rets.columns),
            "samples": int(len(rets)),
            "dropped_symbols": dropped,
            "unapplied_inputs": unapplied,
        }
        if mode in ("frontier", "all"):
            ef = efficient_frontier(rets, points=points, allow_short=allow_short, risk_free=rf)
            out["efficient_frontier"] = [
                {"label": f"vol {p.volatility:.2%}", "return": p.expected_return, "vol": p.volatility,
                 "sharpe": p.sharpe, "weights": p.weights} for p in ef
            ]
        if mode in ("max_sharpe", "all"):
            ms = max_sharpe(rets, risk_free=rf, allow_short=allow_short)
            out["max_sharpe"] = {
                "weights": ms.weights, "return": ms.expected_return,
                "vol": ms.volatility, "sharpe": ms.sharpe,
                "converged": ms.converged, "solver_residual": ms.solver_residual,
            }
            if not ms.converged:
                warnings.append(
                    "max_sharpe did not reach a stationary point "
                    f"(last step moved weights by {ms.solver_residual:.2e}); weights may not be optimal."
                )
        if mode in ("min_vol", "all"):
            mv = min_volatility(rets, allow_short=allow_short, risk_free=rf)
            out["min_volatility"] = {
                "weights": mv.weights, "return": mv.expected_return,
                "vol": mv.volatility, "sharpe": mv.sharpe,
                "converged": mv.converged, "solver_residual": mv.solver_residual,
            }
            if not mv.converged:
                warnings.append(
                    "min_volatility did not reach a stationary point "
                    f"(last step moved weights by {mv.solver_residual:.2e}); weights may not be optimal."
                )
        if mode in ("risk_parity", "all"):
            try:
                rp = risk_parity(rets, risk_free=rf)
            except ValueError as exc:
                # A zero-variance asset has no defined risk contribution: report
                # that honestly instead of inventing equal-risk weights.
                rp = None
                warnings.append(f"risk_parity unavailable: {exc}")
            if rp is not None:
                out["risk_parity"] = {
                    "weights": rp.weights, "return": rp.expected_return,
                    "vol": rp.volatility, "sharpe": rp.sharpe,
                    "converged": rp.converged,
                    "max_risk_contribution_error": rp.max_rc_error,
                }
                if not rp.converged:
                    warnings.append(
                        "risk_parity did not reach equal risk contribution "
                        f"(max RC deviation {rp.max_rc_error:.2e}); weights are not ERC."
                    )
        weight_rows: list[dict[str, Any]] = []
        for section in ("max_sharpe", "min_volatility", "risk_parity"):
            result = out.get(section)
            if not isinstance(result, dict):
                continue
            weights = result.get("weights") or {}
            if not isinstance(weights, dict):
                continue
            for symbol, weight in weights.items():
                weight_rows.append({
                    "label": f"{section}:{symbol}",
                    "mode": section,
                    "symbol": symbol,
                    "weight": float(weight),
                    "weight_pct": float(weight) * 100,
                    "return": result.get("return"),
                    "vol": result.get("vol"),
                    "sharpe": result.get("sharpe"),
                })
        if weight_rows:
            out["rows"] = weight_rows
        out["summary"] = {
            "mode": mode,
            "symbols": len(rets.columns),
            "samples": int(len(rets)),
            "risk_free": rf,
            "allow_short": allow_short,
            "lookback_calendar_days": days,
        }
        out["methodology"] = (
            "Estimate daily return covariance and annualized expected returns for the selected universe. "
            "The efficient frontier plots volatility on the x-axis and expected return on the y-axis; "
            "optimizer modes compute max-Sharpe, min-volatility, and risk-parity weights."
        )
        out["field_dictionary"] = {
            "vol": "Annualized portfolio volatility.",
            "return": "Annualized expected portfolio return.",
            "sharpe": "(return - risk_free_rate) / volatility.",
            "weight_pct": "Optimizer allocation weight for a symbol.",
            "samples": "Trading-day return observations used; the lookback itself is in calendar days.",
            "converged": "Solver stationarity check for max_sharpe and min_volatility: true when one more "
                         "projected-gradient step moves no weight by more than 1e-4. A stationary point, not a proof of global optimality.",
            "solver_residual": "Largest weight move of one more projected-gradient step (0 at a stationary point).",
        }
        return FunctionResult(code=self.code, instrument=None, data=out,
                              sources=sources,
                              warnings=warnings,
                              metadata={"mode": mode, "days": days,
                                         "days_basis": "calendar_days",
                                         "risk_free": rf,
                                         "allow_short": allow_short,
                                         # R2-F11: template rows must never
                                         # carry a live voucher — the source
                                         # string alone used to be the only
                                         # thing keeping the pill honest.
                                         "live": live and not fallback,
                                         "fallback": fallback})


def _unapplied_warning(unapplied: list[str]) -> list[str]:
    if not unapplied:
        return []
    return [
        "Inputs not applied by PORT_OPT (results do not reflect them): "
        + ", ".join(unapplied) + "."
    ]


def _input_error(reason: str, *, next_actions: list[str]) -> FunctionResult:
    return FunctionResult(
        code="PORT_OPT",
        instrument=None,
        data={"status": "input_error", "reason": reason, "next_actions": next_actions},
        sources=[],
        warnings=[f"PORT_OPT was not computed: {reason}"],
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
