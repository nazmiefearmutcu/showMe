"""Bundle C / C1 regression tests.

Verify that the decision engine auto-closes a position when SL/TP is hit,
instead of merely setting a cosmetic warning. Also verify that warnings
accumulate in a list instead of overwriting each other.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.indicators.base import Signal  # noqa: E402
from showme.engine.trading.decision_engine import DecisionEngine  # noqa: E402
from showme.engine.trading.order_models import (  # noqa: E402
    Position,
    PositionSide,
    TradeAction,
)
from showme.engine.trading.position_manager import PositionManager  # noqa: E402


def _make_engine(*, exit_reason: str | None) -> DecisionEngine:
    """Build a DecisionEngine whose position-manager will report ``exit_reason``."""
    config: dict = {
        "market_type": "futures",
        "risk": {"stop_loss_pct": 0.02, "take_profit_pct": 0.04},
        "paper": {"fee_pct": 0.0005},
    }
    pm = PositionManager(config)
    pm.positions["BTCUSDT"] = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        entry_price=100.0,
        quantity=1.0,
        stop_loss=98.0,
        take_profit=104.0,
        leverage=10,
    )

    # Monkey-patch update_position to return the desired exit_reason.
    def _fake_update(symbol: str, current_price: float) -> str | None:
        return exit_reason

    pm.update_position = _fake_update  # type: ignore[assignment]

    # daily-loss-limit check: stub to always pass
    pm.check_daily_loss_limit = lambda *args, **kwargs: False  # type: ignore[assignment]

    return DecisionEngine(config=config, position_manager=pm, leverage_manager=None)


def _consensus(signal: Signal, conf: int = 75) -> dict:
    return {
        "final_signal": signal.value,
        "confidence": conf,
        "should_trade": True,
        "risk_level": "MEDIUM",
        "risk_data": {"position_size_modifier": 1.0},
    }


def test_sl_hit_emits_close_long_decision() -> None:
    """SL hit on a LONG position must emit CLOSE_LONG, not HOLD with a warning."""
    engine = _make_engine(exit_reason="sl_hit")
    decision = engine.decide(
        symbol="BTCUSDT",
        consensus=_consensus(Signal.NEUTRAL),
        current_price=97.5,
        balance=10_000,
        daily_pnl=0,
        daily_start_balance=10_000,
    )
    assert decision["action"] == TradeAction.CLOSE_LONG.value, decision
    assert decision["quantity"] == 1.0
    assert "sl_hit" in decision["reason"]


def test_tp_hit_emits_close_long_decision() -> None:
    engine = _make_engine(exit_reason="tp_hit")
    decision = engine.decide(
        symbol="BTCUSDT",
        consensus=_consensus(Signal.NEUTRAL),
        current_price=104.5,
        balance=10_000,
        daily_pnl=0,
        daily_start_balance=10_000,
    )
    assert decision["action"] == TradeAction.CLOSE_LONG.value
    assert "tp_hit" in decision["reason"]


def test_sl_hit_on_short_emits_close_short() -> None:
    engine = _make_engine(exit_reason="sl_hit")
    # Convert position to SHORT.
    engine.position_manager.positions["BTCUSDT"].side = PositionSide.SHORT
    decision = engine.decide(
        symbol="BTCUSDT",
        consensus=_consensus(Signal.NEUTRAL),
        current_price=102.5,
        balance=10_000,
        daily_pnl=0,
        daily_start_balance=10_000,
    )
    assert decision["action"] == TradeAction.CLOSE_SHORT.value


def test_no_exit_holds_position() -> None:
    """When update_position returns None, no auto-close should fire."""
    engine = _make_engine(exit_reason=None)
    decision = engine.decide(
        symbol="BTCUSDT",
        consensus=_consensus(Signal.NEUTRAL),
        current_price=100.5,
        balance=10_000,
        daily_pnl=0,
        daily_start_balance=10_000,
    )
    assert decision["action"] == TradeAction.HOLD.value


def test_warnings_list_accumulates_signal_reversal() -> None:
    """C1 fix part 2: warnings should accumulate, not overwrite."""
    engine = _make_engine(exit_reason=None)
    pos = engine.position_manager.positions["BTCUSDT"]
    # Pre-seed a warning to verify accumulation.
    pos.warnings = ["earlier:warn"]  # type: ignore[attr-defined]

    decision = engine.decide(
        symbol="BTCUSDT",
        consensus=_consensus(Signal.STRONG_SELL),  # reversal vs LONG
        current_price=100.5,
        balance=10_000,
        daily_pnl=0,
        daily_start_balance=10_000,
    )
    assert decision["action"] == TradeAction.HOLD.value
    # Earlier warning preserved, new reversal warning appended.
    warns = getattr(pos, "warnings")
    assert "earlier:warn" in warns
    assert any("signal_reversed" in w for w in warns)
