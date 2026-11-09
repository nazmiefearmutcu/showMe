"""CRPR debt as-of labelling.

Debt is a point-in-time balance taken from its own concept, so it can be dated
differently from the annual EBIT used in the same leverage ratio. The output
must state the debt date, and must warn when a debt component predates the EBIT
period, instead of showing only the EBIT date.

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


def _instant(val: float, end: str, filed: str = "2026-11-03") -> dict[str, Any]:
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


def _run_with(monkeypatch: pytest.MonkeyPatch, facts: dict[str, Any]) -> Any:
    client = _FakeClient(facts)

    async def _get_client() -> _FakeClient:
        return client

    monkeypatch.setattr(_stubs, "get_client", _get_client)
    return asyncio.run(CRPRFunction().execute(issuer="AAPL"))


def _base(**overrides: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    base: dict[str, list[dict[str, Any]]] = {
        "OperatingIncomeLoss": [_flow(120e9, *_FY)],
        "DepreciationDepletionAndAmortization": [_flow(10e9, *_FY)],
        "InterestExpense": [_flow(4e9, *_FY)],
    }
    base.update(overrides)
    return base


def test_debt_as_of_is_reported_when_debt_matches_the_ebit_period(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = _facts(_base(
        LongTermDebtNoncurrent=[_instant(68e9, "2026-09-26")],
        LongTermDebtCurrent=[_instant(10e9, "2026-09-26")],
    ))
    res = _run_with(monkeypatch, facts)
    summary = res.data["summary"]
    assert summary["gross_debt_as_of"] == "2026-09-26", summary
    assert not any("predate" in w for w in res.warnings), res.warnings


def test_stale_debt_component_is_dated_and_warned(monkeypatch: pytest.MonkeyPatch) -> None:
    # Short-term borrowings were last reported two years before the EBIT period.
    facts = _facts(_base(
        LongTermDebtNoncurrent=[_instant(68e9, "2026-09-26")],
        ShortTermBorrowings=[_instant(5e9, "2024-09-28")],
    ))
    res = _run_with(monkeypatch, facts)
    summary = res.data["summary"]
    # The debt date is the newest component, and the stale component is named with its own date.
    assert summary["gross_debt_as_of"] == "2026-09-26", summary
    assert any("ShortTermBorrowings" in w and "2024-09-28" in w and "predate" in w for w in res.warnings), res.warnings
    assert res.data["rows"], res.data  # still a model-implied rating; the staleness is labelled, not hidden


def test_debt_as_of_is_in_the_rationale(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = _facts(_base(LongTermDebtNoncurrent=[_instant(68e9, "2026-09-26")]))
    res = _run_with(monkeypatch, facts)
    assert "debt as of 2026-09-26" in res.data["rows"][0]["rationale"], res.data["rows"]
