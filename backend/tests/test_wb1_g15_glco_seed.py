"""WB1-G15 — GLCO seed declares the unpublished fields honestly (offline).

GLCO#3: open interest and the contract month are null with a reason on the
keyless feed. The manifest must not describe them as always-populated fields.
"""

from __future__ import annotations


def _glco_entry():
    from showme.manifest.registry import REGISTRY
    from showme.manifest.seeds import load_seeds

    load_seeds()
    return REGISTRY.get("GLCO")


def test_glco_seed_declares_reason_fields_for_unpublished_columns() -> None:
    field_dict = _glco_entry().field_dict
    assert "rows[].open_interest_reason" in field_dict
    assert "rows[].contract_month_reason" in field_dict


def test_glco_seed_describes_nullable_open_interest_and_contract_month() -> None:
    field_dict = _glco_entry().field_dict
    assert "null" in field_dict["rows[].contract_month"].description.lower()
    assert "null" in field_dict["rows[].open_interest"].description.lower()
    assert "continuous" in field_dict["rows[].contract_month"].description.lower()
