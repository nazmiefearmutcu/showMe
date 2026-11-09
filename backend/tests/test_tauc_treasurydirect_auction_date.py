"""TAUC#1 regression: TreasuryDirect rows must keep their auction date.

The live TreasuryDirect feed (/TA_WS/securities/announced and /auctioned)
leaves ``auctionDate`` null on every row and carries the auction day in
``competitiveAuctionCloseDate`` (verified against the feed 2026-11-08: 250/250
rows null on auctionDate, 250/250 populated on competitiveAuctionCloseDate).
The adapter used to read only ``auctionDate``, so ``upcoming()`` and
``recent()`` dropped every row and TAUC reported an empty calendar as ok.

No network: ``httpx.AsyncClient`` is replaced by a fake that serves fixtures.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from showme.engine.data_sources.bond import treasury_auctions_adapter as adapter_mod
from showme.engine.data_sources.bond.treasury_auctions_adapter import TreasuryAuctionsAdapter


def _iso(days: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


def _row(**overrides: Any) -> dict[str, Any]:
    base = {
        "auctionDate": None,
        "issueDate": None,
        "maturityDate": None,
        "securityType": "Bill",
        "securityTerm": "13-Week",
        "offeringAmount": "70000000000",
        "cusip": "912797TC1",
        "competitiveAuctionCloseDate": None,
    }
    base.update(overrides)
    return base


_FEED: dict[str, list[dict[str, Any]]] = {
    "announced": [
        # in the 30-day window, close date only (the live shape)
        _row(competitiveAuctionCloseDate=f"{_iso(3)}T00:00:00", cusip="ANN_IN"),
        # beyond the window
        _row(competitiveAuctionCloseDate=f"{_iso(90)}T00:00:00", cusip="ANN_FAR"),
        # no date at all: cannot be placed on a calendar
        _row(cusip="ANN_NODATE"),
    ],
    "auctioned": [
        _row(competitiveAuctionCloseDate=f"{_iso(-2)}T00:00:00", cusip="AUC_IN"),
        _row(competitiveAuctionCloseDate=f"{_iso(-200)}T00:00:00", cusip="AUC_OLD"),
        # explicit auctionDate must win over the close date
        _row(auctionDate=f"{_iso(-4)}T00:00:00", competitiveAuctionCloseDate=f"{_iso(-6)}T00:00:00", cusip="AUC_EXPLICIT"),
    ],
}


class _Resp:
    status_code = 200

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def get(self, url: str, **_: Any) -> _Resp:
        kind = url.rsplit("/", 1)[-1]
        assert kind in _FEED, f"unexpected TreasuryDirect kind: {kind}"
        return _Resp(_FEED[kind])


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter_mod.httpx, "AsyncClient", _FakeAsyncClient)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_upcoming_keeps_rows_that_only_carry_a_close_date() -> None:
    rows = _run(TreasuryAuctionsAdapter().upcoming(horizon_days=30))
    cusips = [r["cusip"] for r in rows]
    assert cusips == ["ANN_IN"], rows
    assert rows[0]["auction_date"] == _iso(3)


def test_recent_keeps_rows_that_only_carry_a_close_date() -> None:
    rows = _run(TreasuryAuctionsAdapter().recent(days=30))
    cusips = [r["cusip"] for r in rows]
    # AUC_OLD is outside the look-back; AUC_EXPLICIT uses its explicit auctionDate (-4d)
    assert cusips == ["AUC_IN", "AUC_EXPLICIT"], rows
    assert rows[0]["auction_date"] == _iso(-2)
    assert rows[1]["auction_date"] == _iso(-4)


def test_fetch_exposes_auction_date_from_close_date_when_auction_date_null() -> None:
    rows = _run(TreasuryAuctionsAdapter().fetch(_request("announced")))
    by_cusip = {r["cusip"]: r for r in rows}
    assert by_cusip["ANN_IN"]["auction_date"] == _iso(3)
    assert by_cusip["ANN_NODATE"]["auction_date"] is None


def _request(kind: str) -> Any:
    from showme.engine.core.base_data_source import DataKind, DataRequest

    return DataRequest(kind=DataKind.EVENTS, instrument=None, extra={"kind": kind})
