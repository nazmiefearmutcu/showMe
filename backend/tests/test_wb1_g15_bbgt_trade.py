"""WB1-G15 — BBGT ticket validation and pre-trade notional (offline).

* BBGT#2 — side / type / TIF are validated (``input_error``) instead of
  echoed back as a valid preview; an armed invalid side never reaches a broker.
* BBGT#3 — a LIMIT ticket without a positive price is ``input_required``
  and never reaches a broker with ``price=None``.
* BBGT#4 — the pre-trade notional (quantity x limit price, or x an
  indicative last quote when labelled indicative) is emitted, and is null
  with a reason when no reference price exists.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.trade._funcs import BBGTFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
MSFT = Instrument(symbol="MSFT", asset_class=AssetClass.EQUITY)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _RecordingBroker:
    name = "recording_broker"

    def __init__(self) -> None:
        self.placed: list[Any] = []

    async def place_order(self, order: Any) -> str:
        self.placed.append(order)
        return f"ord-{len(self.placed)}"

    async def get_open_orders(self) -> list[Any]:
        return []


def _armed_bbgt() -> tuple[BBGTFunction, _RecordingBroker]:
    fn = BBGTFunction()
    deps = FunctionDeps()
    broker = _RecordingBroker()
    deps.alpaca_broker = broker
    fn.deps = deps
    return fn, broker


class _QuoteFeed:
    """Fake keyless quote adapter: ``fetch`` returns a quote-shaped object."""

    def __init__(self, last: float | None = None, error: Exception | None = None) -> None:
        self.last = last
        self.error = error
        self.calls = 0

    async def fetch(self, request: Any) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return SimpleNamespace(last=self.last, timestamp=None, source="yfinance")


# ── BBGT#2: enum validation ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("field", "value"),
    [("side", "HOLD"), ("tif", "FOO"), ("type", "STOP")],
)
def test_bbgt_rejects_values_outside_ticket_vocabulary(field: str, value: str) -> None:
    kwargs: dict[str, Any] = {"side": "BUY", "type": "LIMIT", "price": 425.0, "tif": "DAY"}
    kwargs[field] = value
    fn = BBGTFunction()
    fn.deps = FunctionDeps()
    res = _run(fn.execute(instrument=MSFT, quantity=7, **kwargs))
    assert res.data["status"] == "input_error", res.data
    assert res.data["field"] == {"side": "side", "type": "order_type", "tif": "tif"}[field]
    assert res.data["value"] == value
    assert res.data["allowed"]


def test_bbgt_invalid_side_never_reaches_broker() -> None:
    fn, broker = _armed_bbgt()
    res = _run(fn.execute(instrument=AAPL, quantity=1, side="HOLD", submit=True, paper_mode=False))
    assert broker.placed == []
    assert res.data["status"] == "input_error"


# ── BBGT#3: LIMIT needs a positive price ────────────────────────────────────


@pytest.mark.parametrize("price", [None, "", 0, -3, "abc", "nan"])
def test_bbgt_limit_without_positive_price_is_input_required(price: Any) -> None:
    fn = BBGTFunction()
    fn.deps = FunctionDeps()
    res = _run(fn.execute(instrument=MSFT, quantity=7, side="SELL", type="LIMIT", tif="DAY", price=price))
    assert res.data["status"] == "input_required", res.data
    assert "limit price" in res.data["reason"].lower()
    assert res.data["field"] == "price"


def test_bbgt_limit_without_price_never_reaches_broker() -> None:
    fn, broker = _armed_bbgt()
    res = _run(fn.execute(instrument=MSFT, quantity=7, side="SELL", type="LIMIT", submit=True, paper_mode=False))
    assert broker.placed == []
    assert res.data["status"] == "input_required"


# ── BBGT#4: pre-trade notional ──────────────────────────────────────────────


def test_bbgt_limit_preview_emits_notional_from_limit_price() -> None:
    fn = BBGTFunction()
    fn.deps = FunctionDeps()
    res = _run(fn.execute(instrument=MSFT, quantity=7, side="SELL", type="LIMIT", price=425.0, tif="DAY"))
    data = res.data
    assert data["status"] == "preview"
    assert data["notional"] == pytest.approx(2975.0)
    assert data["notional_currency"] == "USD"
    assert data["notional_basis"] == "limit_price"
    assert data["notional_indicative"] is False
    assert data["reference_price"] == 425.0


def test_bbgt_market_notional_is_null_without_quote_adapter() -> None:
    fn = BBGTFunction()
    fn.deps = FunctionDeps()
    res = _run(fn.execute(instrument=MSFT, quantity=2, side="BUY", type="MARKET"))
    data = res.data
    assert data["status"] == "preview"
    assert data["notional"] is None
    assert data["notional_basis"] == "unavailable"
    assert data["notional_indicative"] is None
    assert data["notional_reason"]


def test_bbgt_market_notional_uses_labelled_indicative_quote() -> None:
    feed = _QuoteFeed(last=100.0)
    fn = BBGTFunction()
    fn.deps = FunctionDeps(yfinance=feed)
    res = _run(fn.execute(instrument=MSFT, quantity=2, side="BUY", type="MARKET"))
    data = res.data
    assert feed.calls == 1
    assert data["notional"] == pytest.approx(200.0)
    assert data["reference_price"] == 100.0
    assert data["notional_basis"] == "indicative_last_quote"
    assert data["notional_indicative"] is True
    assert data["notional_source"] == "yfinance"


def test_bbgt_market_notional_is_null_when_quote_fetch_fails() -> None:
    fn = BBGTFunction()
    fn.deps = FunctionDeps(yfinance=_QuoteFeed(error=RuntimeError("upstream down")))
    res = _run(fn.execute(instrument=MSFT, quantity=2, side="BUY", type="MARKET"))
    data = res.data
    assert data["status"] == "preview"
    assert data["notional"] is None
    assert data["notional_basis"] == "unavailable"
    assert "unavailable" in data["notional_reason"].lower()
