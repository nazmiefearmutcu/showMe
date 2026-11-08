"""UI-6 residual: the RV table's dividend_yield column must declare its unit.

The backend FieldDef contract says dividend yield is a decimal fraction
(0.0123 = 1.23%). The RV seed declared the column as ``kind="percent"`` with
no ``unit``, so the percent renderer read the fraction as percent points and
would show 0.0123 as 0.01%. The EQS seed already declares ``unit="ratio"`` for
the same field; the RV column must match it.
"""
from __future__ import annotations

from showme.manifest import REGISTRY, load_seeds


def _column(code: str, key: str):
    load_seeds()
    entry = REGISTRY.get(code)
    matches = [c for c in entry.table_schema.columns if c.key == key]
    assert len(matches) == 1, f"{code} must declare exactly one {key} column"
    return matches[0]


def test_rv_dividend_yield_column_declares_ratio_unit() -> None:
    col = _column("RV", "dividend_yield")
    assert col.kind == "percent"
    assert col.unit == "ratio", (
        "dividend_yield is a decimal fraction; without unit='ratio' the percent "
        "renderer would show 0.0123 as 0.01%"
    )


def test_rv_dividend_yield_unit_matches_eqs_contract() -> None:
    rv_col = _column("RV", "dividend_yield")
    eqs_col = _column("EQS", "dividend_yield")
    assert rv_col.unit == eqs_col.unit == "ratio"
