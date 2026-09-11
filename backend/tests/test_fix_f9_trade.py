"""FIX lane F9 — trade/API money-safety + honesty regression pins.

Covers the campaign-2026-09-11 audit findings for the F9 trade slice:

* **BBGT/C + EMSX**: the manifests declare ``paper_mode`` (required,
  default True) as the safe-by-default guard, but the engine never read
  it — ``submit=true`` with a wired broker fired a LIVE order. The
  engine boundary now enforces it: only an explicit ``paper_mode=False``
  can arm the submit path, and a missing/garbage value fails closed to a
  paper preview. The tests below use a recording broker stub, so they are
  red on the old behaviour (the stub received a live order) and green on
  the guard.
* **BBGT/H + EMSX/M**: a successful live submit now returns
  ``status="submitted"`` with a ticket echo, so the panes' live /
  submitted state is actually reachable.
* **EXEC/M**: ``action=plan`` stamps ``cards.execution_mode="planned"``
  so plan vs actual can be labelled honestly.
* **DAPI/L**: ``summary.state_changing`` now agrees with the pane's
  "mutating" filter (yes + depends).
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.api.dapi import DAPIFunction
from showme.engine.functions.trade._funcs import (
    BBGTFunction,
    EMSXFunction,
    _paper_mode_enabled,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _RecordingBroker:
    """Minimal broker adapter recording every place_order call."""

    name = "recording_broker"

    def __init__(self) -> None:
        self.placed: list[Any] = []
        self.cancelled: list[str] = []

    async def place_order(self, order: Any) -> str:
        self.placed.append(order)
        return f"ord-{len(self.placed)}"

    async def cancel_order(self, order_id: str) -> bool:
        self.cancelled.append(order_id)
        return True

    async def get_open_orders(self) -> list[Any]:
        return []


AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _armed_fn(klass: type) -> tuple[Any, _RecordingBroker]:
    fn = klass()
    deps = FunctionDeps()
    broker = _RecordingBroker()
    deps.alpaca_broker = broker
    fn.deps = deps
    return fn, broker


# ── paper_mode parser (fail-closed) ─────────────────────────────────────────


def test_paper_mode_parser_fails_closed_on_garbage() -> None:
    assert _paper_mode_enabled(None) is True
    assert _paper_mode_enabled(True) is True
    assert _paper_mode_enabled("true") is True
    assert _paper_mode_enabled("maybe") is True  # unknown -> paper, never live
    assert _paper_mode_enabled(1) is True
    assert _paper_mode_enabled(False) is False
    assert _paper_mode_enabled("false") is False
    assert _paper_mode_enabled("False") is False
    assert _paper_mode_enabled("0") is False
    assert _paper_mode_enabled(0) is False


# ── BBGT guard (C): default params cannot place a live order ────────────────


def test_bbgt_default_params_cannot_place_live_order() -> None:
    """paper_mode absent (manifest default True) + submit=True -> NO order.

    Red on the old engine: the recording broker received a live order here.
    """
    fn, broker = _armed_fn(BBGTFunction)
    res = _run(fn.execute(instrument=AAPL, quantity=1, submit=True))
    assert broker.placed == [], "default params must never reach the broker"
    assert res.data["status"] == "preview"
    assert res.data["broker"] == "paper"
    assert res.data["submit"] is False
    assert res.data["paper_mode"] is True


def test_bbgt_explicit_paper_mode_true_cannot_place_live_order() -> None:
    fn, broker = _armed_fn(BBGTFunction)
    res = _run(fn.execute(instrument=AAPL, quantity=1, submit=True, paper_mode=True))
    assert broker.placed == []
    assert res.data["status"] == "preview"
    assert res.data["paper_mode"] is True


def test_bbgt_garbage_paper_mode_fails_closed_to_preview() -> None:
    fn, broker = _armed_fn(BBGTFunction)
    res = _run(
        fn.execute(instrument=AAPL, quantity=1, submit=True, paper_mode="maybe")
    )
    assert broker.placed == []
    assert res.data["status"] == "preview"


def test_emsx_default_paper_mode_guard_cannot_place_live_order() -> None:
    """Same boundary guard for the EMSX base class (FXGO/TSOX inherit it)."""
    fn, broker = _armed_fn(EMSXFunction)
    res = _run(fn.execute(instrument=AAPL, quantity=10, submit=True))
    assert broker.placed == []
    assert res.data["status"] == "preview"


def test_explicit_arm_without_broker_is_provider_unavailable() -> None:
    fn = BBGTFunction()
    fn.deps = FunctionDeps()  # no broker adapters wired
    res = _run(
        fn.execute(instrument=AAPL, quantity=1, submit=True, paper_mode=False)
    )
    assert res.data["status"] == "provider_unavailable"
    assert res.data["broker"] is None


# ── live submit success: honest lifecycle status + echo (H/M) ───────────────


def test_explicit_arm_reaches_broker_and_returns_submitted_echo(
    monkeypatch: Any,
) -> None:
    """Only an explicit paper_mode=False + submit=True fires the broker, and
    the success payload carries an honest status + ticket echo."""
    import showme.engine.services.order_history as oh

    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(oh, "record_order", lambda **kw: recorded.append(kw))

    fn, broker = _armed_fn(BBGTFunction)
    res = _run(
        fn.execute(
            instrument=AAPL,
            side="SELL",
            quantity=7,
            type="LIMIT",
            price=425.5,
            tif="DAY",
            submit=True,
            paper_mode=False,
        )
    )
    assert len(broker.placed) == 1
    order = broker.placed[0]
    assert order.side.value == "SELL"
    assert order.quantity == 7
    assert order.order_type.value == "LIMIT"
    assert order.time_in_force.value == "DAY"

    data = res.data
    assert data["status"] == "submitted"
    assert data["order_id"] == "ord-1"
    assert data["broker"] == "recording_broker"
    assert data["side"] == "SELL"
    assert data["quantity"] == 7
    assert data["order_type"] == "LIMIT"
    assert data["time_in_force"] == "DAY"
    assert data["price"] == 425.5
    assert res.metadata.get("submitted") is True
    # audit trail written once after the real broker call
    assert recorded and recorded[0]["order_id"] == "ord-1"


# ── EXEC plan honesty (M) ───────────────────────────────────────────────────


def test_exec_plan_stamps_execution_mode_planned(monkeypatch: Any) -> None:
    import showme.chart_history as ch
    from showme.engine.functions.trade.exec import EXECFunction

    class _History:
        source = "binance_spot"
        rows = [
            {
                "time": 1_700_000_000 + i * 300,
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": 10.0 + i,
            }
            for i in range(30)
        ]

    async def _fake_fetch(**kwargs: Any) -> _History:
        return _History()

    monkeypatch.setattr(ch, "fetch_binance_history", _fake_fetch, raising=True)

    fn = EXECFunction()
    res = _run(
        fn.execute(
            action="plan",
            symbol="BTCUSDT",
            algo="TWAP",
            target_qty=10,
            horizon_seconds=300,
            slices=6,
        )
    )
    data = res.data
    assert data["status"] == "ok"
    assert data["action"] == "plan"
    assert data["cards"]["execution_mode"] == "planned"
    # The parent order row is explicitly lifecycle-"planned" too.
    assert data["orders"][0]["status"] == "planned"


# ── DAPI mutating-count agreement (L) ───────────────────────────────────────


def test_dapi_state_changing_counts_depends_rows() -> None:
    fn = DAPIFunction()
    fn.deps = FunctionDeps()
    res = _run(fn.execute())
    rows = res.data["rows"]
    yes_only = sum(
        1 for r in rows if str(r.get("mutates_state", "")).strip().lower().startswith("yes")
    )
    depends = sum(
        1 for r in rows if str(r.get("mutates_state", "")).strip().lower().startswith("depends")
    )
    assert depends >= 1, "curated manifest must contain 'depends' routes"
    # Old behaviour counted only 'yes' routes; the pane's mutating filter
    # counts 'depends' too, so the summary must include them.
    assert res.data["summary"]["state_changing"] == yes_only + depends
