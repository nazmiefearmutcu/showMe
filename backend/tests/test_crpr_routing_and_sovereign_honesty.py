"""CRPR regressions (G1 bond-api group).

CRPR#1 — the handler declared ``asset_classes=(BOND,)`` while the manifest seed
declares ``[BOND, EQUITY]``. The server compatibility guard rejects any EQUITY
instrument before ``execute`` runs, so every equity issuer returned
``unsupported_asset``. The handler must accept EQUITY and derive the issuer
from the instrument symbol through the SEC EDGAR path.

CRPR#2 — sovereign issuers (hint list in ``_SOVEREIGN_HINTS``) returned a
constant ``AA+`` row labelled ``model_implied`` with ``status: ok``. That is
placeholder data presented as model output. The sovereign branch must return an
honest non-ok state with no rating row.

All network access is patched; no SEC/EDGAR call leaves the process.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
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


def _usd(val: float, end: str) -> dict[str, Any]:
    return {"units": {"USD": [{"val": val, "end": end}]}}


_FACTS = {
    "facts": {
        "us-gaap": {
            "OperatingIncomeLoss": _usd(120e9, "2026-03-31"),
            "DepreciationDepletionAndAmortization": _usd(10e9, "2026-03-31"),
            "LongTermDebtNoncurrent": _usd(40e9, "2026-03-31"),
            "InterestExpense": _usd(4e9, "2026-03-31"),
        }
    }
}


class _FakeClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def get(self, url: str, **_: Any) -> _Resp:
        self.urls.append(url)
        if "company_tickers" in url:
            return _Resp(_TICKERS)
        if "companyfacts" in url:
            return _Resp(_FACTS)
        raise AssertionError(f"unexpected network call in test: {url}")


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    client = _FakeClient()

    async def _get_client() -> _FakeClient:
        return client

    monkeypatch.setattr(_stubs, "get_client", _get_client)
    return client


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---- CRPR#1: EQUITY symbols reach the SEC corporate path -------------------


def test_crpr_accepts_equity_asset_class() -> None:
    # Seed declares [BOND, EQUITY]; the handler must match, otherwise the
    # server guard answers unsupported_asset before execute() is called.
    assert AssetClass.EQUITY in CRPRFunction.asset_classes


def test_crpr_server_guard_admits_equity_symbol() -> None:
    # The route (server.py) calls _function_supports_instrument before execute();
    # an EQUITY symbol such as the pane's AAPL must pass that guard.
    from showme.server import _function_supports_instrument

    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    assert _function_supports_instrument(CRPRFunction, instrument) is True


def test_crpr_equity_symbol_resolves_issuer_from_instrument(fake_client: _FakeClient) -> None:
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    res = _run(CRPRFunction().execute(instrument=instrument))
    assert res.data["status"] == "ok", res.data
    assert res.data["summary"]["issuer"] == "AAPL"
    assert res.data["summary"]["source_mode"] == "model_implied_from_financials"
    assert res.data["rows"][0]["agency"] == "model_implied"
    assert "sec_edgar" in res.sources


# ---- CRPR#2: sovereign issuers are not given a constant AA+ -----------------


@pytest.mark.parametrize("issuer", ["US10Y", "BTP", "US Treasury"])
def test_crpr_sovereign_returns_no_fabricated_rating(issuer: str, fake_client: _FakeClient) -> None:
    res = _run(CRPRFunction().execute(issuer=issuer))
    assert res.data["status"] != "ok", res.data
    assert res.data["rows"] == []
    assert "AA+" not in json.dumps(res.data)
    assert res.data["summary"]["source_mode"] == "sovereign_not_applicable"
    assert res.data.get("reason"), "an honest reason must be given"
    assert res.data.get("next_actions")
    # no SEC call is made for a sovereign that has no CIK
    assert not any("companyfacts" in u for u in fake_client.urls)


def test_crpr_sovereign_with_user_rating_still_echoes_override() -> None:
    rating = {"sp": "AA", "moodys": "Aa2", "fitch": "AA", "outlook": "stable"}
    res = _run(CRPRFunction().execute(issuer="US10Y", rating=rating))
    assert res.data["status"] == "ok"
    assert res.data["summary"]["source_mode"] == "user_input"
    assert res.data["rows"][0]["rating"] == "AA"


# ---- CRPR#1 follow-up: equity symbols are not sovereigns by substring -------


@pytest.mark.parametrize("symbol", ["BOAT", "GOVT"])
def test_equity_symbol_containing_a_sovereign_hint_takes_the_sec_path(symbol: str, fake_client: _FakeClient) -> None:
    # "BOAT" contains "OAT" and "GOVT" is a sovereign-looking ETF symbol. Once
    # EQUITY is admitted they must be looked up as equities, not labelled as
    # sovereign issuers.
    instrument = Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)
    res = _run(CRPRFunction().execute(instrument=instrument))
    assert res.data["summary"]["source_mode"] != "sovereign_not_applicable", res.data
    assert "sovereign" not in str(res.data.get("reason") or "").lower()
    assert any("company_tickers" in u for u in fake_client.urls)
