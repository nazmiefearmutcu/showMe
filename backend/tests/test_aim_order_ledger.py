"""AIM order-ledger regression tests (wb1-g07).

Network-free: broker adapters are stubbed and the local order_history store
is monkeypatched, so every assertion runs through AIMFunction.execute().
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Broker:
    """Minimal adapter stub: a name plus a fixed open-order list."""

    def __init__(self, name: str, open_orders: list[dict[str, Any]] | None = None,
                 *, boom: bool = False) -> None:
        self.name = name
        self._open = list(open_orders or [])
        self._boom = boom

    async def get_open_orders(self) -> list[dict[str, Any]]:
        if self._boom:
            raise RuntimeError("simulated outage")
        return list(self._open)


def _hist(order_id: str, *, broker: str = "alpaca-paper", status: str = "submitted",
          symbol: str = "AAPL", quantity: float = 3.0, price: float | None = 190.0,
          ts: int = 1_700_000_000, type_: str = "LIMIT") -> dict[str, Any]:
    return {
        "id": 1, "ts": ts, "broker": broker, "order_id": order_id,
        "symbol": symbol, "asset_class": "EQUITY", "side": "BUY",
        "quantity": quantity, "price": price, "leverage": None,
        "type": type_, "tif": "GTC", "status": status, "metadata": {},
    }


def _install_history(monkeypatch, rows: list[dict[str, Any]]) -> None:
    import showme.engine.services.order_history as oh

    def _list_orders(**kw: Any) -> list[dict[str, Any]]:
        limit = kw.get("limit", 200)
        broker = kw.get("broker")
        out = [r for r in rows if broker is None or r["broker"] == broker]
        return out[:limit]

    monkeypatch.setattr(oh, "list_orders", _list_orders)


def _aim(deps: Any = None):
    from showme.engine.functions.trade._funcs import AIMFunction

    fn = AIMFunction()
    fn.deps = deps if deps is not None else SimpleNamespace()
    return fn


# --------------------------------------------------------------------------- #
# AIM#1 — orders accepted by a broker ("submitted") are open, not history.
# --------------------------------------------------------------------------- #
def test_submitted_history_order_is_counted_as_open(monkeypatch):
    _install_history(monkeypatch, [_hist("ord-1")])
    res = _run(_aim().execute())
    assert res.data["cards"]["open_count"] == 1
    assert res.data["rows"][0]["status"] == "submitted"


def test_open_count_uses_same_open_vocabulary_as_pane(monkeypatch):
    rows = [
        _hist("a", status="submitted"),
        _hist("b", status="new"),
        _hist("c", status="accepted"),
        _hist("d", status="pending"),
        _hist("e", status="filled"),
        _hist("f", status="cancelled"),
    ]
    _install_history(monkeypatch, rows)
    res = _run(_aim().execute())
    assert res.data["cards"]["open_count"] == 4


def test_unconfirmed_submitted_history_is_labelled(monkeypatch):
    """Order history is never updated after placement, so a 'submitted' row
    that no live broker lists may already be filled. It must be flagged."""
    _install_history(monkeypatch, [_hist("ord-9")])
    res = _run(_aim().execute())
    assert res.data["cards"]["unconfirmed_submitted_count"] == 1
    assert any("submitted" in w and "live broker" in w for w in res.warnings)


# --------------------------------------------------------------------------- #
# AIM#3 (part) — a live broker order must not be double counted with its own
# history row.
# --------------------------------------------------------------------------- #
def test_history_row_matching_live_order_is_not_duplicated(monkeypatch):
    live = {"broker": "alpaca_broker", "order_id": "ord-1", "symbol": "AAPL",
            "side": "BUY", "quantity": 3, "price": 190.0, "status": "open"}
    deps = SimpleNamespace(alpaca_broker=_Broker("alpaca-paper", [live]))
    _install_history(monkeypatch, [_hist("ord-1", broker="alpaca-paper")])
    res = _run(_aim(deps).execute())
    ids = [r["order_id"] for r in res.data["rows"]]
    assert ids.count("ord-1") == 1
    assert res.data["cards"]["open_count"] == 1


# --------------------------------------------------------------------------- #
# AIM#2 — broker_filter must also restrict the order-history tail.
# --------------------------------------------------------------------------- #
def test_broker_filter_restricts_history_rows(monkeypatch):
    rows = [
        _hist("h-alpaca", broker="alpaca-paper", status="filled"),
        _hist("h-binance", broker="binance", symbol="BTCUSDT", status="filled"),
    ]
    _install_history(monkeypatch, rows)
    deps = SimpleNamespace(alpaca_broker=_Broker("alpaca-paper"))
    res = _run(_aim(deps).execute(broker_filter=["alpaca_broker"]))
    ids = [r["order_id"] for r in res.data["rows"]]
    assert ids == ["h-alpaca"], ids


def test_broker_filter_matches_history_by_adapter_name_and_key(monkeypatch):
    """A history row is attributed to an adapter by the name it was stored
    under (adapter.name), so an adapter-key filter must still match it."""
    rows = [_hist("h-recording", broker="recording_broker", status="filled")]
    _install_history(monkeypatch, rows)
    deps = SimpleNamespace(alpaca_broker=_Broker("recording_broker"))
    res = _run(_aim(deps).execute(broker_filter=["alpaca_broker"]))
    assert [r["order_id"] for r in res.data["rows"]] == ["h-recording"]


def test_broker_filter_with_no_matching_broker_returns_no_history(monkeypatch):
    _install_history(monkeypatch, [_hist("h-alpaca", broker="alpaca-paper")])
    res = _run(_aim(SimpleNamespace()).execute(broker_filter=["oanda_broker"]))
    assert res.data["rows"] == []
    assert res.data["status"] == "empty"
