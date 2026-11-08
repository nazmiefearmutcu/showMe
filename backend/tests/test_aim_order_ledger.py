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
def test_submitted_history_order_without_broker_confirmation_is_not_open(monkeypatch):
    """History is written once at placement and never updated, so a 'submitted'
    row that no live broker lists must not be counted as working."""
    _install_history(monkeypatch, [_hist("ord-1")])
    res = _run(_aim().execute())
    assert res.data["cards"]["open_count"] == 0
    assert res.data["cards"]["unconfirmed_submitted_count"] == 1
    assert res.data["rows"][0]["status"] == "submitted"
    assert res.data["rows"][0]["confirmed_open"] is False


def test_submitted_history_order_not_listed_by_polled_broker_is_not_open(monkeypatch):
    """The owning adapter answered its poll and does not list the order, so it
    is not working at the broker: it must not inflate open_count."""
    _install_history(monkeypatch, [_hist("ord-1", broker="alpaca-paper")])
    deps = SimpleNamespace(alpaca_broker=_Broker("alpaca-paper", []))
    res = _run(_aim(deps).execute())
    assert res.data["cards"]["open_count"] == 0
    assert res.data["rows"][0]["status"] == "submitted"
    assert any("live broker" in w for w in res.warnings)


def test_broker_listed_submitted_order_is_open(monkeypatch):
    """Only a live broker listing makes an order open."""
    live = {"order_id": "ord-1", "symbol": "AAPL", "side": "BUY", "quantity": 3,
            "price": 190.0, "status": "new"}
    _install_history(monkeypatch, [_hist("ord-1", broker="alpaca-paper")])
    deps = SimpleNamespace(alpaca_broker=_Broker("alpaca-paper", [live]))
    res = _run(_aim(deps).execute())
    assert res.data["cards"]["open_count"] == 1
    assert res.data["rows"][0]["confirmed_open"] is True


def test_live_broker_submitted_status_is_open(monkeypatch):
    """A live adapter listing is itself proof of a working order, so a status
    the broker reports as 'submitted' (e.g. IBKR "Submitted") must count as open.
    Only history rows, which are never broker-confirmed, stay out of open_count."""
    live = {"order_id": "ord-7", "symbol": "AAPL", "side": "BUY", "quantity": 3,
            "price": 190.0, "status": "submitted"}
    _install_history(monkeypatch, [])
    deps = SimpleNamespace(ibkr_broker=_Broker("ibkr_broker", [live]))
    res = _run(_aim(deps).execute())
    assert res.data["cards"]["open_count"] == 1
    assert res.data["rows"][0]["status"] == "submitted"
    assert res.data["rows"][0]["confirmed_open"] is True


def test_open_count_uses_same_open_vocabulary_as_pane(monkeypatch):
    live = [
        {"order_id": "a", "symbol": "AAPL", "side": "BUY", "quantity": 1, "price": 1.0, "status": "new"},
        {"order_id": "b", "symbol": "AAPL", "side": "BUY", "quantity": 1, "price": 1.0, "status": "accepted"},
        {"order_id": "c", "symbol": "AAPL", "side": "BUY", "quantity": 1, "price": 1.0, "status": "pending"},
        {"order_id": "d", "symbol": "AAPL", "side": "BUY", "quantity": 1, "price": 1.0, "status": "working"},
        {"order_id": "e", "symbol": "AAPL", "side": "BUY", "quantity": 1, "price": 1.0, "status": "filled"},
    ]
    history = [
        _hist("h1", broker="alpaca-paper", status="submitted"),
        _hist("h2", broker="alpaca-paper", status="filled"),
    ]
    _install_history(monkeypatch, history)
    deps = SimpleNamespace(alpaca_broker=_Broker("alpaca-paper", live))
    res = _run(_aim(deps).execute())
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


# --------------------------------------------------------------------------- #
# AIM#3 — the notional total must say what it left out and what it mixes.
# --------------------------------------------------------------------------- #
def test_notional_reports_unpriced_orders_and_basis(monkeypatch):
    rows = [
        _hist("p1", quantity=3.0, price=190.0),
        _hist("p2", quantity=3.0, price=190.0),
        _hist("p3", quantity=3.0, price=190.0, status="filled"),
        _hist("m1", quantity=1.0, price=None, status="filled", type_="MARKET"),
        _hist("m2", quantity=1.0, price=None, status="filled", type_="MARKET"),
    ]
    _install_history(monkeypatch, rows)
    res = _run(_aim().execute())
    cards = res.data["cards"]
    assert cards["total_notional"] == pytest.approx(1710.0)
    assert cards["priced_count"] == 3
    assert cards["unpriced_count"] == 2
    assert cards["notional_basis"] == "indicative_unconverted"
    assert any("unpriced" in w for w in res.warnings)


