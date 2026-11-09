"""RV#4 — the peer median, own-vs-peer premium and the under-three-peers warning.

The RV seed promises an own-versus-peer median, ``pe_vs_peer_pct`` (premium or
discount to the peer median) and a warning when fewer than three peers resolve.
The handler used to return only per-row ranks, so a two-peer set showed a
"computed" median with no caveat. Network is replaced by in-memory fakes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.rv import RVFunction


def _raw(pe: float) -> dict[str, Any]:
    return {
        "trailingPE": pe,
        "forwardPE": pe * 0.9,
        "priceToBook": 4.0,
        "priceToSalesTrailing12Months": 2.0,
        "enterpriseToEbitda": 12.0,
        "returnOnEquity": 0.2,
        "returnOnAssets": 0.05,
        "debtToEquity": 50.0,
        "marketCap": 1.0e11,
        "dividendYield": 1.0,
        "dividendRate": 1.0,
        "currentPrice": 100.0,
    }


class _YF:
    def __init__(self, by_symbol: dict[str, dict[str, Any]]) -> None:
        self._by = by_symbol

    async def fetch(self, request: Any) -> Any:
        raw = self._by.get(request.instrument.symbol, {})
        return SimpleNamespace(market_cap=None, extras={"raw": dict(raw)})


def _run(by_symbol: dict[str, dict[str, Any]], peers: list[str]) -> Any:
    fn = RVFunction(SimpleNamespace(yfinance=_YF(by_symbol), finnhub=None))
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(fn.execute(instrument=inst, peers=peers))


def test_two_peers_raise_the_under_three_peers_warning() -> None:
    result = _run(
        {"AAPL": _raw(30.0), "MSFT": _raw(10.0), "GOOG": _raw(40.0)},
        peers=["MSFT", "GOOG"],
    )
    assert result.data["status"] == "ok"
    assert result.data["peer_count"] == 2
    assert any("fewer than three" in w for w in result.warnings), result.warnings


def test_three_peers_give_peer_median_and_premium_without_warning() -> None:
    result = _run(
        {
            "AAPL": _raw(30.0),
            "MSFT": _raw(10.0),
            "GOOG": _raw(20.0),
            "AMZN": _raw(40.0),
        },
        peers=["MSFT", "GOOG", "AMZN"],
    )
    assert result.data["status"] == "ok"
    assert result.data["peer_count"] == 3
    assert not any("fewer than three" in w for w in result.warnings), result.warnings
    # Peer P/E median of 10, 20, 40 is 20; the target's 30 is a 50% premium.
    assert result.data["peer_median"]["pe"] == 20.0, result.data["peer_median"]
    assert result.data["peer_median_pe"] == 20.0
    assert abs(result.data["pe_vs_peer_pct"] - 50.0) < 1e-9, result.data["pe_vs_peer_pct"]


def test_negative_pe_peer_is_excluded_from_pe_median() -> None:
    result = _run(
        {
            "AAPL": _raw(30.0),
            "MSFT": _raw(10.0),
            "GOOG": _raw(20.0),
            "AMZN": _raw(-5.0),  # loss-making: no meaningful P/E
        },
        peers=["MSFT", "GOOG", "AMZN"],
    )
    assert result.data["peer_median_pe"] == 15.0, result.data["peer_median_pe"]
