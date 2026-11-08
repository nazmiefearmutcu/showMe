"""DPF provenance and card contract (P2a-g05, DPF#4).

FINRA is stubbed and yfinance is replaced by an in-memory denominator, so no
test reaches the network. Covers two review findings: an empty FINRA frame must
not be labelled ``finra``, and every card slot the seed declares must be a key
the handler actually returns.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import dpf as dpf_mod
from showme.engine.functions.equity.dpf import DPFFunction
from showme.manifest import REGISTRY, load_seeds


def _run(coro):
    return asyncio.run(coro)


def _instrument() -> Instrument:
    return Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _recent_monday() -> str:
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


class _RowsFinra:
    async def ats_weekly(self, symbol=None, limit=200):
        return pd.DataFrame(
            {
                "weekStartDate": [_recent_monday()],
                "marketParticipantName": ["VENUE-X"],
                "totalWeeklyShareQuantity": [1000],
                "totalWeeklyTradeCount": [10],
            }
        )


class _EmptyFinra:
    async def ats_weekly(self, symbol=None, limit=200):
        return pd.DataFrame()


def _no_denominator(monkeypatch) -> None:
    async def _empty(symbol):
        return {}

    monkeypatch.setattr(dpf_mod, "_weekly_total_volume", _empty)


def _with_denominator(monkeypatch) -> None:
    async def _total(symbol):
        return {_recent_monday(): 10_000.0}

    monkeypatch.setattr(dpf_mod, "_weekly_total_volume", _total)


def test_empty_finra_is_labelled_no_live_source(monkeypatch) -> None:
    _no_denominator(monkeypatch)
    result = _run(DPFFunction(deps=FunctionDeps(finra=_EmptyFinra())).execute(instrument=_instrument()))
    assert result.data["status"] == "provider_unavailable"
    assert not [s for s in result.sources if s != "no_live_source"]  # no provider claimed


def test_finra_rows_without_denominator_cite_only_finra(monkeypatch) -> None:
    _no_denominator(monkeypatch)
    result = _run(DPFFunction(deps=FunctionDeps(finra=_RowsFinra())).execute(instrument=_instrument()))
    assert result.data["status"] == "ok"
    assert result.sources == ["finra"]
    assert result.data["rows"][0]["dark_pool_pct"] is None


def test_finra_rows_with_denominator_cite_finra_and_yfinance(monkeypatch) -> None:
    _with_denominator(monkeypatch)
    result = _run(DPFFunction(deps=FunctionDeps(finra=_RowsFinra())).execute(instrument=_instrument()))
    assert result.sources == ["finra", "yfinance"]
    assert result.data["rows"][0]["dark_pool_pct"] == 10.0


def _card_keys() -> list[str]:
    load_seeds()
    return [slot.key for slot in REGISTRY.get("DPF").card_schema.slots]


def test_every_card_slot_is_returned_by_handler_when_empty(monkeypatch) -> None:
    _no_denominator(monkeypatch)
    result = _run(DPFFunction(deps=FunctionDeps(finra=_EmptyFinra())).execute(instrument=_instrument()))
    missing = [key for key in _card_keys() if key not in result.data]
    assert missing == []


def test_every_card_slot_is_returned_by_handler_with_rows(monkeypatch) -> None:
    _with_denominator(monkeypatch)
    result = _run(DPFFunction(deps=FunctionDeps(finra=_RowsFinra())).execute(instrument=_instrument()))
    missing = [key for key in _card_keys() if key not in result.data]
    assert missing == []
    assert result.data["latest_ats_volume"] == 1000
    assert result.data["latest_dark_pool_pct"] == 10.0
    assert result.data["data_mode"] == "delayed_reference"
    assert result.data["as_of"] == _recent_monday()


def test_cards_are_null_when_no_live_rows(monkeypatch) -> None:
    _no_denominator(monkeypatch)
    result = _run(DPFFunction(deps=FunctionDeps(finra=_EmptyFinra())).execute(instrument=_instrument()))
    assert result.data["latest_dark_pool_pct"] is None
    assert result.data["latest_ats_volume"] is None
    assert result.data["data_mode"] == "provider_unavailable"
    assert result.data["as_of"] is None
