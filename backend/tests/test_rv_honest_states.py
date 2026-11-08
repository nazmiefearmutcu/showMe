"""RV honesty and labelling regressions (wc1-g37: T10 offline_live_claim, RV#2, RV#3).

* With the refdata provider failing, RV must not return an ``ok`` payload whose
  rows are all-None yet labelled live (the offline audit's offline_live_claim).
* ``debt_equity`` is yfinance percent units; RV delivers a ratio (84.286 -> 0.84286).
* ``peer_source`` says where the peer set came from, and ``sources`` lists only
  providers that actually contributed.

The network is replaced by in-memory fakes shaped like the yfinance and finnhub
adapters. No socket is opened.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from showme import server
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.rv import RVFunction


def _full_raw(pe: float = 25.0, de: float | None = 84.286) -> dict[str, Any]:
    return {
        "trailingPE": pe,
        "forwardPE": pe * 0.9,
        "priceToBook": 40.0,
        "priceToSalesTrailing12Months": 8.0,
        "enterpriseToEbitda": 22.0,
        "returnOnEquity": 1.5,
        "returnOnAssets": 0.28,
        "debtToEquity": de,
        "marketCap": 2.5e12,
        "dividendYield": 0.32,
        "dividendRate": 1.08,
        "currentPrice": 342.37,
    }


class _YF:
    """Fake yfinance adapter: ``by_symbol`` raw dicts, ``default`` otherwise."""

    def __init__(self, by_symbol: dict[str, dict[str, Any]], default: dict[str, Any] | None = None,
                 raise_all: bool = False) -> None:
        self._by = by_symbol
        self._default = default or {}
        self._raise_all = raise_all

    async def fetch(self, request: Any) -> Any:
        if self._raise_all:
            raise ConnectionError("connection refused")
        raw = self._by.get(request.instrument.symbol, self._default)
        # The real adapter swallows info errors and returns an empty raw dict
        # carrying info_error; mirror that shape exactly.
        return SimpleNamespace(market_cap=None, extras={"raw": dict(raw)})


class _Finnhub:
    def __init__(self, peers: list[str] | None = None, *, down: bool = False) -> None:
        self._peers = list(peers or [])
        self._down = down

    async def peers(self, symbol: str) -> list[str]:
        if self._down:
            raise ConnectionError("finnhub down")
        return list(self._peers)


def _deps(yf: Any, finnhub: Any = None) -> SimpleNamespace:
    return SimpleNamespace(yfinance=yf, finnhub=finnhub)


def _run(yf: Any, finnhub: Any = None, symbol: str = "AAPL", **params: Any) -> Any:
    fn = RVFunction(_deps(yf, finnhub))
    inst = Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)
    return asyncio.run(fn.execute(instrument=inst, **params))


def _row(res: Any, symbol: str) -> dict[str, Any]:
    return next(r for r in res.data["rows"] if r["symbol"] == symbol)


# ── T10 offline_live_claim ─────────────────────────────────────────────


def test_rv_offline_refdata_failures_are_not_reported_live():
    # Every refdata call returns the adapter's info_error shape (network cut).
    res = _run(_YF({}, default={"info_error": "connection refused"}))
    assert res.data["status"] == "provider_unavailable"
    assert all(r.get("source_mode") == "provider_unavailable" for r in res.data["rows"])
    assert "yfinance" not in res.sources
    payload = server.enforce_live_or_label_synthetic("RV", {"symbol": "AAPL"}, res.to_dict())
    assert payload["data_state"] != "live", payload["data_state"]


def test_rv_raising_refdata_is_provider_unavailable_not_live():
    res = _run(_YF({}, raise_all=True))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["reason"]
    payload = server.enforce_live_or_label_synthetic("RV", {"symbol": "AAPL"}, res.to_dict())
    assert payload["data_state"] != "live", payload["data_state"]


def test_rv_target_without_multiples_is_unavailable_even_when_peers_resolve():
    yf = _YF({"AAPL": {"info_error": "timeout"}}, default=_full_raw())
    res = _run(yf, peers=["MSFT", "GOOGL"])
    assert res.data["status"] == "provider_unavailable"
    assert res.data["peers"] == ["MSFT", "GOOGL"]


# ── RV#2 debt-to-equity units ──────────────────────────────────────────


def test_rv_debt_to_equity_is_delivered_as_a_ratio_not_percent():
    # yfinance debtToEquity is percent: 84.286 = 0.84286x, 12 = 0.12x.
    yf = _YF({"AAPL": _full_raw(de=84.286), "MSFT": _full_raw(de=12.0)})
    res = _run(yf, peers=["MSFT"])
    assert _row(res, "AAPL")["debt_equity"] == pytest.approx(0.84286)
    assert _row(res, "MSFT")["debt_equity"] == pytest.approx(0.12)


def test_rv_missing_debt_to_equity_stays_none():
    yf = _YF({"AAPL": _full_raw(de=None), "MSFT": _full_raw()})
    res = _run(yf, peers=["MSFT"])
    assert _row(res, "AAPL")["debt_equity"] is None


# ── RV#3 peer source and sources ───────────────────────────────────────


def test_rv_default_peers_are_labelled_as_the_reference_map_not_finnhub():
    res = _run(_YF({}, default=_full_raw()), finnhub=None)
    assert res.data["peers"] == ["MSFT", "GOOGL", "NVDA", "META", "AMZN", "TSLA"]
    assert res.data["peer_source"] == "reference_sector_map"
    assert res.metadata["peer_source"] == "reference_sector_map"
    assert "finnhub" not in res.sources
    assert "reference_sector_map" in res.sources


def test_rv_finnhub_peers_are_labelled_finnhub_and_listed_as_a_source():
    res = _run(_YF({}, default=_full_raw()), finnhub=_Finnhub(["msft", "GOOGL", "AAPL"]))
    assert res.data["peers"] == ["MSFT", "GOOGL"]
    assert res.data["peer_source"] == "finnhub"
    assert "finnhub" in res.sources
    assert "reference_sector_map" not in res.sources


def test_rv_failed_finnhub_falls_back_without_claiming_finnhub():
    res = _run(_YF({}, default=_full_raw()), finnhub=_Finnhub(down=True))
    assert res.data["peer_source"] == "reference_sector_map"
    assert "finnhub" not in res.sources


def test_rv_user_peers_are_labelled_user_input_and_skip_finnhub():
    res = _run(_YF({}, default=_full_raw()), finnhub=_Finnhub(["NVDA"]), peers=["msft"])
    assert res.data["peers"] == ["MSFT"]
    assert res.data["peer_source"] == "user_input"
    assert "finnhub" not in res.sources
