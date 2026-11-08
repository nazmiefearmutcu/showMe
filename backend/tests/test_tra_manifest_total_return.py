"""TRA#4: the TRA manifest must describe the served Total Return Analysis.

The manifest registered under TRA used to be a per-fill broker ledger
("Transaction Analysis", credential_id, date_range, side_filter...) while the
executing class is Total Return Analysis with years and reference inputs.
"""

from __future__ import annotations

from showme.engine.functions.portfolio._more import TRAFunction
from showme.manifest import REGISTRY, load_seeds


def setup_module() -> None:
    load_seeds()


def test_manifest_name_matches_served_function() -> None:
    entry = REGISTRY.get("TRA")
    assert entry.name == TRAFunction.name == "Total Return Analysis"


def test_manifest_inputs_are_the_served_inputs() -> None:
    entry = REGISTRY.get("TRA")
    names = {i.name for i in entry.inputs}
    assert {"years", "reference"} <= names
    # The fill-ledger inputs belonged to a different, unserved function.
    assert "credential_id" not in names
    assert "side_filter" not in names


def test_manifest_intent_describes_total_return() -> None:
    entry = REGISTRY.get("TRA")
    assert "total return" in entry.intent.lower()
    assert "fill" not in entry.intent.lower()


def test_function_has_description_for_the_catalog() -> None:
    assert (TRAFunction.description or "").strip()


def test_manifest_must_have_fields_are_declared_by_the_handler() -> None:
    entry = REGISTRY.get("TRA")
    for key in entry.output_contract.must_have:
        assert key in {
            "price_return_total", "twr_total", "irr_annualized", "cagr",
            "max_drawdown", "total_return_basis",
        }, key
