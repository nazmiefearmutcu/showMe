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
