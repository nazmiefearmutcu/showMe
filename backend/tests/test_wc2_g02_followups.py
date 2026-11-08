"""wc2-g02 follow-up regression tests (network-free).

AIM#3-RQ: history rows for one order_id under broker names that no configured
adapter resolves to cannot be proven to be the same order. They stay counted,
but the response must say so instead of silently double counting.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _hist(order_id: str, *, broker: str, symbol: str = "AAPL", quantity: float = 1.0,
          price: float | None = 190.0, ts: int = 1_700_000_000) -> dict[str, Any]:
    return {
        "id": 1, "ts": ts, "broker": broker, "order_id": order_id,
        "symbol": symbol, "asset_class": "EQUITY", "side": "BUY",
        "quantity": quantity, "price": price, "leverage": None,
        "type": "LIMIT", "tif": "GTC", "status": "filled", "metadata": {},
    }


def _install_history(monkeypatch, rows: list[dict[str, Any]]) -> None:
    import showme.engine.services.order_history as oh

    def _list_orders(**kw: Any) -> list[dict[str, Any]]:
        limit = kw.get("limit", 200)
        broker = kw.get("broker")
        out = [r for r in rows if broker is None or r["broker"] == broker]
        return out[:limit]

    monkeypatch.setattr(oh, "list_orders", _list_orders)


def _aim(deps: Any):
    from showme.engine.functions.trade._funcs import AIMFunction

    fn = AIMFunction()
    fn.deps = deps
    return fn


def test_aim_same_order_under_unresolved_broker_names_is_counted_once(monkeypatch):
    """AIM#3-RQ: the history store is written once per placement, so one order_id
    under two broker labels that no adapter resolves is one order recorded twice.
    It must be listed and counted once (newest row kept), and the response must
    say which duplicate was dropped."""
    rows = [
        _hist("ord-1", broker="recording_broker", ts=1_700_000_200),
        _hist("ord-1", broker="rec", ts=1_700_000_100),
    ]
    _install_history(monkeypatch, rows)
    res = _run(_aim(SimpleNamespace()).execute())
    assert len(res.data["rows"]) == 1, res.data["rows"]
    assert res.data["rows"][0]["broker"] == "recording_broker"
    assert res.data["cards"]["total_notional"] == 190.0, res.data["cards"]
    text = " ".join(res.warnings).lower()
    assert "ord-1" in text and "duplicate" in text and "rec" in text, res.warnings


def test_aim_distinct_orders_under_unresolved_names_are_not_merged(monkeypatch):
    """Different order_ids under unmatched labels are different orders: no merge."""
    rows = [
        _hist("ord-1", broker="recording_broker"),
        _hist("ord-2", broker="rec"),
    ]
    _install_history(monkeypatch, rows)
    res = _run(_aim(SimpleNamespace()).execute())
    assert len(res.data["rows"]) == 2
    assert res.data["cards"]["total_notional"] == 380.0
