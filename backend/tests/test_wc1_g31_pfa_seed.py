"""WC1 g31 PFA#4 — the PFA manifest must describe the Brinson function the handler runs.

The seed used to describe a CAPM/FF factor regression (factor_model, window,
portfolio_source inputs) while pfa.py computes sector Brinson attribution from
four typed maps. The contract must match the handler.
"""
from __future__ import annotations

import pytest

from showme.manifest import REGISTRY, load_seeds
from showme.engine.functions.portfolio.pfa import PFAFunction


def _entry():
    load_seeds()
    return REGISTRY.get("PFA")


def test_pfa_manifest_name_matches_handler_name() -> None:
    entry = _entry()
    # RED before fix: the seed said "Portfolio Factor Analysis".
    assert entry.name == PFAFunction.name


def test_pfa_manifest_inputs_are_the_brinson_maps() -> None:
    names = [i.name for i in _entry().inputs]
    # RED before fix: the seed declared factor_model / window / portfolio_source instead.
    assert names == ["port_weights", "port_returns", "bench_weights", "bench_returns"]
    for forbidden in ("factor_model", "window", "portfolio_source", "risk_free_rate"):
        assert forbidden not in names


def test_pfa_manifest_methodology_is_brinson_not_factor_regression() -> None:
    text = _entry().methodology.lower()
    assert "brinson" in text and "allocation" in text and "selection" in text
    assert "ken french" not in text and "factor regression" not in text and "hac" not in text


# ── PFA#4 units: a percent-kind column or card must read a value already in percent ──


def _valid_run() -> dict:
    import asyncio

    port_w = {"Technology": 0.60, "Financials": 0.40}
    port_r = {"Technology": 0.10, "Financials": 0.02}
    bench_w = {"Technology": 0.50, "Financials": 0.50}
    bench_r = {"Technology": 0.08, "Financials": 0.03}
    return asyncio.run(PFAFunction().execute(
        port_weights=port_w, port_returns=port_r, bench_weights=bench_w, bench_returns=bench_r,
    )).data


def test_pfa_percent_columns_read_percent_values() -> None:
    data = _valid_run()
    rows = data["rows"]
    percent_cols = [c for c in _entry().table_schema.columns if c.kind == "percent"]
    assert percent_cols, "expected percent columns"
    for col in percent_cols:
        # RED before fix: the columns read decimals (0.6) with a % unit, so 0.6 displayed as 0.60%.
        assert col.key.endswith("_pct"), col.key
        base = col.key[: -len("_pct")]
        for row in rows:
            assert row[col.key] == pytest.approx(100.0 * row[base], abs=1e-9), col.key


def test_pfa_percent_cards_read_percent_values() -> None:
    data = _valid_run()
    summary = data["summary"]
    percent_slots = [s for s in _entry().card_schema.slots if s.unit == "%"]
    assert percent_slots, "expected percent card slots"
    for slot in percent_slots:
        assert slot.key.endswith("_pct"), slot.key
        base = slot.key[: -len("_pct")]
        assert summary[slot.key] == pytest.approx(100.0 * summary[base], abs=1e-9), slot.key


def test_pfa_seed_weight_guidance_states_the_fraction_contract() -> None:
    entry = _entry()
    for name in ("port_weights", "bench_weights"):
        desc = next(i.description for i in entry.inputs if i.name == name).lower()
        # RED before fix: the description said "(the pane takes percent)" with no conversion path.
        assert "fraction" in desc and "1.0" in desc
        assert "(the pane takes percent)" not in desc
