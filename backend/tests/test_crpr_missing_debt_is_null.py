"""CRPR follow-up — a filer with no debt concept must not be read as zero debt.

When SEC companyfacts report none of LongTermDebt, LongTermDebtNoncurrent or
ShortTermBorrowings, the old code summed an empty list and added 0.0, so gross
debt was 0, leverage was 0.0 and a rating (AA) was derived with no warning.
Missing debt is a null input: no leverage, no implied rating, and a warning.

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
_FY = ("2025-09-28", "2026-09-26")


def _flow(val: float, start: str, end: str) -> dict[str, Any]:
    return {"val": val, "start": start, "end": end, "filed": "2026-11-03", "fp": "FY", "form": "10-K"}


class _FakeClient:
    def __init__(self, facts: dict[str, Any]) -> None:
        self._facts = facts

    async def get(self, url: str, **_: Any) -> _Resp:
        if "company_tickers" in url:
            return _Resp(_TICKERS)
        if "companyfacts" in url:
            return _Resp(self._facts)
        raise AssertionError(f"unexpected network call in test: {url}")


def _run_with(monkeypatch: pytest.MonkeyPatch, us_gaap: dict[str, list[dict[str, Any]]]) -> Any:
    facts = {"facts": {"us-gaap": {name: {"units": {"USD": items}} for name, items in us_gaap.items()}}}
    client = _FakeClient(facts)

    async def _get_client() -> _FakeClient:
        return client

    monkeypatch.setattr(_stubs, "get_client", _get_client)
    return asyncio.run(CRPRFunction().execute(issuer="AAPL"))


def _no_debt_filer() -> dict[str, list[dict[str, Any]]]:
    # Positive annual EBIT, D&A and interest, but no debt concept at all.
    return {
        "OperatingIncomeLoss": [_flow(120e9, *_FY)],
        "DepreciationDepletionAndAmortization": [_flow(10e9, *_FY)],
        "InterestExpense": [_flow(4e9, *_FY)],
    }


def test_missing_all_debt_concepts_is_null_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    res = _run_with(monkeypatch, _no_debt_filer())
    summary = res.data["summary"]
    assert summary["gross_debt_usd"] is None, summary
    assert summary["leverage_x"] is None, summary
    assert res.data["status"] != "ok", res.data
    assert res.data["rows"] == [], res.data["rows"]
    assert summary["implied_bucket"] == "n/a", summary


def test_missing_all_debt_concepts_warns_about_debt(monkeypatch: pytest.MonkeyPatch) -> None:
    res = _run_with(monkeypatch, _no_debt_filer())
    assert any("debt" in w.lower() for w in res.warnings), res.warnings
