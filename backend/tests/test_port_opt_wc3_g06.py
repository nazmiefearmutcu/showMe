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
