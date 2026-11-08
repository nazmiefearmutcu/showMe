"""PORT_OPT honesty regressions (wc1-g13).

Each test reproduces one defect through ``PortOptFunction.execute`` (or the
manifest / router) with the yfinance adapter replaced by an offline fake.

* PORT_OPT#3 - declared manifest inputs (objective, window, risk_free_rate,
  frontier_points, constraints ...) were silently ignored.
* PORT_OPT#4 - symbols whose fetch fails were dropped without a warning.
* PORT_OPT#5 - live returns requested but unavailable still produced weights
  from synthetic cosine returns.
* PORT_OPT#6 - the manifest claimed PyPortfolioOpt / Riskfolio / EfficientFrontier.
* PORT_OPT#7 - the sidecar injected agent defaults (days 120, peers, live) into
  direct PORT_OPT calls.
* PORT_OPT#9 - the frontier repeated identical points and the lookback was
  calendar days while the output called it days.
"""

from __future__ import annotations

import asyncio

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.port_opt import PortOptFunction
from showme.manifest import REGISTRY, load_seeds

from test_port_opt_erc_and_rf import SYMBOLS, _FakeYFinance, _VOLS


def _run(deps_yf, **params):
    fn = PortOptFunction(deps=FunctionDeps(yfinance=deps_yf))
    return asyncio.run(fn.execute(**params))


# --- PORT_OPT#3 -------------------------------------------------------------

def test_window_input_sets_lookback_when_days_absent() -> None:
    result = _run(None, symbols=["AAPL", "MSFT", "NVDA"], window="90d", live=False)
    assert result.metadata["days"] == 90


def test_objective_input_selects_the_solver_mode() -> None:
    result = _run(None, symbols=["AAPL", "MSFT", "NVDA"], objective="max_sharpe", live=False)
    assert "max_sharpe" in result.data, sorted(result.data)


def test_risk_free_rate_input_is_applied() -> None:
    result = _run(None, symbols=["AAPL", "MSFT", "NVDA"], risk_free_rate=0.03, live=False)
    assert result.data["summary"]["risk_free"] == 0.03


def test_frontier_points_input_is_applied() -> None:
    result = _run(
        _FakeYFinance(_VOLS), symbols=SYMBOLS, mode="frontier", live=True,
        days=756, frontier_points=10,
    )
    assert len(result.data["efficient_frontier"]) <= 10


def test_unapplied_constraints_are_reported_not_silently_ignored() -> None:
    result = _run(
        _FakeYFinance(_VOLS), symbols=SYMBOLS, mode="max_sharpe", live=True,
        days=756, constraints={"max_weight": 0.2},
    )
    assert "constraints" in result.data.get("unapplied_inputs", []), result.data.get("unapplied_inputs")
    assert any("constraints" in w for w in result.warnings), result.warnings


def test_unsupported_objective_is_an_input_error_not_a_different_answer() -> None:
    result = _run(None, symbols=["AAPL", "MSFT", "NVDA"], objective="max_return", live=False)
    assert result.data.get("status") == "input_error", result.data.get("status")
    assert "max_sharpe" not in result.data and "efficient_frontier" not in result.data


# --- PORT_OPT#4 -------------------------------------------------------------

def test_failed_symbol_is_reported_and_status_is_partial() -> None:
    result = _run(
        _FakeYFinance(_VOLS), symbols=["SPY", "TLT", "ZZZNOTREAL", "GLD"],
        mode="frontier", live=True, days=756,
    )
    assert result.data["symbols"] == ["SPY", "TLT", "GLD"]
    assert result.data.get("dropped_symbols") == ["ZZZNOTREAL"], result.data.get("dropped_symbols")
    assert result.data.get("status") == "partial", result.data.get("status")
    assert any("ZZZNOTREAL" in w for w in result.warnings), result.warnings


# --- PORT_OPT#5 -------------------------------------------------------------

class _RaisingYFinance:
    async def fetch(self, request):  # noqa: ANN001 - adapter protocol
        raise RuntimeError("yfinance offline (test)")


def test_live_unavailable_returns_no_weights() -> None:
    result = _run(_RaisingYFinance(), symbols=SYMBOLS, mode="all", live=True, days=756)
    assert result.data.get("status") == "provider_unavailable", result.data.get("status")
    for key in ("max_sharpe", "min_volatility", "risk_parity", "rows", "efficient_frontier"):
        assert key not in result.data, key
    assert result.sources == []


