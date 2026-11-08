"""Agent fast probe must not invent MLSIG or RPAR measurements (MLSIG#2, RPAR agent probe).

Before this fix the agent probe built MLSIG test accuracy, feature importances,
Sharpe and a long_bias label, and RPAR diversification scores, all from a
per-asset-class profile table. Those are invented values. The probe now
returns the explicit missing-data state for both codes and they contribute no
signal to candidate ranking. No network: the probe is local.
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme import server
from showme.server_routes import _agent_runtime as rt
from showme.server_routes._models import FunctionIndexEntry


_PROFILE_CONSTANTS = ("0.24", "0.21", "0.19", "0.11", "84")


def _entry(code: str) -> FunctionIndexEntry:
    return FunctionIndexEntry(code=code, name=code, category="portfolio")


def _probe(code: str, symbol: str = "AAPL", asset_class: str = "EQUITY") -> dict[str, Any]:
    candidate = {"symbol": symbol, "asset_class": asset_class}
    return rt._agent_probe_payload(_entry(code), candidate, dict(candidate), True)


def _assert_no_invented_values(payload: dict[str, Any]) -> None:
    flat = repr(payload)
    assert "long_bias" not in flat
    assert "short_bias" not in flat
    assert "positive_risk_balance" not in flat
    assert "risk_watch" not in flat
    for constant in _PROFILE_CONSTANTS:
        assert constant not in flat, constant


def test_mlsig_probe_is_explicit_state_not_profile_metrics() -> None:
    payload = _probe("MLSIG")

    assert payload["metadata"]["fallback"] is True
    assert rt._agent_payload_score("MLSIG", payload)["signal_count"] == 0
    _assert_no_invented_values(payload)
    assert "test_accuracy" not in payload["data"] or payload["data"]["test_accuracy"] is None


def test_rpar_probe_is_explicit_state_not_profile_scores() -> None:
    payload = _probe("RPAR")

    assert payload["metadata"]["fallback"] is True
    assert rt._agent_payload_score("RPAR", payload)["signal_count"] == 0
    _assert_no_invented_values(payload)
    assert "diversification_score" not in payload["data"]
    assert "portfolio_volatility_pct" not in payload["data"]


def test_mlsig_alone_cannot_rank_a_candidate(monkeypatch) -> None:
    monkeypatch.setattr(server, "_load_function_index", lambda: [_entry("MLSIG")])

    out = asyncio.run(rt._run_best_symbol_agent({
        "candidates": ["AAPL", "EURUSD"],
        "max_candidates": 2,
        "execute_functions": False,
    }))

    assert out["best"] is not None
    assert all(row["signal_functions"] == 0 for row in out["ranked"])
    assert all(row["score"] == 0 for row in out["ranked"])
