"""CRPR#5 / CRPR#6 — debt fallback and coverage inputs.

CRPR#5: when LongTermDebtNoncurrent is absent, the fallback LongTermDebt already
includes the current portion (Apple: 78.114bn = 68.208bn noncurrent + 9.906bn
current, verified against companyfacts). Adding LongTermDebtCurrent on top
double counted it.

CRPR#6: the figure labelled interest coverage was EBITDA / interest, while the
conventional ratio is EBIT / interest expense. A missing OperatingIncomeLoss was
also silently treated as zero, so leverage was computed on D&A alone. Missing
inputs must yield null metrics and an honest empty state, never a rating.

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


def _flow(val: float, start: str, end: str) -> dict[str, Any]:
    return {"val": val, "start": start, "end": end, "filed": "2026-11-03", "fp": "FY", "form": "10-K"}


def _instant(val: float, end: str) -> dict[str, Any]:
    return {"val": val, "end": end, "filed": "2026-11-03", "form": "10-K"}


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


def _run_with(monkeypatch: pytest.MonkeyPatch, facts: dict[str, Any]) -> Any:
    client = _FakeClient(facts)

    async def _get_client() -> _FakeClient:
        return client

    monkeypatch.setattr(_stubs, "get_client", _get_client)
    return asyncio.run(CRPRFunction().execute(issuer="AAPL"))


_FY = ("2025-09-28", "2026-09-26")


def _base(**overrides: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    base: dict[str, list[dict[str, Any]]] = {
        "OperatingIncomeLoss": [_flow(120e9, *_FY)],
        "DepreciationDepletionAndAmortization": [_flow(10e9, *_FY)],
        "InterestExpense": [_flow(4e9, *_FY)],
    }
    base.update(overrides)
    return base


# ---- CRPR#5: the LongTermDebt fallback already includes the current portion --


def test_fallback_long_term_debt_is_not_added_to_current_portion(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only the total LongTermDebt (100bn, current portion included) is reported.
    facts = _facts(_base(
        LongTermDebt=[_instant(100e9, "2026-09-26")],
        LongTermDebtCurrent=[_instant(10e9, "2026-09-26")],
    ))
    res = _run_with(monkeypatch, facts)
    assert res.data["summary"]["gross_debt_usd"] == pytest.approx(100e9), res.data["summary"]


def test_noncurrent_debt_still_adds_the_current_portion(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = _facts(_base(
        LongTermDebtNoncurrent=[_instant(68e9, "2026-09-26")],
        LongTermDebtCurrent=[_instant(10e9, "2026-09-26")],
    ))
    res = _run_with(monkeypatch, facts)
    assert res.data["summary"]["gross_debt_usd"] == pytest.approx(78e9), res.data["summary"]


# ---- CRPR#6: coverage is EBIT / interest, and missing EBIT is not zero -------


def test_interest_coverage_is_ebit_over_interest(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = _facts(_base(LongTermDebtNoncurrent=[_instant(68e9, "2026-09-26")]))
    res = _run_with(monkeypatch, facts)
    # EBIT 120bn / interest 4bn = 30x. EBITDA-based coverage would be 32.5x.
    assert res.data["summary"]["interest_coverage_x"] == pytest.approx(30.0), res.data["summary"]


def test_missing_operating_income_is_not_treated_as_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = _facts({
        "DepreciationDepletionAndAmortization": [_flow(10e9, *_FY)],
        "InterestExpense": [_flow(4e9, *_FY)],
        "LongTermDebtNoncurrent": [_instant(68e9, "2026-09-26")],
    })
    res = _run_with(monkeypatch, facts)
    summary = res.data["summary"]
    assert summary["leverage_x"] is None, summary
    assert summary["ebitda_proxy_usd"] is None, summary
    assert summary["interest_coverage_x"] is None, summary
    assert res.data["status"] != "ok", res.data
    assert res.data["rows"] == [], res.data["rows"]
    assert any("EBIT" in w or "OperatingIncomeLoss" in w for w in res.warnings), res.warnings


def test_missing_depreciation_does_not_produce_a_leverage_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = _facts({
        "OperatingIncomeLoss": [_flow(120e9, *_FY)],
        "InterestExpense": [_flow(4e9, *_FY)],
        "LongTermDebtNoncurrent": [_instant(68e9, "2026-09-26")],
    })
    res = _run_with(monkeypatch, facts)
    summary = res.data["summary"]
    assert summary["leverage_x"] is None, summary
    assert summary["ebitda_proxy_usd"] is None, summary
    assert res.data["status"] != "ok", res.data
    assert any("D&A" in w for w in res.warnings), res.warnings
