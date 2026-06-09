"""Degarbage regression tests for trade functions (AIM, FXGO).

These assert the handlers return REAL data shapes instead of the old
hardcoded/raw stubs:

  * AIM returns a manifest-shaped read-only ledger (status/rows/cards/
    methodology/field_dictionary/data_mode), normalising persisted
    order-history rows into the table schema — honest ``empty`` when
    nothing is found.
  * FXGO's DEFAULT path returns a LIVE FX dealing board (rows with
    bid/ask/spread) fetched keyless from the public Yahoo FX chart
    endpoint, degrading to a clearly-labelled ``provider_unavailable``
    shape when offline. The inherited EMSX ticket-preview contract is
    preserved when an order ticket is supplied.

Live-network assertions are guarded so the suite passes cleanly offline.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.instrument import AssetClass, Instrument


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mk_handler(klass, deps=None):
    try:
        return klass(deps=deps)
    except TypeError:
        return klass()


# --------------------------------------------------------------------------- #
# AIM
# --------------------------------------------------------------------------- #
def test_aim_empty_is_manifest_shaped(monkeypatch):
    """No brokers + no history -> honest empty with the full contract."""
    import showme.engine.services.order_history as oh

    monkeypatch.setattr(oh, "list_orders", lambda **_kw: [])

    from showme.engine.functions.trade._funcs import AIMFunction

    h = _mk_handler(AIMFunction, deps=None)
    res = _run(h.execute())
    data = res.data
    assert data.get("status") in {"ok", "empty"}
    # Contract fields must always be present regardless of state.
    assert "rows" in data and isinstance(data["rows"], list)
    assert isinstance(data.get("cards"), dict)
    assert data.get("methodology")
    assert isinstance(data.get("field_dictionary"), dict) and data["field_dictionary"]
    assert data.get("data_mode") in {"live_exchange", "cached_snapshot", "not_configured"}
    assert "as_of" in data
    assert isinstance(data.get("brokers_checked"), list)
    # No brokers wired + no history -> not_configured + empty.
    assert data["status"] == "empty"
    assert data["rows"] == []
    assert data["data_mode"] == "not_configured"


def test_aim_normalises_persisted_history_rows(monkeypatch):
    """A persisted order row surfaces as a normalised ledger row (real data)."""
    import showme.engine.services.order_history as oh

    fake_rows = [
        {
            "id": 1,
            "ts": 1_700_000_000,
            "broker": "binance_broker",
            "order_id": "abc123",
            "symbol": "BTCUSDT",
            "asset_class": "CRYPTO",
            "side": "buy",
            "quantity": 0.5,
            "price": 60000.0,
            "leverage": None,
            "type": "LIMIT",
            "tif": "GTC",
            "status": "filled",
            "metadata": {},
        }
    ]
    monkeypatch.setattr(oh, "list_orders", lambda **_kw: list(fake_rows))

    from showme.engine.functions.trade._funcs import AIMFunction

    h = _mk_handler(AIMFunction, deps=None)
    res = _run(h.execute(limit=50))
    data = res.data
    assert data["status"] == "ok"
    rows = data["rows"]
    assert rows, "expected the persisted order to surface as a row"
    row = next(r for r in rows if r.get("order_id") == "abc123")
    assert row["symbol"] == "BTCUSDT"
    assert row["side"] == "BUY"  # normalised to upper
    assert row["status"] == "filled"
    assert row["broker"] == "binance_broker"
    assert row["created_at"] is not None  # derived from ts
    # cards reflect real aggregates, not constants.
    assert data["cards"]["filled_today"] >= 1
    assert "order_history" in res.sources


def test_aim_history_tail_respects_limit(monkeypatch):
    """The handler clamps + the store call honours the limit argument."""
    import showme.engine.services.order_history as oh

    captured = {}

    def _fake_list_orders(**kw):
        captured["limit"] = kw.get("limit")
        n = kw.get("limit", 200)
        return [
            {"order_id": f"o{i}", "symbol": "ETHUSDT", "side": "buy",
             "quantity": 1, "price": 1000.0, "status": "open"}
            for i in range(min(n, 10))
        ]

    monkeypatch.setattr(oh, "list_orders", _fake_list_orders)

    from showme.engine.functions.trade._funcs import AIMFunction

    h = _mk_handler(AIMFunction, deps=None)
    res = _run(h.execute(limit=3))
    assert captured["limit"] == 3
    assert len(res.data["rows"]) <= 3


def test_aim_manifest_provider_chain_is_honest() -> None:
    """The AIM manifest must not mislabel its provider chain.

    H2: the impl fans out across binance/alpaca/ibkr/oanda broker adapters and
    degrades to a cached order_history snapshot — it is NOT a single
    ``ccxt_broker`` provider. The seed primary must reflect the multi-broker
    fanout while keeping the cached_snapshot fallback.
    """
    from showme.manifest.registry import REGISTRY
    from showme.manifest.seeds import load_seeds

    load_seeds()
    entry = REGISTRY.get("AIM")
    assert entry.provider_chain.primary != "ccxt_broker", (
        "AIM provider_chain.primary must not claim a single ccxt_broker — it "
        "fans out across multiple broker adapters"
    )
    assert entry.provider_chain.primary == "broker_adapters", (
        f"expected 'broker_adapters', got {entry.provider_chain.primary!r}"
    )
    assert "cached_snapshot" in entry.provider_chain.fallbacks


def test_aim_filled_card_label_is_not_misnamed_today() -> None:
    """H1: the 'Filled' KPI counts all-time fills, so it must not say 'today'.

    The data key stays ``filled_today`` for contract stability, but the
    user-facing label must be the honest all-time "Filled".
    """
    from showme.manifest.registry import REGISTRY
    from showme.manifest.seeds import load_seeds

    load_seeds()
    entry = REGISTRY.get("AIM")
    filled_slots = [s for s in entry.card_schema.slots if s.key == "filled_today"]
    assert filled_slots, "AIM must expose a filled KPI slot"
    label = filled_slots[0].label or ""
    assert "today" not in label.lower(), (
        f"the all-time fill count must not be labelled 'today'; got {label!r}"
    )
    assert label == "Filled"


# --------------------------------------------------------------------------- #
# FXGO — live dealing board
# --------------------------------------------------------------------------- #
def test_fxgo_default_board_live_or_graceful_real_network():
    """Real, UNSTUBBED default call: live FX board OR an honest fallback.

    Network-tolerant: when Yahoo answers we assert a real two-way board;
    when it is unreachable/rate-limited we assert the labelled
    provider_unavailable shape with no fabricated numbers. Either way the
    contract fields (methodology/field_dictionary/yfinance source) hold.
    """
    from showme.engine.functions.trade._funcs import FXGOFunction

    h = _mk_handler(FXGOFunction, deps=None)
    res = _run(h.execute())
    data = res.data
    assert data.get("status") in {"ok", "provider_unavailable"}
    assert data.get("methodology")
    assert isinstance(data.get("field_dictionary"), dict) and data["field_dictionary"]
    assert "yfinance" in res.sources
    assert isinstance(data.get("rows"), list)
    if data["status"] == "ok":
        # Real, non-constant spot data with a real two-way quote.
        assert data["rows"], "ok board must carry rows"
        first = data["rows"][0]
        for key in ("pair", "bid", "ask", "mid", "spread", "spread_pips"):
            assert key in first
        assert first["bid"] > 0 and first["ask"] > 0
        assert first["ask"] >= first["bid"]
        assert data["data_mode"] == "live_exchange"
    else:
        # Offline / rate-limited: honest unavailable shape, no numbers.
        assert data["data_mode"] == "provider_unavailable"
        assert data["rows"] == []
        assert res.warnings or data.get("warning")


def test_fxgo_default_board_ok_with_stub(monkeypatch):
    """Deterministic default-path board with a stubbed spot (no network)."""
    from showme.engine.functions.trade._funcs import FXGOFunction

    monkeypatch.setattr(
        FXGOFunction, "_fetch_fx_spot",
        lambda self, pair: (1.10 if not pair.upper().endswith("JPY") else 150.0, None),
    )

    h = _mk_handler(FXGOFunction, deps=None)
    res = _run(h.execute())
    data = res.data
    assert data["status"] == "ok"
    assert data["data_mode"] == "live_exchange"
    assert len(data["rows"]) == len(FXGOFunction._BOARD_PAIRS)
    assert "yfinance" in res.sources
    first = data["rows"][0]
    assert first["bid"] > 0 and first["ask"] >= first["bid"]
    assert isinstance(data.get("cards"), dict) and "as_of" in data["cards"]


def test_fxgo_board_via_injected_spot(monkeypatch):
    """With a stubbed FX spot, the board computes a real bid/ask/spread."""
    from showme.engine.functions.trade._funcs import FXGOFunction

    monkeypatch.setattr(
        FXGOFunction, "_fetch_fx_spot",
        lambda self, pair: (1.0850, 1.0800),
    )

    h = _mk_handler(FXGOFunction, deps=None)
    res = _run(h.execute(pairs="EURUSD"))
    data = res.data
    assert data["status"] == "ok"
    assert data["data_mode"] == "live_exchange"
    row = data["rows"][0]
    assert row["pair"] == "EURUSD"
    assert row["mid"] == pytest.approx(1.0850, abs=1e-6)
    assert row["ask"] > row["bid"]
    assert row["spread"] == pytest.approx(0.0001, abs=1e-6)  # 1 pip on a non-JPY pair
    assert row["change"] == pytest.approx(0.0050, abs=1e-6)
    assert row["change_pct"] is not None


def test_fxgo_jpy_pip_size(monkeypatch):
    from showme.engine.functions.trade._funcs import FXGOFunction

    monkeypatch.setattr(
        FXGOFunction, "_fetch_fx_spot",
        lambda self, pair: (150.00, 149.50),
    )

    h = _mk_handler(FXGOFunction, deps=None)
    res = _run(h.execute(pairs="USDJPY"))
    row = res.data["rows"][0]
    # JPY pair uses a 0.01 pip; 1-pip spread -> 0.01.
    assert row["spread"] == pytest.approx(0.01, abs=1e-6)
    assert row["spread_pips"] == pytest.approx(1.0, abs=1e-6)


def test_fxgo_board_unavailable_when_fetch_raises(monkeypatch):
    """Network outage on every pair -> honest provider_unavailable, no numbers."""
    from showme.engine.functions.trade._funcs import FXGOFunction

    def _boom(self, pair):
        raise ConnectionError("network down")

    monkeypatch.setattr(FXGOFunction, "_fetch_fx_spot", _boom)

    h = _mk_handler(FXGOFunction, deps=None)
    res = _run(h.execute(pairs="EURUSD"))
    data = res.data
    assert data["status"] == "provider_unavailable"
    assert data["data_mode"] == "provider_unavailable"
    assert data["rows"] == []
    assert res.warnings
    assert "yfinance" in res.sources


def test_fxgo_ticket_intent_preserves_emsx_preview():
    """Supplying a ticket (quantity) keeps the inherited safe paper-preview path.

    With submit omitted/false and no broker wired, EMSX returns a faithful
    paper preview that round-trips the ticket fields the trader entered.
    """
    from showme.engine.functions.trade._funcs import FXGOFunction

    h = _mk_handler(FXGOFunction, deps=None)
    inst = Instrument(symbol="EURUSD", asset_class=AssetClass.FX)
    res = _run(h.execute(instrument=inst, side="SELL", quantity=250000,
                         order_type="LIMIT", price=1.2755))
    data = res.data
    # No broker wired + preview -> paper preview, no live submit.
    assert data["status"] == "preview"
    assert data["broker"] == "paper"
    assert data["side"] == "SELL"
    assert data["quantity"] == 250000
    assert data["price"] == 1.2755


def test_fxgo_live_submit_without_broker_is_safe():
    """Arming live submit with no FX broker must NOT silently trade — it
    returns provider_unavailable per the EMSX safe-by-default contract."""
    from showme.engine.functions.trade._funcs import FXGOFunction

    h = _mk_handler(FXGOFunction, deps=None)
    inst = Instrument(symbol="USDJPY", asset_class=AssetClass.FX)
    res = _run(h.execute(instrument=inst, side="BUY", quantity=100000, submit=True))
    data = res.data
    assert data["status"] == "provider_unavailable"
    assert data.get("broker") in {None, "paper"}