# --- PORT_OPT#6 -------------------------------------------------------------

def test_manifest_does_not_claim_external_solvers() -> None:
    load_seeds()
    entry = REGISTRY.get("PORT_OPT")
    text = f"{entry.intent} {entry.methodology}"
    for claim in ("PyPortfolioOpt", "Riskfolio", "EfficientFrontier", "min-vol and max-return"):
        assert claim not in text, claim


# --- PORT_OPT#7 -------------------------------------------------------------

def test_router_does_not_inject_agent_defaults_into_port_opt() -> None:
    from showme.server_routes._agent_runtime import _route_function_params

    params = _route_function_params("PORT_OPT", {})
    for key in ("days", "range", "live", "symbols", "query"):
        assert key not in params, (key, params.get(key))


def test_router_keeps_caller_days_for_port_opt() -> None:
    from showme.server_routes._agent_runtime import _route_function_params

    params = _route_function_params("PORT_OPT", {"days": 756, "mode": "all"})
    assert params["days"] == 756
    assert params["mode"] == "all"


# --- PORT_OPT#9 -------------------------------------------------------------

def test_frontier_has_no_duplicate_points() -> None:
    result = _run(_FakeYFinance(_VOLS), symbols=SYMBOLS, mode="frontier", live=True, days=756)
    ef = result.data["efficient_frontier"]
    keys = {(round(p["vol"], 10), round(p["return"], 10)) for p in ef}
    assert len(keys) == len(ef), f"{len(ef)} points but {len(keys)} distinct"


def test_lookback_is_labelled_as_calendar_days() -> None:
    result = _run(_FakeYFinance(_VOLS), symbols=SYMBOLS, mode="frontier", live=True, days=756)
    assert result.metadata["days_basis"] == "calendar_days"
    assert result.data["summary"]["lookback_calendar_days"] == 756


def test_model_returns_are_labelled_when_live_is_off() -> None:
    """LIVE off is an explicit user choice: the model-returns result is allowed,
    but it must never be read as market data."""
    result = _run(None, symbols=SYMBOLS, mode="risk_parity", live=False, days=756)
    assert result.sources == ["computed_return_model"]
    assert result.metadata["fallback"] is True
    assert any("not market data" in w for w in result.warnings), result.warnings


# --- PORT_OPT#3 follow-up: inputs that were still silently ignored -------------

def test_provider_mode_input_is_reported_as_unapplied() -> None:
    result = _run(
        _FakeYFinance(_VOLS), symbols=SYMBOLS, mode="frontier", live=True,
        days=756, provider_mode="cached_snapshot",
    )
    assert "provider_mode" in result.data.get("unapplied_inputs", []), result.data.get("unapplied_inputs")
    assert any("provider_mode" in w for w in result.warnings), result.warnings


def test_window_is_reported_when_days_takes_precedence() -> None:
    result = _run(
        _FakeYFinance(_VOLS), symbols=SYMBOLS, mode="frontier", live=True,
        days=756, window="2Y",
    )
    assert result.metadata["days"] == 756
    assert "window" in result.data.get("unapplied_inputs", []), result.data.get("unapplied_inputs")


def test_frontier_points_is_reported_when_mode_has_no_frontier() -> None:
    result = _run(
        _FakeYFinance(_VOLS), symbols=SYMBOLS, mode="max_sharpe", live=True,
        days=756, frontier_points=20,
    )
    assert "efficient_frontier" not in result.data
    assert "frontier_points" in result.data.get("unapplied_inputs", []), result.data.get("unapplied_inputs")


# --- PORT_OPT#6 follow-up: remaining external-solver claim and min-vol method ---

def test_manifest_input_descriptions_do_not_claim_external_solvers() -> None:
    load_seeds()
    entry = REGISTRY.get("PORT_OPT")
    texts = [entry.intent, entry.methodology] + [spec.description or "" for spec in entry.inputs]
    for text in texts:
        for claim in ("PyPortfolioOpt", "Riskfolio", "EfficientFrontier"):
            assert claim not in text, (claim, text)


def test_methodology_does_not_give_min_volatility_a_return_multiplier() -> None:
    load_seeds()
    entry = REGISTRY.get("PORT_OPT")
    assert "Min-volatility and the frontier use" not in entry.methodology, entry.methodology
    assert "Min-volatility uses projected gradient descent" in entry.methodology, entry.methodology


