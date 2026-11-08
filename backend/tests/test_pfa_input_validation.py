"""PFA (Brinson attribution) must not invent inputs or report unreconciled effects.

Regression for P1a-g12 findings:
  * PFA#1 - the default call used to serve a hard-coded five-sector sample as a
    modelled result with an active return headline and no warning.
  * PFA#2 - weights that do not sum to 100% produced effects that did not add
    up to the reported active return.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.portfolio.pfa import PFAFunction

PORT_W = {"Technology": 0.45, "Financials": 0.20, "Healthcare": 0.15, "Energy": 0.10, "Consumer": 0.10}
PORT_R = {"Technology": 0.18, "Financials": 0.05, "Healthcare": 0.07, "Energy": -0.04, "Consumer": 0.03}
BENCH_W = {"Technology": 0.30, "Financials": 0.18, "Healthcare": 0.18, "Energy": 0.08, "Consumer": 0.10,
           "Industrials": 0.16}
BENCH_R = {"Technology": 0.12, "Financials": 0.04, "Healthcare": 0.05, "Energy": -0.06, "Consumer": 0.02,
           "Industrials": 0.06}
# Complete maps: Industrials is benchmark-only, so the portfolio carries it at 0% weight with an
# explicitly supplied sector return (the what-if return for a sector the portfolio does not hold).
FULL_PORT_W = {**PORT_W, "Industrials": 0.0}
FULL_PORT_R = {**PORT_R, "Industrials": 0.06}


def _run(**params):
    return asyncio.run(PFAFunction().execute(**params))


def test_default_call_does_not_serve_a_sample_result():
    res = _run()
    assert res.data["status"] == "input_required"
    assert res.data["rows"] == []
    # No headline is computed from invented weights and returns.
    assert "active_return" not in res.data.get("totals", {})
    assert res.data.get("summary", {}).get("active_return") is None
    assert res.data["next_actions"]


def test_partial_maps_are_input_required_not_a_sample():
    res = _run(port_weights=PORT_W, port_returns=PORT_R, bench_weights=BENCH_W)
    assert res.data["status"] == "input_required"
    assert res.data["rows"] == []
    assert "bench_returns" in res.data["reason"]


def test_weights_not_summing_to_one_are_rejected():
    port_w = {"Technology": 0.45, "Financials": 0.20}  # sums to 0.65
    bench_w = {"Technology": 0.30, "Financials": 0.20, "Healthcare": 0.10}  # sums to 0.60
    res = _run(port_weights=port_w, port_returns={"Technology": 0.18, "Financials": 0.05},
               bench_weights=bench_w, bench_returns={"Technology": 0.12, "Financials": 0.04, "Healthcare": 0.05})
    assert res.data["status"] == "input_error"
    assert res.data["rows"] == []
    assert "sum" in res.data["reason"].lower()


def test_effects_reconcile_to_active_return_for_valid_inputs():
    # Every sector in either map carries an explicit return on both sides (no implied 0%).
    res = _run(port_weights=FULL_PORT_W, port_returns=FULL_PORT_R, bench_weights=BENCH_W, bench_returns=BENCH_R)
    assert res.data["status"] == "ok"
    t = res.data["totals"]
    assert t["allocation"] + t["selection"] + t["interaction"] == pytest.approx(t["active_return"], abs=1e-12)
    rows = {row["sector"]: row for row in res.data["rows"]}
    # The supplied portfolio return for the unheld sector is used as given, never replaced by 0.
    assert rows["Industrials"]["port_return"] == pytest.approx(0.06)
    assert rows["Industrials"]["port_weight"] == 0.0


def test_bench_only_sector_without_portfolio_return_is_rejected():
    # Industrials is benchmark-only (16%). Its portfolio return is absent, so it must not be read as 0%.
    res = _run(port_weights=FULL_PORT_W, port_returns=PORT_R, bench_weights=BENCH_W, bench_returns=BENCH_R)
    assert res.data["status"] == "input_error"
    assert "Industrials" in res.data["reason"]
    assert "port_returns" in res.data["reason"]
    assert res.data["rows"] == []
    assert "active_return" not in res.data["totals"]


def test_portfolio_only_sector_without_benchmark_return_is_rejected():
    # Crypto is held by the portfolio (5%) but is not in the benchmark and has no benchmark return.
    port_w = {**PORT_W, "Technology": 0.40, "Crypto": 0.05}
    port_r = {**FULL_PORT_R, "Crypto": 0.25}
    res = _run(port_weights=port_w, port_returns=port_r, bench_weights=BENCH_W, bench_returns=BENCH_R)
    assert res.data["status"] == "input_error"
    assert "Crypto" in res.data["reason"]
    assert "bench_returns" in res.data["reason"]
    assert res.data["rows"] == []


def test_weighted_sector_without_a_return_is_rejected():
    # Technology carries 45% of the portfolio but no portfolio return is supplied.
    port_r = {k: v for k, v in PORT_R.items() if k != "Technology"}
    res = _run(port_weights=PORT_W, port_returns=port_r, bench_weights=BENCH_W, bench_returns=BENCH_R)
    assert res.data["status"] == "input_error"
    assert "Technology" in res.data["reason"]
    assert res.data["rows"] == []


def test_every_missing_return_is_listed_not_only_the_first():
    # Industrials (bench-only) and Technology (held) both lack portfolio returns: both must be named.
    port_r = {k: v for k, v in FULL_PORT_R.items() if k not in ("Technology", "Industrials")}
    res = _run(port_weights=FULL_PORT_W, port_returns=port_r, bench_weights=BENCH_W, bench_returns=BENCH_R)
    assert res.data["status"] == "input_error"
    assert "Technology" in res.data["reason"]
    assert "Industrials" in res.data["reason"]
