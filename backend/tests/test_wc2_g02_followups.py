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


def test_aim_same_order_under_unresolved_broker_names_is_flagged(monkeypatch):
    """AIM#3-RQ: an order_id recorded under two broker names that no adapter
    resolves to is kept (it may be a different venue) but flagged as a possible
    duplicate, so the indicative notional is not silently double counted."""
    rows = [
        _hist("ord-1", broker="recording_broker"),
        _hist("ord-1", broker="rec"),
    ]
    _install_history(monkeypatch, rows)
    res = _run(_aim(SimpleNamespace()).execute())
    text = (" ".join(res.warnings) + " " + str(res.data.get("warning", ""))).lower()
    assert "ord-1" in text and "possible duplicate" in text, res.warnings
