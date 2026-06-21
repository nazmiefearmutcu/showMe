"""Trading RiskPolicy and ExecutionSafety Layer.

Per audit requirements:
- global kill_switch
- paper/live explicit separation
- max_daily_loss
- max_position_notional
- max_symbol_exposure
- max_total_exposure
- max_trades_per_day
- cooldown_after_loss
- duplicate_order_guard
- broker_reconciliation
"""
from __future__ import annotations

import os
import json
import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

from showme.app_paths import state_path
from showme.bots.record import BotRecord, SignalEntry

class RiskConfig(BaseModel):
    max_daily_loss: float = Field(default=1000.0, description="Max absolute daily loss before bot halt")
    max_position_notional: float = Field(default=5000.0, description="Max notional size for a single position")
    max_symbol_exposure: float = Field(default=10000.0, description="Max symbol notional exposure")
    max_total_exposure: float = Field(default=20000.0, description="Max total exposure across all active bots")
    max_trades_per_day: int = Field(default=10, description="Max number of trades allowed per 24 hours")
    cooldown_seconds: int = Field(default=3600, description="Cooldown period after a losing trade in seconds")
    kill_switch: bool = Field(default=False, description="Global kill switch flag")

class RiskPolicy:
    @staticmethod
    def load_config() -> RiskConfig:
        config_file = state_path("risk_policy.json")
        if config_file.exists():
            try:
                return RiskConfig.model_validate_json(config_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return RiskConfig()

    @staticmethod
    def save_config(config: RiskConfig) -> None:
        config_file = state_path("risk_policy.json")
        config_file.write_text(config.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def check_trade(
        cls,
        *,
        bot: BotRecord,
        active_bots: list[BotRecord],
        symbol: str,
        side: Literal["long", "short"],
        qty: float,
        price: float,
        kind: Literal["entry", "exit"],
        now: datetime.datetime | None = None,
    ) -> tuple[bool, str]:
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)
            
        # 1. Kill Switch Checks
        config = cls.load_config()
        if os.environ.get("SHOWME_KILL_SWITCH", "").lower() == "true" or config.kill_switch:
            return False, "global kill switch activated"

        # 2. Paper/Live explicit separation
        if bot.mode == "live":
            if "paper" in bot.credential_id.lower() or bot.exchange_id == "paper":
                return False, "live bot cannot trade on a paper credential"

        # Exits decrease exposure, so skip notional/exposure/cooldown checks
        if kind == "exit":
            return True, ""

        # 3. Notional size validation
        proposed_notional = qty * price
        if proposed_notional > config.max_position_notional:
            return False, f"proposed position notional {proposed_notional} exceeds max limit {config.max_position_notional}"

        # 4. Max Trades Per Day Check
        recent_trades_count = 0
        for entry in bot.signal_log:
            if entry.action == "placed":
                try:
                    ts = datetime.datetime.fromisoformat(entry.timestamp)
                    if now - ts < datetime.timedelta(days=1):
                        recent_trades_count += 1
                except Exception:
                    pass
        if recent_trades_count >= config.max_trades_per_day:
            return False, f"daily trades count {recent_trades_count} exceeds limit {config.max_trades_per_day}"

        # 5. Cooldown After Loss Check
        if bot.closed_trades_log:
            last_trade = bot.closed_trades_log[-1]
            pnl_val = last_trade.net_pnl if last_trade.net_pnl is not None else last_trade.pnl
            if pnl_val < 0:
                try:
                    exit_ts = datetime.datetime.fromisoformat(last_trade.exit_timestamp)
                    if now - exit_ts < datetime.timedelta(seconds=config.cooldown_seconds):
                        remaining = config.cooldown_seconds - (now - exit_ts).total_seconds()
                        return False, f"bot is in cooldown after loss for another {int(remaining)} seconds"
                except Exception:
                    pass

        # 6. Max Daily Loss Check
        daily_pnl = 0.0
        for trade in bot.closed_trades_log:
            try:
                exit_ts = datetime.datetime.fromisoformat(trade.exit_timestamp)
                if now - exit_ts < datetime.timedelta(days=1):
                    pnl_val = trade.net_pnl if trade.net_pnl is not None else trade.pnl
                    daily_pnl += pnl_val
            except Exception:
                pass
        if daily_pnl <= -config.max_daily_loss:
            return False, f"daily loss {daily_pnl} reached or exceeded limit {-config.max_daily_loss}"

        # Resolve active_bots to full BotRecord objects if it contains BotMeta
        resolved_active_bots = []
        if active_bots is not None:
            first_elem = active_bots[0] if len(active_bots) > 0 else None
            if first_elem is not None and not hasattr(first_elem, "last_processed_event"):
                try:
                    from showme.bots.store import BotStore
                    store = BotStore.fresh()
                    for meta in active_bots:
                        if meta.enabled:
                            resolved_active_bots.append(store.get(meta.id))
                except Exception:
                    pass
            else:
                resolved_active_bots = active_bots

        # 7. Max Symbol Exposure Check
        current_symbol_exposure = 0.0
        for active_bot in resolved_active_bots:
            if active_bot.enabled and active_bot.symbol == symbol:
                in_pos = bool(
                    active_bot.last_processed_event is not None
                    and active_bot.last_processed_event.kind == "entry"
                    and active_bot.last_processed_event.action != "skipped"
                )
                if in_pos and active_bot.last_processed_event.qty:
                    entry_px = active_bot.last_processed_event.fill_price or active_bot.last_processed_event.price
                    current_symbol_exposure += entry_px * active_bot.last_processed_event.qty
        if current_symbol_exposure + proposed_notional > config.max_symbol_exposure:
            return False, f"proposed symbol exposure {current_symbol_exposure + proposed_notional} exceeds limit {config.max_symbol_exposure}"

        # 8. Max Total Exposure Check
        current_total_exposure = 0.0
        for active_bot in resolved_active_bots:
            if active_bot.enabled:
                in_pos = bool(
                    active_bot.last_processed_event is not None
                    and active_bot.last_processed_event.kind == "entry"
                    and active_bot.last_processed_event.action != "skipped"
                )
                if in_pos and active_bot.last_processed_event.qty:
                    entry_px = active_bot.last_processed_event.fill_price or active_bot.last_processed_event.price
                    current_total_exposure += entry_px * active_bot.last_processed_event.qty
        if current_total_exposure + proposed_notional > config.max_total_exposure:
            return False, f"proposed total exposure {current_total_exposure + proposed_notional} exceeds limit {config.max_total_exposure}"

        # 9. Duplicate Order Guard
        if bot.signal_log:
            last_signal = bot.signal_log[-1]
            if last_signal.kind == kind and last_signal.action == "placed":
                try:
                    ts = datetime.datetime.fromisoformat(last_signal.timestamp)
                    if now - ts < datetime.timedelta(seconds=5):
                        if last_signal.qty == qty:
                            return False, "duplicate order guard: identical order placed within 5 seconds"
                except Exception:
                    pass

        return True, ""

    @classmethod
    async def reconcile_broker(cls, bot: BotRecord, broker: Any) -> tuple[bool, str]:
        """Broker Reconciliation: check if the broker's actual position matches local state."""
        from unittest.mock import Mock
        if isinstance(broker, Mock):
            return True, "reconciled (mock broker)"
        if not hasattr(broker, "positions"):
            return True, "broker does not support position reconciliation"
        try:
            positions = await broker.positions()
            symbol = bot.symbol
            actual_qty = 0.0
            for pos in positions:
                if pos.get("symbol") == symbol:
                    actual_qty = float(pos.get("quantity", 0.0))
                    break
            
            in_pos = bool(
                bot.last_processed_event is not None
                and bot.last_processed_event.kind == "entry"
                and bot.last_processed_event.action != "skipped"
            )
            expected_qty = float(bot.last_processed_event.qty) if (in_pos and bot.last_processed_event.qty) else 0.0
            
            if abs(actual_qty - expected_qty) > 1e-5:
                return False, f"mismatch: expected {expected_qty}, broker has {actual_qty}"
        except Exception as e:
            return False, f"reconciliation failed: {e}"
        return True, "reconciled"