def test_notional_label_is_not_usd_when_nothing_is_priced(monkeypatch):
    _install_history(monkeypatch, [_hist("m1", quantity=1.0, price=None, status="filled", type_="MARKET")])
    res = _run(_aim().execute())
    cards = res.data["cards"]
    assert cards["total_notional"] == 0
    assert cards["priced_count"] == 0
    assert cards["unpriced_count"] == 1


# --------------------------------------------------------------------------- #
# AIM#4 — provider_mode is honoured and the methodology describes the real loop.
# --------------------------------------------------------------------------- #
class _CountingBroker(_Broker):
    def __init__(self, name: str, open_orders: list[dict[str, Any]] | None = None) -> None:
        super().__init__(name, open_orders)
        self.calls = 0

    async def get_open_orders(self) -> list[dict[str, Any]]:
        self.calls += 1
        return await super().get_open_orders()


def test_provider_mode_cached_snapshot_skips_live_polling(monkeypatch):
    _install_history(monkeypatch, [_hist("h-1", status="filled")])
    broker = _CountingBroker("alpaca-paper", [{"order_id": "live-1", "symbol": "AAPL", "side": "BUY",
                                              "quantity": 1, "price": 1.0, "status": "open"}])
    deps = SimpleNamespace(alpaca_broker=broker)
    res = _run(_aim(deps).execute(provider_mode="cached_snapshot"))
    assert broker.calls == 0
    assert res.data["data_mode"] == "cached_snapshot"
    assert res.data["provider_mode"] == "cached_snapshot"
    assert [r["order_id"] for r in res.data["rows"]] == ["h-1"]


def test_brokers_checked_lists_only_configured_adapters_that_were_polled(monkeypatch):
    _install_history(monkeypatch, [])
    deps = SimpleNamespace(alpaca_broker=_Broker("alpaca-paper", [
        {"order_id": "live-1", "symbol": "AAPL", "side": "BUY", "quantity": 1,
         "price": 1.0, "status": "open"}]))
    res = _run(_aim(deps).execute())
    assert res.data["brokers_checked"] == ["alpaca_broker"]
    assert res.data["brokers_online"] == ["alpaca_broker"]


def test_failed_poll_is_checked_but_not_online(monkeypatch):
    _install_history(monkeypatch, [_hist("h-1", broker="alpaca-paper", status="filled")])
    deps = SimpleNamespace(alpaca_broker=_Broker("alpaca-paper", boom=True))
    res = _run(_aim(deps).execute(broker_filter=[]))
    assert res.data["brokers_checked"] == ["alpaca_broker"]
    assert res.data["brokers_online"] == []


def test_cached_snapshot_checks_no_brokers(monkeypatch):
    _install_history(monkeypatch, [_hist("h-1", status="filled")])
    deps = SimpleNamespace(alpaca_broker=_Broker("alpaca-paper"))
    res = _run(_aim(deps).execute(provider_mode="cached_snapshot"))
    assert res.data["brokers_checked"] == []


def test_unknown_provider_mode_is_reported_not_silently_used(monkeypatch):
    _install_history(monkeypatch, [])
    res = _run(_aim(SimpleNamespace()).execute(provider_mode="bogus"))
    assert any("provider_mode" in str(w) and "bogus" in str(w) for w in res.warnings)


def test_methodology_does_not_claim_parallel_fan_out():
    from showme.engine.functions.trade._funcs import AIMFunction

    assert "in parallel" not in AIMFunction._METHODOLOGY
    assert "sequential" in AIMFunction._METHODOLOGY


def test_seed_methodology_does_not_claim_parallel_fan_out():
    from showme.manifest.seeds.aim_seed import aim

    manifest = aim  # the @manifest decorator registers the FunctionManifest object itself
    assert "in parallel" not in manifest.methodology
    assert "sequential" in manifest.methodology
