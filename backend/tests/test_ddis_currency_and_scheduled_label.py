"""DDIS regression tests (offline).

* DDIS#1 - a non-USD currency is an explicit input error on both the manual
  and the live path; amounts are USD billions and are never relabelled.
* DDIS#2 - the live summary reports the sum of scheduled maturities as
  ``scheduled_principal_usd_bn`` and the reported balance-sheet long-term debt
  separately, so the "total" is not presented as balance-sheet debt.

The SEC companyfacts payload is a fixture copied from the Apple FY2026 10-K
concepts (values in USD). No network is used.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.functions.bond import _stubs
from showme.engine.functions.bond._stubs import DDISFunction


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


_END = "2026-09-26"


def _usd_fact(val: float) -> dict[str, Any]:
    return {"val": val, "end": _END, "form": "10-K", "fy": 2026, "fp": "FY", "filed": "2026-10-30"}


_AAPL_FACTS: dict[str, Any] = {
    "facts": {
        "us-gaap": {
            "LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths": {"units": {"USD": [_usd_fact(9_991_000_000)]}},
            "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo": {"units": {"USD": [_usd_fact(9_300_000_000)]}},
            "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree": {"units": {"USD": [_usd_fact(5_175_000_000)]}},
            "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFour": {"units": {"USD": [_usd_fact(4_956_000_000)]}},
            "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFive": {"units": {"USD": [_usd_fact(3_750_000_000)]}},
            "LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive": {"units": {"USD": [_usd_fact(45_506_000_000)]}},
            "LongTermDebt": {"units": {"USD": [_usd_fact(78_114_000_000)]}},
            "LongTermDebtNoncurrent": {"units": {"USD": [_usd_fact(68_208_000_000)]}},
            "LongTermDebtCurrent": {"units": {"USD": [_usd_fact(9_906_000_000)]}},
        }
    }
}


class _Resp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _SecClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def get(self, url: str, headers: dict[str, str] | None = None) -> _Resp:
        return _Resp(self._payload)


@pytest.fixture
def sec_aapl(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _client() -> _SecClient:
        return _SecClient(_AAPL_FACTS)

    async def _cik(_client: Any, _ticker: str) -> str:
        return "0000320193"

    monkeypatch.setattr(_stubs, "get_client", _client)
    monkeypatch.setattr(_stubs, "_sec_lookup_cik", _cik)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom() -> None:
        raise AssertionError("a non-USD request must not reach the SEC client")

    monkeypatch.setattr(_stubs, "get_client", _boom)


# ---------------------------------------------------------------- DDIS#1 ---


def test_non_usd_manual_schedule_is_rejected_not_relabelled() -> None:
    result = _run(DDISFunction().execute(
        issuer="ACME",
        currency="EUR",
        maturities=[{"bucket": "0-1Y", "tenor_years": 0.5, "amount_usd_bn": 10.0}],
    ))
    assert result.data["status"] == "input_error", result.data
    assert result.data["rows"] == []
    assert "USD" in result.data["reason"]
    assert result.data["summary"]["currency"] == "EUR"


def test_non_usd_live_request_is_rejected_before_any_fetch(no_network: None) -> None:
    result = _run(DDISFunction().execute(issuer="AAPL", currency="EUR"))
    assert result.data["status"] == "input_error"
    assert result.data["rows"] == []


def test_lowercase_usd_is_accepted_for_manual_schedule() -> None:
    result = _run(DDISFunction().execute(
        issuer="ACME",
        currency="usd",
        maturities=[{"bucket": "0-1Y", "tenor_years": 0.5, "amount_usd_bn": 2.0}],
    ))
    assert result.data["status"] == "ok"
    assert result.data["summary"]["currency"] == "USD"


# ---------------------------------------------------------------- DDIS#2 ---


def test_live_summary_separates_scheduled_principal_from_balance_sheet(sec_aapl: None) -> None:
    result = _run(DDISFunction().execute(issuer="AAPL"))
    assert result.data["status"] == "ok", result.data
    summary = result.data["summary"]
    assert summary["scheduled_principal_usd_bn"] == pytest.approx(78.678, abs=1e-6)
    assert summary["balance_sheet_long_term_debt_usd_bn"] == pytest.approx(78.114, abs=1e-6)
    assert summary["balance_sheet_as_of"] == _END
    assert summary["scheduled_principal_usd_bn"] != summary["balance_sheet_long_term_debt_usd_bn"]


def test_balance_sheet_falls_back_to_current_plus_noncurrent(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = {"facts": {"us-gaap": {k: v for k, v in _AAPL_FACTS["facts"]["us-gaap"].items() if k != "LongTermDebt"}}}

    async def _client() -> _SecClient:
        return _SecClient(facts)

    async def _cik(_client: Any, _ticker: str) -> str:
        return "0000320193"

    monkeypatch.setattr(_stubs, "get_client", _client)
    monkeypatch.setattr(_stubs, "_sec_lookup_cik", _cik)
    result = _run(DDISFunction().execute(issuer="AAPL"))
    assert result.data["summary"]["balance_sheet_long_term_debt_usd_bn"] == pytest.approx(78.114, abs=1e-6)


def test_manual_schedule_summary_states_it_is_scheduled_principal() -> None:
    result = _run(DDISFunction().execute(
        issuer="ACME",
        maturities=[{"bucket": "0-1Y", "tenor_years": 0.5, "amount_usd_bn": 1.0}],
    ))
    summary = result.data["summary"]
    assert summary["scheduled_principal_usd_bn"] == pytest.approx(1.0)
    assert summary["balance_sheet_long_term_debt_usd_bn"] is None


def test_ddis_seed_headline_card_is_scheduled_principal() -> None:
    from showme.manifest.seeds.ddis_seed import ddis

    slots = {slot.key: slot for slot in ddis.card_schema.slots}
    assert "scheduled_principal_usd_bn" in slots
    assert "Scheduled" in slots["scheduled_principal_usd_bn"].label
    assert "total_debt_usd_bn" not in slots


def test_non_usd_row_currency_in_manual_schedule_is_rejected() -> None:
    # A top-level USD request must not carry rows whose own currency is EUR:
    # those amounts would be USD-named figures for EUR principal.
    result = _run(DDISFunction().execute(
        issuer="ACME",
        currency="USD",
        maturities=[
            {"bucket": "0-1Y", "tenor_years": 0.5, "amount_usd_bn": 10.0, "currency": "USD"},
            {"bucket": "1-3Y", "tenor_years": 2.0, "amount_usd_bn": 30.0, "currency": "EUR"},
        ],
    ))
    assert result.data["status"] == "input_error", result.data
    assert result.data["rows"] == []
    assert "EUR" in result.data["reason"]


def test_ddis_seed_currency_options_are_usd_only() -> None:
    # The handler refuses every non-USD value, so the seed must not offer any.
    from showme.manifest.seeds.ddis_seed import ddis

    currency = next(spec for spec in ddis.inputs if spec.name == "currency")
    assert list(currency.options) == ["USD"]
