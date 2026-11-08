"""DCFS honesty contract (wb1-g20).

Pins:
 - a negative base fair value is not reported as status "ok" and keeps the
   upstream DCF warnings (DCFS#1);
 - the base assumptions the grid was computed from are echoed back so the
   operator can audit the base value (DCFS#5);
 - tornado rows carry the keys the manifest table_schema declares, and the
   spread column is the absolute USD delta, not a percent (DCFS#6).

Network-free: every call passes fcfe / shares_outstanding / wacc explicitly,
so the DCF engine never reaches a provider.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.dcfs import DCFSensitivityFunction
from showme.manifest.registry import REGISTRY
from showme.manifest.seeds import load_seeds


def _nvda() -> Instrument:
    return Instrument(symbol="NVDA", asset_class=AssetClass.EQUITY)


def _run(**params):
    fn = DCFSensitivityFunction(FunctionDeps())
    return asyncio.run(fn.execute(_nvda(), **params))


def test_negative_base_value_is_not_reported_ok() -> None:
    res = _run(fcfe=-1_000_000_000, shares_outstanding=10_000_000, wacc=0.10,
               growth_high=0.05, years=5)
    assert res.data["base_fair_value"] is not None
    assert res.data["base_fair_value"] < 0
    assert res.data["status"] == "negative_value", (
        f"negative base fair value must not be status ok, got {res.data['status']!r}"
    )


def test_upstream_dcf_warnings_are_forwarded() -> None:
    res = _run(fcfe=-1_000_000_000, shares_outstanding=10_000_000, wacc=0.10,
               growth_high=0.05, years=5)
    assert any("free_cash_flow" in w for w in res.warnings), (
        f"base DCF free-cash-flow warning was dropped: {res.warnings}"
    )


def test_base_assumptions_are_echoed() -> None:
    res = _run(fcfe=1_000_000_000, shares_outstanding=10_000_000, wacc=0.10,
               growth_high=0.08, years=5)
    assumptions = res.data.get("assumptions")
    assert isinstance(assumptions, dict), f"assumptions block missing: {sorted(res.data)}"
    assert assumptions["wacc"] == pytest.approx(0.10)
    assert assumptions["g_terminal"] == pytest.approx(0.025)
    assert assumptions["g_high"] == pytest.approx(0.08)
    assert assumptions["years"] == 5
    assert assumptions["starting_fcfe"] == pytest.approx(1_000_000_000)
    assert assumptions["shares_outstanding"] == pytest.approx(10_000_000)
    assert assumptions["wacc_override"] is True
    assert assumptions["fcfe_override"] is True


def test_tornado_rows_match_manifest_table_schema() -> None:
    load_seeds()
    schema = REGISTRY.get("DCFS").table_schema
    keys = [c.key for c in schema.columns]
    assert "delta_pct" not in keys, "tornado emits an absolute USD delta, not a percent"
    res = _run(fcfe=1_000_000_000, shares_outstanding=10_000_000, wacc=0.10,
               growth_high=0.08, years=5)
    tornado = res.data["tornado"]
    assert tornado, "positive base case must produce tornado rows"
    for row in tornado:
        missing = [k for k in keys if k not in row]
        assert not missing, f"tornado row {row.get('input')} lacks schema keys {missing}"
    spread = next(c for c in schema.columns if c.key == "delta")
    assert "USD" in spread.label or "$" in spread.label, spread.label


def test_negative_warning_does_not_claim_a_grid_is_shown() -> None:
    """DCFS#1: the UI withholds the grid for a negative base, so the warning
    must not tell the operator that a grid is displayed."""
    res = _run(fcfe=-1_000_000_000, shares_outstanding=10_000_000, wacc=0.10,
               growth_high=0.05, years=5)
    text = " ".join(res.warnings).lower()
    assert "negative value per share" in text
    assert "grid is shown" not in text, f"warning claims a grid is shown: {res.warnings}"
    assert "for diagnosis" not in text, f"warning promises a diagnostic grid: {res.warnings}"


def test_seed_assumptions_contract_matches_handler_echo() -> None:
    """DCFS#5 / cross-cutting: the seed must describe the echoed assumptions
    the handler really returns, not the retired grid_width / discount_rate keys."""
    load_seeds()
    manifest = REGISTRY.get("DCFS")
    description = manifest.field_dict["assumptions"].description
    assert "grid width" not in description.lower()
    assert "wacc" in description and "g_terminal" in description
    assertion_names = [
        a for t in manifest.semantic_tests for a in t.assertions
    ]
    stale = [a for a in assertion_names if "grid_width" in a or "discount_rate" in a]
    assert not stale, f"semantic tests assert retired echo keys: {stale}"
    assert "assumptions_wacc_equals_input" in assertion_names
