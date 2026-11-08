"""DDIS#2 follow-up (offline): the balance-sheet long-term-debt fallback must not
sum two facts with different end dates under one as-of date."""
from __future__ import annotations

from typing import Any

from showme.engine.functions.bond._stubs import _balance_sheet_long_term_debt


def _fact(val: float, end: str) -> dict[str, Any]:
    return {"val": val, "end": end, "form": "10-K", "fy": 2026, "fp": "FY"}


def _facts(**concepts: list[dict[str, Any]]) -> dict[str, Any]:
    return {"facts": {"us-gaap": {k: {"units": {"USD": v}} for k, v in concepts.items()}}}


def test_fallback_sums_current_and_noncurrent_when_end_dates_match() -> None:
    facts = _facts(
        LongTermDebtCurrent=[_fact(9_906_000_000, "2026-09-26")],
        LongTermDebtNoncurrent=[_fact(68_208_000_000, "2026-09-26")],
    )
    value, as_of = _balance_sheet_long_term_debt(facts)
    assert value == 78.114
    assert as_of == "2026-09-26"


def test_fallback_refuses_when_end_dates_differ() -> None:
    facts = _facts(
        LongTermDebtCurrent=[_fact(9_906_000_000, "2026-09-26")],
        LongTermDebtNoncurrent=[_fact(68_208_000_000, "2025-09-27")],
    )
    assert _balance_sheet_long_term_debt(facts) == (None, None)


def test_fallback_uses_latest_point_of_each_concept_when_dates_agree() -> None:
    facts = _facts(
        LongTermDebtCurrent=[_fact(1_000_000_000, "2025-09-27"), _fact(9_906_000_000, "2026-09-26")],
        LongTermDebtNoncurrent=[_fact(2_000_000_000, "2025-09-27"), _fact(68_208_000_000, "2026-09-26")],
    )
    value, as_of = _balance_sheet_long_term_debt(facts)
    assert value == 78.114
    assert as_of == "2026-09-26"
