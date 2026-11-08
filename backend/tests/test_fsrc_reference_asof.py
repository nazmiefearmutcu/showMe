"""FSRC — curated AUM / YTD carry an as-of stamp (finding FSRC#1, residual).

The curated fund table has no provider as-of date for AUM or YTD. Every row
must carry the table date it was last verified (``aum_as_of`` / ``ytd_as_of``),
the payload warning must state that date, and the field dictionary must
document both stamps. Offline: no quote provider is injected.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.screen._funcs import FSRCFunction, _FUND_REFERENCE_AS_OF


def _reference_result():
    return asyncio.run(FSRCFunction(deps=FunctionDeps()).execute(query="expenseRatio <= 0.001"))


def test_reference_as_of_constant_is_the_verification_date() -> None:
    assert _FUND_REFERENCE_AS_OF == "2026-09-15"


def test_every_curated_row_carries_aum_and_ytd_as_of() -> None:
    out = _reference_result()
    assert out.data["rows"]
    for row in out.data["rows"]:
        assert row.get("aum_as_of") == "2026-09-15", row["symbol"]
        assert row.get("ytd_as_of") == "2026-09-15", row["symbol"]


def test_warning_states_the_as_of_date() -> None:
    out = _reference_result()
    assert any("2026-09-15" in w for w in out.warnings), out.warnings


def test_field_dictionary_documents_as_of_stamps() -> None:
    out = _reference_result()
    fields = {entry["field"]: entry["meaning"] for entry in out.data["field_dictionary"]}
    assert "aum_as_of" in fields and "ytd_as_of" in fields
    assert "2026-09-15" in fields["aum_as_of"]
    assert "2026-09-15" in fields["ytd_as_of"]
    assert "no as-of date" not in fields["aum_usd"].lower()
    assert "no as-of date" not in fields["ytd_return_pct"].lower()
