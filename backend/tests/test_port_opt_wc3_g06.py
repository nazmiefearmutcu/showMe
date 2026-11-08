"""PORT_OPT follow-ups (wc3-g06): manifest truthfulness, live-off honesty and weight caps.

Offline: yfinance is replaced by an in-memory fake; nothing touches the network.
"""
from __future__ import annotations

from showme.manifest import REGISTRY, load_seeds


def test_methodology_does_not_claim_risk_parity_is_the_only_convergence_reporter() -> None:
    load_seeds()
    methodology = REGISTRY.get("PORT_OPT").methodology
    assert "is the only mode that reports" not in methodology, methodology
    # the solvers that do report convergence are named accurately
    assert "converged" in methodology and "solver_residual" in methodology, methodology


def test_methodology_names_the_risk_parity_output_key_that_is_emitted() -> None:
    # PORT_OPT#6-RQ: the manifest must name the key the output really contains
    # (port_opt.py emits max_risk_contribution_error, not the internal max_rc_error).
    load_seeds()
    methodology = REGISTRY.get("PORT_OPT").methodology
    assert "max_rc_error" not in methodology, methodology
    assert "max_risk_contribution_error" in methodology, methodology


import asyncio  # noqa: E402

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.functions.portfolio.port_opt import PortOptFunction  # noqa: E402

from test_port_opt_erc_and_rf import SYMBOLS, _FakeYFinance, _VOLS  # noqa: E402


def _run(deps_yf, **params):
    fn = PortOptFunction(deps=FunctionDeps(yfinance=deps_yf))
    return asyncio.run(fn.execute(**params))


# --- PORT_OPT#5 follow-up: LIVE off must not optimise on template returns ------

def test_live_off_produces_no_weights_from_template_returns() -> None:
    result = _run(_FakeYFinance(_VOLS), symbols=SYMBOLS, mode="all", live=False, days=756)
    assert result.data.get("status") == "needs_input", result.data.get("status")
    for key in ("max_sharpe", "min_volatility", "risk_parity", "efficient_frontier", "rows"):
        assert key not in result.data, key
    assert result.sources == [], result.sources
    assert not any("computed_return_model" in str(s) for s in result.sources)


def test_live_off_is_never_reported_as_ok() -> None:
    result = _run(None, symbols=SYMBOLS, mode="max_sharpe", live=False, days=756)
    assert result.data.get("status") != "ok", result.data
    assert result.metadata.get("fallback") is False, result.metadata


# --- PORT_OPT#3 follow-up: constraints.max_weight is enforced, not just reported ---

_CAP = 0.2


def test_max_weight_is_enforced_for_max_sharpe() -> None:
    result = _run(_FakeYFinance(_VOLS), symbols=SYMBOLS, mode="max_sharpe", live=True,
                  days=756, constraints={"max_weight": _CAP})
    weights = result.data["max_sharpe"]["weights"]
    assert max(weights.values()) <= _CAP + 1e-6, weights
    assert abs(sum(weights.values()) - 1.0) < 1e-6, sum(weights.values())
    assert "constraints" not in result.data["unapplied_inputs"], result.data["unapplied_inputs"]


def test_max_weight_is_enforced_for_min_volatility_and_frontier() -> None:
    result = _run(_FakeYFinance(_VOLS), symbols=SYMBOLS, mode="all", live=True,
                  days=756, constraints={"max_weight": _CAP})
    mv = result.data["min_volatility"]["weights"]
    assert max(mv.values()) <= _CAP + 1e-6, mv
    for point in result.data["efficient_frontier"]:
        assert max(point["weights"].values()) <= _CAP + 1e-6, point["weights"]


def test_infeasible_max_weight_is_an_input_error() -> None:
    result = _run(_FakeYFinance(_VOLS), symbols=SYMBOLS, mode="max_sharpe", live=True,
                  days=756, constraints={"max_weight": 0.1})
    assert result.data["status"] == "input_error", result.data
    assert "max_sharpe" not in result.data


def test_unsupported_constraint_key_is_still_reported() -> None:
    result = _run(_FakeYFinance(_VOLS), symbols=SYMBOLS, mode="max_sharpe", live=True,
                  days=756, constraints={"max_weight": 0.4, "sector_caps": {"Tech": 0.3}})
    assert "constraints" in result.data["unapplied_inputs"], result.data["unapplied_inputs"]
    weights = result.data["max_sharpe"]["weights"]
    assert max(weights.values()) <= 0.4 + 1e-6, weights


def test_risk_parity_section_says_it_ignores_max_weight() -> None:
    result = _run(_FakeYFinance(_VOLS), symbols=SYMBOLS, mode="all", live=True,
                  days=756, constraints={"max_weight": _CAP})
    assert "constraints" in result.data["unapplied_inputs"], result.data["unapplied_inputs"]
    assert any("risk_parity" in w and "max_weight" in w for w in result.warnings), result.warnings


def test_manifest_constraints_input_does_not_claim_unapplied_caps() -> None:
    load_seeds()
    spec = next(s for s in REGISTRY.get("PORT_OPT").inputs if s.name == "constraints")
    text = spec.description or ""
    assert "max_weight" in text, text
    assert "sector" in text.lower() and "not applied" in text, text
