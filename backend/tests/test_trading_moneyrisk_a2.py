"""Task A2 money-risk regression tests (execution/decision/position cluster).

Covers:
  - F1/H2: daily-loss gate must not freeze SL/TP auto-close of an OPEN position
  - F2/H1: live CLOSE respects executedQty (partial fills), dust guard,
    real commission from fills, zero-fill-price guard
  - F3: paper spot-short credits sale proceeds (profitable short grows balance)
  - F4/H14: decision engine passes the real SL distance to calculate_leverage
  - F5: leveraged paper sizing caps notional at free margin (balance -
    allocated margin), not the full untouched balance
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from showme.engine.trading.decision_engine import DecisionEngine  # noqa: E402
from showme.engine.trading.execution_engine import ExecutionEngine  # noqa: E402
from showme.engine.trading.leverage_manager import LeverageManager  # noqa: E402
from showme.engine.trading.order_models import (  # noqa: E402
    Position,
    PositionSide,
    TradeAction,
)
from showme.engine.trading.position_manager import PositionManager  # noqa: E402
from showme.engine.indicators.base import Signal  # noqa: E402


RISK_CONFIG = {"stop_loss_pct": 0.02, "take_profit_pct": 0.04}
BASE_CONFIG: dict = {
    "market_type": "futures",
    "risk": dict(RISK_CONFIG),
    "paper": {"fee_pct": 0.0005},
}


def _make_position(
    symbol: str = "BTCUSDT",
    side: PositionSide = PositionSide.LONG,
    entry: float = 100.0,
    quantity: float = 1.0,
    leverage: int = 1,
) -> Position:
    return Position(
        symbol=symbol,
        side=side,
        entry_price=entry,
        quantity=quantity,
        stop_loss=entry * 0.98,
        take_profit=entry * 1.04,
        leverage=leverage,
    )


# ─────────────────────────── F1: daily-loss gate ───────────────────────────


def _decision_engine(pm: PositionManager, lm: Any = None) -> DecisionEngine:
    return DecisionEngine(config=dict(BASE_CONFIG), position_manager=pm, leverage_manager=lm)


def _consensus(signal: Signal = Signal.BUY, conf: int = 90) -> dict:
    return {
        "final_signal": signal.value,
        "confidence": conf,
        "should_trade": True,
        "risk_level": "MEDIUM",
        "risk_data": {"position_size_modifier": 1.0},
    }


def test_daily_loss_limit_blocks_new_entries() -> None:
    """With no position, a tripping daily-loss limit must still block entries."""
    pm = PositionManager(dict(BASE_CONFIG))
    pm.check_daily_loss_limit = lambda *a, **k: True  # type: ignore[assignment]
    engine = _decision_engine(pm)

    decision = engine.decide(
        symbol="BTCUSDT",
        consensus=_consensus(Signal.BUY),
        current_price=100.0,
        balance=10_000,
        daily_pnl=-600,
        daily_start_balance=10_000,
    )
    assert decision["action"] == TradeAction.NO_ACTION.value
    assert "NEW" in decision["reason"]


def test_daily_loss_limit_does_not_freeze_sl_auto_close() -> None:
    """H2 regression: with a position open, the loss limit must NOT swallow
    update_position / the C1 SL/TP auto-close — the exit must still fire."""
    pm = PositionManager(dict(BASE_CONFIG))
    pm.positions["BTCUSDT"] = _make_position()
    pm.check_daily_loss_limit = lambda *a, **k: True  # type: ignore[assignment]
    pm.update_position = lambda symbol, price: "stop_loss"  # type: ignore[assignment]
    engine = _decision_engine(pm)

    decision = engine.decide(
        symbol="BTCUSDT",
        consensus=_consensus(Signal.NEUTRAL),
        current_price=97.0,
        balance=10_000,
        daily_pnl=-600,
        daily_start_balance=10_000,
    )
    assert decision["action"] == TradeAction.CLOSE_LONG.value, decision
    assert "stop_loss" in decision["reason"]


def test_daily_loss_limit_holds_position_without_exit() -> None:
    """Position open, limit tripped, no SL/TP hit → HOLD (not a forced close)."""
    pm = PositionManager(dict(BASE_CONFIG))
    pm.positions["BTCUSDT"] = _make_position()
    pm.check_daily_loss_limit = lambda *a, **k: True  # type: ignore[assignment]
    pm.update_position = lambda symbol, price: None  # type: ignore[assignment]
    engine = _decision_engine(pm)

    decision = engine.decide(
        symbol="BTCUSDT",
        consensus=_consensus(Signal.NEUTRAL),
        current_price=100.5,
        balance=10_000,
        daily_pnl=-600,
        daily_start_balance=10_000,
    )
    assert decision["action"] == TradeAction.HOLD.value


# ──────────────── F2: live CLOSE partial fills / fees / guards ─────────────


LOT_INFO = {"filters": [{"filterType": "LOT_SIZE", "minQty": "0.0001", "stepSize": "0.0001"}]}


class FakeLiveClient:
    """Minimal client stub for the live execution path."""

    def __init__(
        self,
        symbol_info: Optional[dict] = None,
        sell_result: Optional[dict] = None,
        buy_result: Optional[dict] = None,
    ) -> None:
        self.symbol_info = symbol_info
        self.sell_result = sell_result
        self.buy_result = buy_result
        self.sell_calls: list[float] = []
        self.buy_calls: list[float] = []

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        return self.symbol_info

    def place_market_sell(self, symbol: str, quantity: float) -> Optional[dict]:
        self.sell_calls.append(quantity)
        return self.sell_result

    def place_market_buy(self, symbol: str, quantity: float) -> Optional[dict]:
        self.buy_calls.append(quantity)
        return self.buy_result


def _live_engine(client: FakeLiveClient, pm: PositionManager) -> ExecutionEngine:
    config = {"mode": "live", "paper": {"starting_balance": 10_000.0, "fee_pct": 0.001}}
    return ExecutionEngine(config, client, pm)  # type: ignore[arg-type]


def _close_decision(symbol: str = "BTCUSDT", price: float = 90.0) -> dict:
    return {
        "action": TradeAction.CLOSE_LONG.value,
        "symbol": symbol,
        "quantity": 1.0,
        "price": price,
        "reason": "test-close",
        "leverage": 1,
    }


def test_live_close_partial_fill_books_partial_and_keeps_remainder() -> None:
    """H1 regression: a 0.6/1.0 filled sell must book ONLY 0.6 and keep the
    remaining 0.4 tracked, with the REAL commission from fills."""
    pm = PositionManager(dict(BASE_CONFIG))
    pm.positions["BTCUSDT"] = _make_position(quantity=1.0)
    client = FakeLiveClient(
        symbol_info=LOT_INFO,
        sell_result={
            "executedQty": "0.6",
            "orderId": 7,
            "fills": [{"price": "90.0", "qty": "0.6", "commission": "0.054"}],
        },
    )
    engine = _live_engine(client, pm)

    result = engine.execute(_close_decision())

    assert result["executed"] is True
    assert result["partial"] is True
    # Remainder still tracked with its original entry price.
    remainder = pm.get_position("BTCUSDT")
    assert remainder is not None
    assert remainder.quantity == 0.4
    assert remainder.entry_price == 100.0
    # Partial record books only the filled qty with the REAL commission.
    record = pm.trade_history[-1]
    assert record.quantity == 0.6
    assert record.fee == 0.054  # not the 0.114 paper-default fee
    assert record.pnl == round((90.0 - 100.0) * 0.6 - 0.054, 4)
    assert pm.total_realized_pnl == record.pnl


def test_live_close_full_fill_closes_position_completely() -> None:
    pm = PositionManager(dict(BASE_CONFIG))
    pm.positions["BTCUSDT"] = _make_position(quantity=1.0)
    client = FakeLiveClient(
        symbol_info=LOT_INFO,
        sell_result={
            "executedQty": "1.0",
            "orderId": 8,
            "fills": [{"price": "90.0", "qty": "1.0", "commission": "0.09"}],
        },
    )
    engine = _live_engine(client, pm)

    result = engine.execute(_close_decision())

    assert result["executed"] is True
    assert result["partial"] is False
    assert pm.get_position("BTCUSDT") is None
    record = pm.trade_history[-1]
    assert record.quantity == 1.0
    assert record.fee == 0.09


def test_live_close_without_fill_commission_falls_back_to_configured_fee() -> None:
    pm = PositionManager(dict(BASE_CONFIG))
    pm.positions["BTCUSDT"] = _make_position(quantity=1.0)
    client = FakeLiveClient(
        symbol_info=LOT_INFO,
        sell_result={"executedQty": "1.0", "cummulativeQuoteQty": "90.0", "orderId": 9},
    )
    engine = _live_engine(client, pm)

    result = engine.execute(_close_decision())

    assert result["executed"] is True
    record = pm.trade_history[-1]
    # (entry*qty + exit*qty) * 0.001 configured fee
    assert record.fee == (100.0 * 1.0 + 90.0 * 1.0) * 0.001


def test_live_close_dust_guard_blocks_order_and_keeps_position() -> None:
    pm = PositionManager(dict(BASE_CONFIG))
    pm.positions["BTCUSDT"] = _make_position(quantity=0.00005)
    client = FakeLiveClient(symbol_info=LOT_INFO, sell_result={"executedQty": "0"})
    engine = _live_engine(client, pm)

    result = engine.execute(_close_decision())

    assert result["executed"] is False
    assert result["reason"] == "quantity below LOT_SIZE minQty"
    assert client.sell_calls == []  # no sell sent
    assert pm.get_position("BTCUSDT") is not None  # ledger intact
    assert pm.trade_history == []


def test_live_close_zero_fill_price_not_booked() -> None:
    """L1: a truthy ack without a fill price must NOT book a close (PnL would
    be the full notional); the position stays tracked for a retry."""
    pm = PositionManager(dict(BASE_CONFIG))
    pm.positions["BTCUSDT"] = _make_position(quantity=1.0)
    client = FakeLiveClient(
        symbol_info=LOT_INFO,
        sell_result={"executedQty": "0.6", "orderId": 10},  # no fills, no cumQuote
    )
    engine = _live_engine(client, pm)

    result = engine.execute(_close_decision())

    assert result["executed"] is False
    assert pm.get_position("BTCUSDT") is not None
    assert pm.trade_history == []


def test_live_open_zero_fill_price_not_booked() -> None:
    """L1: entry_price=0 would give TP=0 → instant close and full-notional
    'profit'. The open must refuse to book."""
    pm = PositionManager(dict(BASE_CONFIG))
    client = FakeLiveClient(
        symbol_info=LOT_INFO,
        buy_result={"executedQty": "0.5", "orderId": 11},  # no fills, no cumQuote
    )
    engine = _live_engine(client, pm)

    decision = {
        "action": TradeAction.OPEN_LONG.value,
        "symbol": "BTCUSDT",
        "quantity": 1.0,
        "price": 100.0,
        "reason": "test-open",
        "leverage": 1,
    }
    result = engine.execute(decision)

    assert result["executed"] is False
    assert pm.get_position("BTCUSDT") is None
    assert pm.trade_history == []


def test_close_position_default_signature_unchanged() -> None:
    """Backward compat: positional (symbol, price, reason, fee_pct) call still
    closes the FULL position."""
    pm = PositionManager(dict(BASE_CONFIG))
    pm.positions["BTCUSDT"] = _make_position(quantity=2.0)

    record = pm.close_position("BTCUSDT", 90.0, "manual", 0.002)

    assert record is not None
    assert record.quantity == 2.0
    assert record.fee == (100.0 * 2.0 + 90.0 * 2.0) * 0.002
    assert pm.get_position("BTCUSDT") is None


def test_close_position_partial_reduces_quantity() -> None:
    pm = PositionManager(dict(BASE_CONFIG))
    pm.positions["BTCUSDT"] = _make_position(quantity=2.0)

    record = pm.close_position("BTCUSDT", 90.0, "partial", filled_qty=0.5)

    assert record is not None
    assert record.quantity == 0.5
    assert pm.get_position("BTCUSDT").quantity == 1.5
    # Second full close books the remainder.
    record2 = pm.close_position("BTCUSDT", 95.0, "rest")
    assert record2 is not None
    assert record2.quantity == 1.5
    assert pm.get_position("BTCUSDT") is None


# ────────────────────── F3: paper spot-short accounting ────────────────────


def _paper_engine(start_balance: float = 10_000.0) -> tuple[ExecutionEngine, PositionManager]:
    config = {
        "mode": "paper",
        "risk": dict(RISK_CONFIG),
        "paper": {"starting_balance": start_balance, "fee_pct": 0.001},
    }
    pm = PositionManager(config)
    return ExecutionEngine(config, None, pm), pm  # type: ignore[arg-type]


def test_paper_profitable_short_increases_balance() -> None:
    """F3 regression: a profitable leverage-1 short must INCREASE the paper
    balance (old code drained it by ~the full notional)."""
    engine, pm = _paper_engine()

    open_res = engine._execute_paper(
        TradeAction.OPEN_SHORT, "BTCUSDT", 1.0, 100.0, "short-open", leverage=1
    )
    assert open_res["executed"] is True
    # proceeds credited, entry fee debited: 10000 - 0.1 + 100
    assert open_res["balance_after"] == 10_099.9

    close_res = engine._execute_paper(
        TradeAction.CLOSE_SHORT, "BTCUSDT", 1.0, 90.0, "short-close", leverage=1
    )
    assert close_res["executed"] is True
    record = pm.trade_history[-1]
    assert record.pnl == 9.81  # gross 10 - round-trip fee 0.19
    # 10099.9 - (buyback 90 + fee 0.19) = 10009.71  → balance grew by 9.71
    assert engine.paper_balance == 10_009.71
    assert engine.paper_balance > 10_000.0


def test_paper_losing_short_decreases_balance() -> None:
    engine, _pm = _paper_engine()
    engine._execute_paper(TradeAction.OPEN_SHORT, "BTCUSDT", 1.0, 100.0, "o", leverage=1)
    close_res = engine._execute_paper(
        TradeAction.CLOSE_SHORT, "BTCUSDT", 1.0, 110.0, "c", leverage=1
    )
    assert close_res["executed"] is True
    # 10099.9 - (110 + 0.21) = 9989.69 → loss hits the balance
    assert engine.paper_balance == 9_989.69


# ──────────────── F4: liquidation-aware leverage clamp wiring ──────────────


class RecordingLeverageManager:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def calculate_leverage(self, symbol: str, confidence: int, sl_distance_pct=None) -> int:
        self.calls.append(
            {"symbol": symbol, "confidence": confidence, "sl_distance_pct": sl_distance_pct}
        )
        return 5


def test_calculate_leverage_receives_risk_config_sl_distance() -> None:
    pm = PositionManager(dict(BASE_CONFIG))
    pm.check_daily_loss_limit = lambda *a, **k: False  # type: ignore[assignment]
    lm = RecordingLeverageManager()
    engine = _decision_engine(pm, lm)

    decision = engine.decide(
        symbol="BTCUSDT",
        consensus=_consensus(Signal.BUY),
        current_price=100.0,
        balance=10_000,
        daily_pnl=0,
        daily_start_balance=10_000,
    )
    assert decision["leverage"] == 5
    assert lm.calls[0]["sl_distance_pct"] == 0.02  # the risk config value


def test_h14_sl_cap_is_live_with_real_leverage_manager() -> None:
    """Integration: BTC @100% confidence = 100x raw; the default 2.5% SL must
    cap it at 0.8/0.025 = 32x (pre-fix the cap never ran → 100x)."""
    config = dict(BASE_CONFIG)
    config["risk"] = {"stop_loss_pct": 0.025, "take_profit_pct": 0.05}
    pm = PositionManager(config)
    pm.check_daily_loss_limit = lambda *a, **k: False  # type: ignore[assignment]
    lm = LeverageManager({"leverage": {"enabled": True}}, binance_client=None)
    engine = DecisionEngine(config=config, position_manager=pm, leverage_manager=lm)

    decision = engine.decide(
        symbol="BTCUSDT",
        consensus=_consensus(Signal.BUY, conf=100),
        current_price=100.0,
        balance=10_000,
        daily_pnl=0,
        daily_start_balance=10_000,
    )
    assert decision["leverage"] == 32


# ──────────────────── F5: leveraged paper free-margin cap ──────────────────


def test_leveraged_paper_open_capped_by_allocated_margin() -> None:
    """F5: with a 10x position holding 5000 margin, a second open must be
    capped by (balance - allocated_margin) * leverage * 0.99, not by the
    untouched balance."""
    engine, pm = _paper_engine()

    first = engine._execute_paper(
        TradeAction.OPEN_LONG, "BTCUSDT", 500.0, 100.0, "open-1", leverage=10
    )
    assert first["executed"] is True
    assert first["quantity"] == 500.0  # notional 50k < cap, uncapped
    assert engine.paper_balance == 9_950.0  # only the fee was debited

    second = engine._execute_paper(
        TradeAction.OPEN_LONG, "ETHUSDT", 1000.0, 100.0, "open-2", leverage=10
    )
    assert second["executed"] is True
    # free margin = 9950 - (100*500)/10 = 4950 → cap = 4950*10*0.99 = 49005
    expected_qty = 49_005.0 / (100.0 * 1.001)
    assert second["quantity"] == round(expected_qty, 8)
    assert second["quantity"] < 500.0  # clamped far below the requested 1000
    assert pm.get_position("ETHUSDT").quantity == second["quantity"]


def test_allocated_margin_ignores_unleveraged_positions() -> None:
    engine, pm = _paper_engine()
    pm.positions["SPOT"] = _make_position(symbol="SPOT", quantity=100.0, leverage=1)
    pm.positions["PERP"] = _make_position(symbol="PERP", quantity=50.0, leverage=10)
    # only PERP counts: (100 * 50) / 10
    assert engine._allocated_margin() == 500.0
