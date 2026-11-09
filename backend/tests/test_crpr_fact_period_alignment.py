"""CRPR#3 / CRPR#4 — SEC companyfacts facts must be picked by period.

CRPR#3: interest expense was taken from the most recent InterestExpense entry
regardless of period. Apple's InterestExpense stops at FY2023 while its EBITDA
is FY2026, so the output showed a 2026 coverage built from a 2023 interest
figure. Interest must come from the same fiscal period as the EBIT numerator,
and coverage is null with a warning when no such period exists.

CRPR#4: the fact picker kept the newest end date with no check on duration or
form, so a 9-month YTD operating income (272 days) became the EBITDA numerator.
Flow concepts must be annual (about 365 days); balance-sheet concepts must be
instants.

All network access is patched. The facts are shaped like SEC companyfacts.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.functions.bond import _stubs
from showme.engine.functions.bond._stubs import CRPRFunction


class _Resp:
    status_code = 200

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


_TICKERS = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}


def _flow(val: float, start: str, end: str, filed: str, fp: str = "FY", form: str = "10-K") -> dict[str, Any]:
    return {"val": val, "start": start, "end": end, "filed": filed, "fp": fp, "form": form}


def _instant(val: float, end: str, filed: str) -> dict[str, Any]:
    return {"val": val, "end": end, "filed": filed, "form": "10-K"}


def _facts(us_gaap: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {"facts": {"us-gaap": {name: {"units": {"USD": items}} for name, items in us_gaap.items()}}}


class _FakeClient:
    def __init__(self, facts: dict[str, Any]) -> None:
        self._facts = facts

    async def get(self, url: str, **_: Any) -> _Resp:
        if "company_tickers" in url:
            return _Resp(_TICKERS)
        if "companyfacts" in url:
            return _Resp(self._facts)
        raise AssertionError(f"unexpected network call in test: {url}")


def _run_with(monkeypatch: pytest.MonkeyPatch, facts: dict[str, Any], issuer: str = "AAPL") -> Any:
    client = _FakeClient(facts)

    async def _get_client() -> _FakeClient:
        return client

    monkeypatch.setattr(_stubs, "get_client", _get_client)
    return asyncio.run(CRPRFunction().execute(issuer=issuer))


# ---- CRPR#3: interest must share the EBIT fiscal period ---------------------


def test_stale_interest_expense_is_not_divided_into_current_ebitda(monkeypatch: pytest.MonkeyPatch) -> None:
    # Apple-shaped: InterestExpense only through FY2023, EBIT and D&A through FY2026.
    facts = _facts({
        "OperatingIncomeLoss": [_flow(120_000e6, "2025-09-28", "2026-09-26", "2026-10-31")],
        "DepreciationDepletionAndAmortization": [_flow(11_000e6, "2025-09-28", "2026-09-26", "2026-10-31")],
        "LongTermDebtNoncurrent": [_instant(68_000e6, "2026-09-26", "2026-10-31")],
        "InterestExpense": [_flow(3_933e6, "2022-09-25", "2023-09-30", "2023-11-03")],
    })
    res = _run_with(monkeypatch, facts)
    # Coverage from FY2023 interest over FY2026 EBIT would be 30.5x: a period mismatch, not a ratio.
    assert res.data["summary"]["interest_coverage_x"] is None, res.data["summary"]
    assert res.data["status"] != "ok", res.data
    assert any("period" in w.lower() for w in res.warnings), res.warnings


def test_interest_from_the_same_fiscal_period_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = _facts({
        "OperatingIncomeLoss": [_flow(120_000e6, "2025-09-28", "2026-09-26", "2026-10-31")],
        "DepreciationDepletionAndAmortization": [_flow(11_000e6, "2025-09-28", "2026-09-26", "2026-10-31")],
        "LongTermDebtNoncurrent": [_instant(68_000e6, "2026-09-26", "2026-10-31")],
        "InterestExpense": [
            _flow(3_933e6, "2022-09-25", "2023-09-30", "2023-11-03"),
            _flow(4_000e6, "2025-09-28", "2026-09-26", "2026-10-31"),
        ],
    })
    res = _run_with(monkeypatch, facts)
    summary = res.data["summary"]
    assert summary["interest_expense_usd"] == pytest.approx(4_000e6), summary
    assert summary["interest_period_end"] == "2026-09-26", summary
    assert summary["interest_coverage_x"] is not None, summary


# ---- CRPR#4: flow concepts must be annual, not YTD or quarterly -------------


def test_ytd_operating_income_is_not_used_as_annual_ebit(monkeypatch: pytest.MonkeyPatch) -> None:
    # The newest OperatingIncomeLoss entry is a 9-month YTD (272 days) filed in a 10-Q.
    # The FY2025 annual figure must be used instead.
    facts = _facts({
        "OperatingIncomeLoss": [
            _flow(100_000e6, "2024-09-29", "2025-09-27", "2025-10-31"),
            _flow(122_432e6, "2025-09-28", "2026-06-27", "2026-08-01", fp="Q3", form="10-Q"),
        ],
        "DepreciationDepletionAndAmortization": [
            _flow(10_000e6, "2024-09-29", "2025-09-27", "2025-10-31"),
            _flow(9_973e6, "2025-09-28", "2026-06-27", "2026-08-01", fp="Q3", form="10-Q"),
        ],
        "LongTermDebtNoncurrent": [_instant(68_000e6, "2026-06-27", "2026-08-01")],
        "InterestExpense": [_flow(3_000e6, "2024-09-29", "2025-09-27", "2025-10-31")],
    })
    res = _run_with(monkeypatch, facts)
    assert res.data["summary"]["ebitda_proxy_usd"] == pytest.approx(110_000e6), res.data["summary"]
    assert res.data["summary"]["ebitda_proxy_usd"] != pytest.approx(122_432e6 + 9_973e6)


def test_balance_sheet_debt_ignores_flow_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    # A flow-shaped entry (has a start date) must not be read as a balance-sheet balance.
    facts = _facts({
        "OperatingIncomeLoss": [_flow(100_000e6, "2024-09-29", "2025-09-27", "2025-10-31")],
        "DepreciationDepletionAndAmortization": [_flow(10_000e6, "2024-09-29", "2025-09-27", "2025-10-31")],
        "LongTermDebtNoncurrent": [
            _instant(60_000e6, "2025-09-27", "2025-10-31"),
            {"val": 999_000e6, "start": "2025-09-28", "end": "2026-06-27", "filed": "2026-08-01", "fp": "Q3", "form": "10-Q"},
        ],
        "InterestExpense": [_flow(3_000e6, "2024-09-29", "2025-09-27", "2025-10-31")],
    })
    res = _run_with(monkeypatch, facts)
    assert res.data["summary"]["gross_debt_usd"] == pytest.approx(60_000e6), res.data["summary"]
