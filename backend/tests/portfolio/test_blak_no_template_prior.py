"""BLAK#6 / BLAK#3-RQ regression: no prior is ever built from invented returns.

The former deterministic sine template stood in for market returns on the
default (live off, MODEL) path and whenever the live history was too thin.
A prior, covariance and posterior built on it are not market data and break
the DATA POLICY. These tests pin the honest contract:

* live off  -> status ``needs_input`` with reason and next_actions, no prior;
* live on but no usable history -> status ``provider_unavailable``, no prior;
* the market-cap weights that were really resolved are still reported;
* the synthetic source label never appears.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataSourceError
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.blak import BLAKFunction

_PRIOR_KEYS = (
    "prior_covariance",
    "implied_returns_prior",
    "posterior_returns",
    "implied_optimal_weights",
    "rows",
    "prior_covariance_estimator",
)


@dataclass
class _Ref:
    market_cap: float | None = None
    extras: dict = field(default_factory=dict)


class _RefOnlyYf:
    """Serves market caps (REFDATA) and refuses every return request."""

    def __init__(self, caps: dict[str, float]) -> None:
        self._caps = caps
        self.ohlcv_calls = 0

    async def fetch(self, request: Any) -> Any:
        sym = request.instrument.symbol.upper()
        if request.kind == DataKind.REFDATA:
            return _Ref(market_cap=self._caps.get(sym))
        self.ohlcv_calls += 1
        raise DataSourceError(f"no history for {sym} in this test")


def test_default_run_without_live_has_no_template_prior() -> None:
    """The default (no live flag) BLAK run must not return a prior."""
    result = asyncio.run(
        BLAKFunction(deps=FunctionDeps()).execute(symbols=["AAPL", "MSFT", "SPY"])
    )
    assert result.data["status"] == "needs_input"
    assert result.data["reason"]
    assert result.data["next_actions"]
    for key in _PRIOR_KEYS:
        assert key not in result.data, key
    assert "synthetic_fallback" not in result.sources
    assert result.data["return_data_state"] == "unavailable"
    assert result.data["samples"] == 0


def test_default_run_still_reports_resolved_market_cap_weights() -> None:
    """Honest state keeps the real market-cap weights, not a template prior."""
    caps = {"AAPL": 3.0e12, "MSFT": 1.0e12}
    deps = FunctionDeps(yfinance=_RefOnlyYf(caps))
    result = asyncio.run(BLAKFunction(deps=deps).execute(symbols=["AAPL", "MSFT"]))
    assert result.data["status"] == "needs_input"
    assert result.data["market_cap_data_state"] == "real"
    assert abs(result.data["market_weights"]["AAPL"] - 0.75) < 1e-9
    assert abs(result.data["market_weights"]["MSFT"] - 0.25) < 1e-9


def test_live_run_without_history_is_provider_unavailable_not_template() -> None:
    """Live on, every return fetch fails: explicit state, no synthetic prior."""
    yf = _RefOnlyYf({"AAPL": 3.0e12, "MSFT": 1.0e12})
    result = asyncio.run(
        BLAKFunction(deps=FunctionDeps(yfinance=yf)).execute(
            symbols=["AAPL", "MSFT"], live=True,
        )
    )
    assert yf.ohlcv_calls == 2
    assert result.data["status"] == "provider_unavailable"
    assert result.data["reason"]
    assert result.data["next_actions"]
    for key in _PRIOR_KEYS:
        assert key not in result.data, key
    assert len(result.data["live_fetch_errors"]) == 2
    assert "synthetic_fallback" not in result.sources


def test_live_run_without_any_provider_is_provider_unavailable() -> None:
    """Live on but no market-data adapter wired: refused, never templated."""
    result = asyncio.run(
        BLAKFunction(deps=FunctionDeps()).execute(symbols=["AAPL", "MSFT"], live=True)
    )
    assert result.data["status"] == "provider_unavailable"
    for key in _PRIOR_KEYS:
        assert key not in result.data, key


def test_template_generator_is_gone() -> None:
    """The sine-wave template must not remain reachable from BLAK."""
    import showme.engine.functions.portfolio.blak as blak_mod

    assert not hasattr(blak_mod, "_template_returns")
