"""PCAS — PCA-based portfolio stress test.

Single-factor mode (legacy): ``pc_index`` + ``k_sigma`` shock one principal
component. Multi-factor mode: ``n_factors`` and/or ``shock_set`` (σ per PC)
shock the first N components; each component's P&L is reported and the
aggregate is the linear sum (the components are orthogonal, so the shocks
add up in portfolio return space).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions.portfolio.return_series import align_return_series, close_to_daily_returns
from showme.engine.portfolio.state import PortfolioState
from showme.engine.services import pca_stress

# Calendar-day equivalents for the lookback_window manifest options.
_LOOKBACK_DAYS = {"90d": 90, "180d": 180, "1Y": 365, "2Y": 730, "5Y": 1826}
# Only daily returns are computed; other cadences are not implemented.
_IMPLEMENTED_FREQUENCIES = ("1d",)
_MAX_FACTORS = 20


@FunctionRegistry.register
class PCASFunction(BaseFunction):
    code = "PCAS"
    name = "PCA Factor Stress"
    category = "portfolio"
    description = "Apply k-σ shock along principal components (correlated stress)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        pc_index = int(params.get("pc_index", 0))
        k_sigma = float(params.get("k_sigma", 3.0))
        top_n = int(params.get("top_n", 8))
        # Each flag is parsed on its own: the string "false" is truthy in Python,
        # so an or-chain over raw values would let live_prices="false" through.
        live_portfolio = any(
            _truthy(params.get(key)) for key in ("live_portfolio", "live_prices", "live")
        )
        if not live_portfolio:
            return _empty_pcas(self.code, instrument, pc_index, k_sigma,
                               "live=true required for PCA stress", status="input_error")
        if "live_prices" in params and not _truthy(params.get("live_prices")):
            # The modeled template returns were removed: a synthetic series must
            # never feed a stress result. Refuse the explicit opt-out instead.
            return _empty_pcas(self.code, instrument, pc_index, k_sigma,
                               "live_prices=false asks for modeled template returns, which are not "
                               "offered; PCA stress runs on live price history only (omit live_prices "
                               "or set it to true)",
                               status="input_error")

        frequency = str(params.get("frequency") or "1d").strip()
        if frequency not in _IMPLEMENTED_FREQUENCIES:
            return _empty_pcas(self.code, instrument, pc_index, k_sigma,
                               f"frequency {frequency!r} is not implemented; only 1d returns are computed",
                               status="input_error")
        lookback = params.get("lookback_window")
        if lookback is not None and str(lookback) not in _LOOKBACK_DAYS:
            return _empty_pcas(self.code, instrument, pc_index, k_sigma,
                               f"lookback_window {lookback!r} is not one of {sorted(_LOOKBACK_DAYS)}",
                               status="input_error")
        days = _LOOKBACK_DAYS[str(lookback)] if lookback is not None else int(params.get("days", 504))

        multi, indices, shocks, plan_error = _factor_plan(params, pc_index, k_sigma)
        if plan_error:
            return _empty_pcas(self.code, instrument, pc_index, k_sigma, plan_error, status="input_error")

        portfolio = PortfolioState()
        if _truthy(params.get("include_legacy") or params.get("legacy")):
            portfolio.import_legacy_crypto()
        eligible = [p for p in portfolio.positions
                    if p.instrument.asset_class.value not in ("MACRO", "BOND")]
        if not eligible:
            return _empty_pcas(self.code, None, pc_index, k_sigma, "empty portfolio")
        timeout = float(params.get("timeout", 8))

        async def _ret(p) -> tuple[str, pd.Series, float | None]:
            try:
                if not self.deps.yfinance:
                    raise RuntimeError("no yfinance")
                df = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.OHLCV, instrument=p.instrument,
                        start=datetime.now(timezone.utc) - timedelta(days=days),
                        interval="1d",
                    )),
                    timeout=timeout,
                )
                last = float(df["close"].iloc[-1])
                return p.instrument.symbol, close_to_daily_returns(df), last
            except Exception:
                return p.instrument.symbol, pd.Series(dtype=float), None

        results = await asyncio.gather(*(_ret(p) for p in eligible))
        # A position without live history is not valued at its cost basis and
        # folded into the book: the stress is refused and the gap is named.
        missing = [s for s, r, _ in results if r.empty]
        if missing:
            return _empty_pcas(
                self.code, None, pc_index, k_sigma,
                f"no live return history for {', '.join(missing)}; PCA stress is not run on a partial book",
                status="provider_unavailable",
            )
        last_map = {s: lp for s, _, lp in results}
        # Audit Q3 #7: forward-fill for PCA — eigen-decomposition needs a
        # dense matrix; pairwise NaNs would invalidate the spectrum.
        df = align_return_series(
            ((s, r) for s, r, _ in results), policy="forward_fill"
        )
        if df.shape[0] < 30:
            return _empty_pcas(self.code, None, pc_index, k_sigma, "no live return history",
                               status="provider_unavailable")
        data_mode = "delayed_reference"
        source = "yfinance"
        # Build weights from positions
        notional = []
        for p in eligible:
            notional.append((p.instrument.symbol, p.quantity * last_map[p.instrument.symbol]))
        total = sum(n for _, n in notional) or 1.0
        sym_to_w = {s: n / total for s, n in notional}
        cols = list(df.columns)
        weights = np.array([sym_to_w.get(s, 0.0) for s in cols])
        # PCA + factor shock
        try:
            decomp = pca_stress.pca_decompose(df.values)
        except Exception as e:
            return _pca_failure(self.code, pc_index, k_sigma, e, df)
        available = int(decomp["loadings"].shape[0])
        if max(indices) >= available:
            # Asking for more components than the history supports is a user
            # input error (lower n_factors), not a provider outage.
            return _empty_pcas(
                self.code, None, pc_index, k_sigma,
                f"needs {max(indices) + 1} principal components, history supports {available}",
                status="input_error",
            )
        try:
            shocks_out = [
                pca_stress.apply_to_portfolio(weights, df.values, pc_index=idx, k_sigma=sig)
                for idx, sig in zip(indices, shocks)
            ]
            # Components are orthogonal, so their shocks add linearly in asset space.
            combined_returns = np.sum([np.asarray(s["asset_returns"]) for s in shocks_out], axis=0)
            combined_return = float(weights @ combined_returns)
        except Exception as e:
            return _pca_failure(self.code, pc_index, k_sigma, e, df)
        top = pca_stress.top_loadings(decomp["loadings"], cols, pc_index=pc_index,
                                      top_n=top_n)
        asset_returns = [
            {
                "symbol": s,
                "weight": float(weights[i]),
                "weight_pct": float(weights[i] * 100),
                "shock_return": float(combined_returns[i]),
                "shock_return_pct": float(combined_returns[i] * 100),
                "pnl": float(weights[i] * total * combined_returns[i]),
            }
            for i, s in enumerate(cols)
        ]
        loading_rows = [
            {
                "symbol": item.get("symbol"),
                "loading": float(item.get("loading") or 0.0),
                "pc_index": pc_index,
            }
            for item in top
        ]
        ev_ratio = decomp["explained_variance_ratio"]
        components = []
        shock_impacts = []
        for idx, sh in zip(indices, shocks_out):
            label = f"PC{idx + 1}"
            impact_value = float(sh["portfolio_return"] * total)
            components.append({
                "pc_index": idx,
                "component": label,
                "explained_variance_pct": float(ev_ratio[idx] * 100),
                "eigenvalue": float(decomp["explained_variance"][idx]),
                "shock_sigma": float(sh["k_sigma"]),
                "top_loadings": pca_stress.top_loadings(
                    decomp["loadings"], cols, pc_index=idx, top_n=top_n),
            })
            shock_impacts.append({
                "pc_index": idx,
                "component": label,
                "shock_sigma": float(sh["k_sigma"]),
                "factor_shock_magnitude": float(sh["shock_magnitude"]),
                "impact_value": impact_value,
                "impact_pct": float(sh["portfolio_return"] * 100),
            })
        aggregate_impact = float(sum(item["impact_value"] for item in shock_impacts))
        aggregate_impact_pct = float(sum(item["impact_pct"] for item in shock_impacts))
        largest = max(shock_impacts, key=lambda item: abs(item["impact_value"]))
        retained_variance = float(sum(ev_ratio[idx] for idx in indices))
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "status": "ok",
                # Vintage of the returns used: the last price bar date. The
                # retrieval time is reported separately as fetched_at.
                "as_of": _last_bar_date(df),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "data_mode": data_mode,
                "n_factors": len(indices),
                "multi_factor": multi,
                "lookback_days": days,
                "frequency": frequency,
                "pc_index": pc_index, "k_sigma": k_sigma,
                "explained_variance_ratio": ev_ratio[:5],
                "explained_variance": retained_variance,
                "factor_shock_magnitude": shocks_out[0]["shock_magnitude"] if len(shocks_out) == 1 else None,
                "portfolio_return_pct": combined_return * 100,
                "portfolio_pnl_dollar": combined_return * total,
                "aggregate_impact": aggregate_impact,
                "aggregate_impact_pct": aggregate_impact_pct,
                "largest_pc": largest["component"],
                "components": components,
                "shock_impacts": shock_impacts,
                "total_notional": total,
                "top_loadings": top,
                "asset_returns": asset_returns,
                "rows": asset_returns,
                "loadings": loading_rows,
                "samples": int(df.shape[0]),
                "summary": {
                    "pc_index": pc_index,
                    "k_sigma": k_sigma,
                    "n_factors": len(indices),
                    "portfolio_return_pct": combined_return * 100,
                    "portfolio_pnl_dollar": combined_return * total,
                    "aggregate_impact": aggregate_impact,
                },
                "methodology": (
                    "Run PCA on aligned daily return history, shock each selected principal component by "
                    "its σ multiple, then project the correlated asset return shocks through current "
                    "portfolio weights. Component P&L impacts are summed linearly into aggregate_impact."
                ),
                "field_dictionary": {
                    "explained_variance_ratio": "Share of return variance explained by each principal component.",
                    "explained_variance": "Share of return variance covered by the retained components.",
                    "shock_return_pct": "Asset return implied by the selected PCA shock.",
                    "pnl": "Dollar contribution of the shock to portfolio P&L.",
                    "loading": "Symbol loading on the selected principal component.",
                    "aggregate_impact": "Linear sum of the per-component P&L impacts.",
                },
            },
            # Every result here is built on live yfinance history; there is no
            # modeled or template branch.
            sources=[source],
        )


def _factor_plan(
    params: dict[str, Any], pc_index: int, k_sigma: float,
) -> tuple[bool, list[int], list[float], str | None]:
    """Resolve which components to shock and by how many σ.

    Returns (multi_factor, component indices, σ per component, error reason).
    """
    raw_n = params.get("n_factors")
    raw_set = params.get("shock_set")
    shock_list: list[float] | None = None
    if raw_set not in (None, "", []):
        items = raw_set.split(",") if isinstance(raw_set, str) else list(raw_set) if isinstance(raw_set, (list, tuple)) else None
        if items is None:
            return False, [], [], "shock_set must be a list of σ multiples, one per factor"
        try:
            shock_list = [float(str(item).strip()) for item in items if str(item).strip() != ""]
        except ValueError:
            return False, [], [], "shock_set must contain only numbers (σ multiples)"
        if not shock_list:
            return False, [], [], "shock_set is empty"
    if raw_n is None and shock_list is None:
        return False, [pc_index], [k_sigma], None
    try:
        n = int(raw_n) if raw_n is not None else len(shock_list or [])
    except (TypeError, ValueError):
        return False, [], [], "n_factors must be an integer"
    if not 1 <= n <= _MAX_FACTORS:
        return False, [], [], f"n_factors must be between 1 and {_MAX_FACTORS}"
    if shock_list is not None and len(shock_list) != n:
        return False, [], [], f"shock_set has {len(shock_list)} values for {n} factors"
    shocks = shock_list if shock_list is not None else [k_sigma] * n
    return True, list(range(n)), shocks, None


def _pca_failure(code: str, pc_index: int, k_sigma: float, error: Exception, df: Any) -> FunctionResult:
    """Decomposition or shock failure on the history itself (provider-side state)."""
    return FunctionResult(
        code=code,
        instrument=None,
        data={
            **_empty_pcas(code, None, pc_index, k_sigma, f"pca: {error}").data,
            "samples": int(df.shape[0]) if hasattr(df, "shape") else 0,
        },
        sources=["portfolio_state"],
        metadata={"provider_errors": [f"pca: {error}"]},
    )


def _last_bar_date(df: Any) -> str | None:
    """ISO date of the last aligned return bar (None when the history is empty)."""
    if df is None or getattr(df, "shape", (0,))[0] == 0:
        return None
    try:
        return pd.Timestamp(df.index[-1]).date().isoformat()
    except (TypeError, ValueError, AttributeError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _empty_pcas(
    code: str,
    instrument: Instrument | None,
    pc_index: int,
    k_sigma: float,
    reason: str,
    status: str | None = None,
) -> FunctionResult:
    if status is None:
        status = "ready_no_positions" if "portfolio" in reason else "provider_unavailable"
    return FunctionResult(
        code=code,
        instrument=instrument,
        data={
            "status": status,
            "reason": reason,
            "pc_index": pc_index,
            "k_sigma": k_sigma,
            "explained_variance_ratio": [],
            "portfolio_return_pct": None,
            "portfolio_pnl_dollar": None,
            "top_loadings": [],
            "components": [],
            "shock_impacts": [],
            "aggregate_impact": None,
            "samples": 0,
            "rows": [],
            "next_actions": [
                "Add real positions through portfolio state.",
                "Set live=true to fetch live return history for every position.",
            ],
            "methodology": (
                "PCA stress requires portfolio positions plus aligned return history. It shocks one "
                "principal component and maps the shock through position weights."
            ),
        },
        sources=["portfolio_state"],
        metadata={"empty": True, "requires_positions": True},
    )
