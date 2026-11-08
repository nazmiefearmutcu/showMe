"""WB1-G16 regression pins for EMSX and TSOX (findings EMSX#1-#3, TSOX#3-#4).

* EMSX#1: invalid side / tif / leverage were previewed as a valid ticket.
* EMSX#2: a MARKET ticket echoed the limit price the caller typed.
* EMSX#3: the live branch built a BrokerOrder from unvalidated enums.
* TSOX#4: a LIMIT treasury ticket with no price previewed as valid.
* TSOX#3: bond-ticket analytics (DV01, accrued, settlement, multiplier) were
  silently absent; the response now says they are not computed.

The network is never touched: brokers are recording stubs and the order
audit write is patched out.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.trade._funcs import EMSXFunction, TSOXFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
ZN = Instrument(symbol="ZN=F", asset_class=AssetClass.DERIVATIVE)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _RecordingBroker:
    name = "recording_broker"

    def __init__(self) -> None:
        self.placed: list[Any] = []

    async def place_order(self, order: Any) -> str:
        self.placed.append(order)
        return f"ord-{len(self.placed)}"


@pytest.fixture
def no_audit(monkeypatch: Any) -> None:
    import showme.engine.services.order_history as oh

    monkeypatch.setattr(oh, "record_order", lambda **_kw: None)


def _emsx_fn() -> tuple[EMSXFunction, _RecordingBroker]:
    fn = EMSXFunction()
    deps = FunctionDeps()
    broker = _RecordingBroker()
    deps.alpaca_broker = broker
    fn.deps = deps
    return fn, broker


def _tsox_fn() -> tuple[TSOXFunction, _RecordingBroker]:
    fn = TSOXFunction()
    deps = FunctionDeps()
    broker = _RecordingBroker()
    deps.ibkr_broker = broker
    fn.deps = deps
    return fn, broker


# ── EMSX#1: enum / range validation before a preview ───────────────────────


def test_emsx_unknown_side_is_input_error_not_preview() -> None:
    fn, broker = _emsx_fn()
    res = _run(fn.execute(instrument=AAPL, side="HOLD", quantity=10))
    assert res.data["status"] == "input_error"
    assert res.data["field"] == "side"
    assert broker.placed == []


def test_emsx_unknown_tif_is_input_error_not_preview() -> None:
    fn, _ = _emsx_fn()
    res = _run(fn.execute(instrument=AAPL, side="BUY", quantity=10, tif="FOO"))
    assert res.data["status"] == "input_error"
    assert res.data["field"] == "tif"


def test_emsx_leverage_above_seed_max_is_input_error() -> None:
    fn, _ = _emsx_fn()
    res = _run(fn.execute(instrument=AAPL, side="BUY", quantity=10, leverage=500))
    assert res.data["status"] == "input_error"
    assert res.data["field"] == "leverage"


def test_emsx_valid_leverage_is_echoed_as_number() -> None:
    fn, _ = _emsx_fn()
    res = _run(fn.execute(instrument=AAPL, side="BUY", quantity=10, leverage="10"))
    assert res.data["status"] == "preview"
    assert res.data["leverage"] == 10


def test_emsx_nan_quantity_is_input_error() -> None:
    fn, _ = _emsx_fn()
    res = _run(fn.execute(instrument=AAPL, side="BUY", quantity=float("nan")))
    assert res.data["status"] == "input_error"
    assert res.data["field"] == "quantity"
    assert res.data["quantity"] is None  # NaN is not JSON-serialisable


# ── EMSX#2: MARKET ticket must not echo a limit price ─────────────────────


def test_emsx_market_preview_does_not_echo_limit_price() -> None:
    fn, _ = _emsx_fn()
    res = _run(fn.execute(instrument=AAPL, side="BUY", quantity=5, order_type="MARKET", price=190))
    assert res.data["status"] == "preview"
    assert res.data["price"] is None


# ── TSOX#4 / EMSX: LIMIT ticket needs a positive price ────────────────────


def test_tsox_limit_without_price_is_input_error() -> None:
    fn, broker = _tsox_fn()
    res = _run(fn.execute(instrument=ZN, side="BUY", quantity=1, order_type="LIMIT"))
    assert res.data["status"] == "input_error"
    assert res.data["field"] == "price"
    assert broker.placed == []


@pytest.mark.parametrize("bad_price", [0, -1.5, "abc", float("nan")])
def test_emsx_limit_with_non_positive_or_garbage_price_is_input_error(bad_price: Any) -> None:
    fn, _ = _emsx_fn()
    res = _run(fn.execute(instrument=AAPL, side="SELL", quantity=5, order_type="LIMIT", price=bad_price))
    assert res.data["status"] == "input_error"
    assert res.data["field"] == "price"


def test_tsox_limit_price_round_trips_32nds_decimal() -> None:
    fn, _ = _tsox_fn()
    res = _run(fn.execute(instrument=ZN, side="BUY", quantity=1, order_type="LIMIT", price=110.015625))
    assert res.data["status"] == "preview"
    assert res.data["price"] == 110.015625


# ── EMSX#3: live branch never builds an order from unvalidated fields ─────


def test_emsx_live_armed_invalid_side_never_reaches_broker() -> None:
    fn, broker = _emsx_fn()
    res = _run(fn.execute(instrument=AAPL, side="HOLD", quantity=1, submit=True, paper_mode=False))
    assert res.data["status"] == "input_error"
    assert res.data["field"] == "side"
    assert broker.placed == []


def test_emsx_live_armed_market_order_is_built_without_price(no_audit: None) -> None:
    fn, broker = _emsx_fn()
    res = _run(
        fn.execute(instrument=AAPL, side="BUY", quantity=2, order_type="MARKET", price=190,
                   submit=True, paper_mode=False)
    )
    assert res.data["status"] == "submitted"
    assert len(broker.placed) == 1
    assert broker.placed[0].price is None
    assert broker.placed[0].quantity == 2


# ── TSOX#3: bond analytics are explicit, never silently absent or invented ─


def test_tsox_preview_reports_analytics_as_not_computed() -> None:
    fn, _ = _tsox_fn()
    res = _run(fn.execute(instrument=ZN, side="BUY", quantity=1, order_type="LIMIT", price=110.015625))
    analytics = res.data["analytics"]
    assert analytics["status"] == "not_computed"
    for key in ("dv01", "accrued_interest", "settlement_date", "contract_multiplier"):
        assert key in analytics["not_computed"]
        assert key not in res.data
    assert analytics.get("reason")


# ── TSOX seed doc: the status field lists every status the pane can receive ─


def test_tsox_seed_status_doc_lists_input_error_and_analytics() -> None:
    from showme.manifest.seeds.tsox_seed import tsox

    desc = tsox.field_dict["status"].description
    assert "input_error" in desc
    assert "not_computed" in desc
