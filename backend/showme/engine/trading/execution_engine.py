"""Execution engine - handles order placement for paper and live modes."""

from typing import Any, Optional

from showme.engine.api.binance_client import BinanceClient
from showme.engine.trading.order_models import (
    TradeAction, PositionSide,
)
from showme.engine.trading.position_manager import PositionManager
from showme.engine.utils.logger import get_logger

logger = get_logger("trading.execution_engine")


class ExecutionEngine:
    """Executes trading decisions in either paper or live mode."""

    def __init__(
        self,
        config: dict[str, Any],
        binance_client: BinanceClient,
        position_manager: PositionManager,
    ) -> None:
        self.config = config
        self.client = binance_client
        self.position_manager = position_manager
        self.mode = config.get("mode", "paper")
        self.paper_config = config.get("paper", {})
        self.paper_balance: float = self.paper_config.get("starting_balance", 10000.0)
        self.paper_fee_pct: float = self.paper_config.get("fee_pct", 0.001)

    def execute(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Execute a trading decision. Returns execution result."""
        action = TradeAction(decision["action"])
        symbol = decision["symbol"]
        quantity = decision["quantity"]
        price = decision["price"]
        leverage = decision.get("leverage", 1)

        if action in (TradeAction.HOLD, TradeAction.NO_ACTION):
            return {
                "executed": False,
                "action": action.value,
                "reason": decision["reason"],
            }

        # DEFAULT-SAFE gate: only an exact "live" may reach real orders. The
        # old inverted check (`!= "paper"` → live) sent a typo'd mode such as
        # "Paper" or "live " to the REAL broker.
        if self.mode == "paper":
            return self._execute_paper(action, symbol, quantity, price, decision["reason"], leverage)
        if self.mode == "live":
            return self._execute_live(action, symbol, quantity, price, decision["reason"], leverage)
        logger.error(
            "Unknown execution mode %r — refusing to trade (expected 'paper' or 'live')",
            self.mode,
        )
        return {
            "executed": False,
            "action": action.value,
            "reason": f"Unknown mode {self.mode!r} — order refused",
        }

    def _execute_paper(
        self,
        action: TradeAction,
        symbol: str,
        quantity: float,
        price: float,
        reason: str,
        leverage: int = 1,
    ) -> dict[str, Any]:
        """Simulate order execution in paper mode.

        With leverage (futures):
          - margin = notional / leverage = (quantity * price) / leverage
          - We deduct margin from balance, not the full notional
          - PnL is based on full notional movement (already embedded in quantity)
        """
        notional = price * quantity
        fee = notional * self.paper_fee_pct
        is_leveraged = leverage > 1

        if action == TradeAction.OPEN_LONG:
            # Futures: margin KİLİTLENMEZ — sadece fee bakiyeden düşer.
            # Kayıp gerçekleştiğinde (close veya liquidation) asıl bakiyeyi etkiler.
            if is_leveraged:
                cost = fee
                # F5: cap new notional at FREE margin (balance minus margin
                # already allocated to open leveraged positions). Margin is
                # never locked on leveraged paper opens, so without this the
                # affordability cap re-checks the full untouched balance.
                free_margin = max(self.paper_balance - self._allocated_margin(), 0.0)
                # Notional sınırı: serbest marjin * leverage (risk tavanı)
                max_notional = free_margin * leverage * 0.99
                if notional > max_notional:
                    max_qty = max_notional / (price * (1 + self.paper_fee_pct))
                    if max_qty <= 0:
                        return {"executed": False, "action": action.value, "reason": "Insufficient paper balance"}
                    quantity = round(max_qty, 8)
                    notional = price * quantity
                    fee = notional * self.paper_fee_pct
                    cost = fee
            else:
                cost = notional + fee
                if cost > self.paper_balance:
                    max_qty = (self.paper_balance * 0.99) / (price * (1 + self.paper_fee_pct))
                    if max_qty <= 0:
                        return {"executed": False, "action": action.value, "reason": "Insufficient paper balance"}
                    quantity = round(max_qty, 8)
                    notional = price * quantity
                    fee = notional * self.paper_fee_pct
                    cost = notional + fee

            if cost > self.paper_balance:
                return {"executed": False, "action": action.value, "reason": "Insufficient paper balance"}

            self.paper_balance -= cost
            position = self.position_manager.open_position(
                symbol, PositionSide.LONG, price, quantity, leverage=leverage
            )
            logger.info(
                f"[PAPER] OPEN LONG | {symbol} | qty={quantity} | price={price} | "
                f"leverage={leverage}x | fee={fee:.4f} | balance={self.paper_balance:.2f}"
            )
            return {
                "executed": True,
                "action": action.value,
                "mode": "paper",
                "symbol": symbol,
                "side": "BUY",
                "quantity": quantity,
                "price": price,
                "fee": round(fee, 4),
                "leverage": leverage,
                "margin": round(cost, 4),
                "balance_after": round(self.paper_balance, 4),
                "position": position.to_dict(),
            }

        elif action == TradeAction.CLOSE_LONG:
            position = self.position_manager.get_position(symbol)
            pos_leverage = position.leverage if position else 1
            record = self.position_manager.close_position(
                symbol, price, reason, self.paper_fee_pct
            )
            if record:
                if pos_leverage > 1:
                    # Futures: margin kilidi yok — sadece realize PnL bakiyeye yansır
                    self.paper_balance += record.pnl
                else:
                    # Spot: satış gelirini geri ekle
                    proceeds = price * record.quantity - abs(record.fee)
                    self.paper_balance += proceeds
                logger.info(
                    f"[PAPER] CLOSE LONG | {symbol} | qty={record.quantity} | "
                    f"exit={price} | leverage={pos_leverage}x | PnL={record.pnl:.4f} | balance={self.paper_balance:.2f}"
                )
                return {
                    "executed": True,
                    "action": action.value,
                    "mode": "paper",
                    "symbol": symbol,
                    "side": "SELL",
                    "quantity": record.quantity,
                    "price": price,
                    "pnl": record.pnl,
                    "fee": record.fee,
                    "leverage": pos_leverage,
                    "balance_after": round(self.paper_balance, 4),
                    "reason": reason,
                }
            return {"executed": False, "action": action.value, "reason": "No position to close"}

        elif action == TradeAction.OPEN_SHORT:
            # Futures: margin KİLİTLENMEZ — sadece fee bakiyeden düşer.
            proceeds_credit = 0.0
            if is_leveraged:
                cost = fee
                # F5: leveraged opens only debit the fee, so margin is never
                # locked. Cap new notional at the FREE margin (balance minus
                # margin already allocated to open leveraged positions) —
                # otherwise N stacked positions each re-check against the
                # full untouched balance ≈ N×leverage account exposure.
                free_margin = max(self.paper_balance - self._allocated_margin(), 0.0)
                max_notional = free_margin * leverage * 0.99
                if notional > max_notional:
                    max_qty = max_notional / (price * (1 + self.paper_fee_pct))
                    if max_qty <= 0:
                        return {"executed": False, "action": action.value, "reason": "Insufficient paper balance"}
                    quantity = round(max_qty, 8)
                    notional = price * quantity
                    fee = notional * self.paper_fee_pct
                    cost = fee
            else:
                # F3 fix: only the entry fee is debited at open, but the
                # short-sale proceeds MUST be credited. The old code never
                # credited them while the close debits the full buyback + fee,
                # so even a maximally profitable short DRAINED the balance.
                cost = fee  # Spot short: entry fee only
                proceeds_credit = notional

            if cost > self.paper_balance:
                return {"executed": False, "action": action.value, "reason": "Insufficient paper balance"}

            self.paper_balance -= cost
            if proceeds_credit:
                self.paper_balance += proceeds_credit
            position = self.position_manager.open_position(
                symbol, PositionSide.SHORT, price, quantity, leverage=leverage
            )
            logger.info(
                f"[PAPER] OPEN SHORT | {symbol} | qty={quantity} | price={price} | "
                f"leverage={leverage}x | fee={fee:.4f} | balance={self.paper_balance:.2f}"
            )
            return {
                "executed": True,
                "action": action.value,
                "mode": "paper",
                "symbol": symbol,
                "side": "SELL",
                "quantity": quantity,
                "price": price,
                "fee": round(fee, 4),
                "leverage": leverage,
                "margin": round(cost, 4),
                "balance_after": round(self.paper_balance, 4),
                "position": position.to_dict(),
            }

        elif action == TradeAction.CLOSE_SHORT:
            position = self.position_manager.get_position(symbol)
            pos_leverage = position.leverage if position else 1
            record = self.position_manager.close_position(
                symbol, price, reason, self.paper_fee_pct
            )
            if record:
                if pos_leverage > 1:
                    # Futures: margin kilidi yok — sadece realize PnL bakiyeye yansır
                    self.paper_balance += record.pnl
                else:
                    # Spot short kapanışı — fee + kapanış farkı
                    cost = price * record.quantity + abs(record.fee)
                    self.paper_balance -= cost
                logger.info(
                    f"[PAPER] CLOSE SHORT | {symbol} | qty={record.quantity} | "
                    f"exit={price} | leverage={pos_leverage}x | PnL={record.pnl:.4f} | balance={self.paper_balance:.2f}"
                )
                return {
                    "executed": True,
                    "action": action.value,
                    "mode": "paper",
                    "symbol": symbol,
                    "side": "BUY",
                    "quantity": record.quantity,
                    "price": price,
                    "pnl": record.pnl,
                    "fee": record.fee,
                    "leverage": pos_leverage,
                    "balance_after": round(self.paper_balance, 4),
                    "reason": reason,
                }
            return {"executed": False, "action": action.value, "reason": "No short position to close"}

        return {"executed": False, "action": action.value, "reason": "Unhandled action"}

    def _execute_live(
        self,
        action: TradeAction,
        symbol: str,
        quantity: float,
        price: float,
        reason: str,
        leverage: int = 1,
    ) -> dict[str, Any]:
        """Execute real orders on Binance."""
        # Set leverage on Binance Futures before opening position
        if action in (TradeAction.OPEN_LONG, TradeAction.OPEN_SHORT) and leverage > 1:
            try:
                self.client.client.futures_change_leverage(symbol=symbol, leverage=leverage)
                logger.info(f"[LIVE] Leverage set to {leverage}x for {symbol}")
            except Exception as e:
                # ABORT, not warn-and-continue: if the leverage change fails the
                # exchange would fill at its current/default leverage, which can
                # be many times riskier than the sized-for leverage (sizing math
                # assumed `leverage`). Refusing the order is the safe outcome.
                logger.error(f"Failed to set leverage for {symbol}: {e} — order refused")
                return {
                    "executed": False,
                    "action": action.value,
                    "reason": f"Leverage change failed: {e}",
                }

        if action == TradeAction.OPEN_LONG:
            # Round quantity to symbol precision
            symbol_info = self.client.get_symbol_info(symbol)
            quantity = self._adjust_quantity(quantity, symbol_info)
            if quantity <= 0:
                return {"executed": False, "action": action.value, "reason": "Quantity too small after rounding"}

            order_result = self.client.place_market_buy(symbol, quantity)
            if order_result:
                filled_price = self._get_avg_fill_price(order_result)
                filled_qty = float(order_result.get("executedQty", quantity))
                # L1 fix: a truthy ack with no real fill must NOT become a
                # position — entry_price=0 gives TP=0 (instant close) and
                # books the full notional as "profit". Treat as failure and
                # keep the order_id for manual reconciliation.
                if filled_price <= 0 or filled_qty <= 0:
                    logger.error(
                        f"[LIVE] OPEN LONG {symbol} acked without fill "
                        f"(price={filled_price}, qty={filled_qty}) — position NOT booked "
                        f"(order_id={order_result.get('orderId')})"
                    )
                    return {
                        "executed": False,
                        "action": action.value,
                        "reason": "Order acked but no fill price/quantity — position NOT booked",
                        "order_id": order_result.get("orderId"),
                    }
                self.position_manager.open_position(
                    symbol, PositionSide.LONG, filled_price, filled_qty, leverage=leverage
                )
                logger.info(f"[LIVE] OPEN LONG | {symbol} | qty={filled_qty} | price={filled_price} | lev={leverage}x")
                return {
                    "executed": True,
                    "action": action.value,
                    "mode": "live",
                    "symbol": symbol,
                    "side": "BUY",
                    "quantity": filled_qty,
                    "price": filled_price,
                    "order_id": order_result.get("orderId"),
                    "status": order_result.get("status"),
                }
            return {"executed": False, "action": action.value, "reason": "Market buy failed"}

        elif action == TradeAction.CLOSE_LONG:
            position = self.position_manager.get_position(symbol)
            if not position:
                return {"executed": False, "action": action.value, "reason": "No position to close"}

            symbol_info = self.client.get_symbol_info(symbol)
            qty = self._adjust_quantity(position.quantity, symbol_info)
            # Dust guard (mirror of the OPEN branch): a floor-to-zero sell
            # would be rejected by the exchange while the old code still
            # deleted the whole ledger position.
            if qty <= 0:
                return {
                    "executed": False,
                    "action": action.value,
                    "reason": "quantity below LOT_SIZE minQty",
                }

            order_result = self.client.place_market_sell(symbol, qty)
            if order_result:
                filled_price = self._get_avg_fill_price(order_result)
                # L1 fix: never book a close at a zero/unfilled price — the
                # ledger position stays tracked so the close can be retried.
                if filled_price <= 0:
                    logger.error(
                        f"[LIVE] CLOSE LONG {symbol} acked without fill price — "
                        f"close NOT booked (order_id={order_result.get('orderId')})"
                    )
                    return {
                        "executed": False,
                        "action": action.value,
                        "reason": "Order acked but no fill price — close NOT booked",
                        "order_id": order_result.get("orderId"),
                    }
                # H1 fix: sell only what actually filled. A partial fill must
                # not be recorded as a full close — the remainder stays real
                # exposure on the exchange and has to remain tracked.
                filled_qty = float(order_result.get("executedQty", 0) or 0)
                # Real commission from fills; fall back to the configured fee.
                commission = self._get_total_commission(order_result)
                if commission is not None:
                    record = self.position_manager.close_position(
                        symbol, filled_price, reason,
                        filled_qty=filled_qty, fee_amount=commission,
                    )
                else:
                    record = self.position_manager.close_position(
                        symbol, filled_price, reason,
                        self.paper_fee_pct, filled_qty=filled_qty,
                    )
                logger.info(f"[LIVE] CLOSE LONG | {symbol} | price={filled_price} | filled={filled_qty}")
                return {
                    "executed": True,
                    "action": action.value,
                    "mode": "live",
                    "symbol": symbol,
                    "side": "SELL",
                    "quantity": filled_qty,
                    "price": filled_price,
                    "pnl": record.pnl if record else 0,
                    # Position still tracked after the close = partial fill,
                    # remainder remains real exposure and keeps its SL/TP.
                    "partial": bool(
                        record is not None
                        and self.position_manager.get_position(symbol) is not None
                    ),
                    "order_id": order_result.get("orderId"),
                    "reason": reason,
                }
            return {"executed": False, "action": action.value, "reason": "Market sell failed"}

        elif action in (TradeAction.OPEN_SHORT, TradeAction.CLOSE_SHORT):
            # Futures short execution - architecture ready
            logger.warning(f"Short execution requires futures mode. Action: {action.value}")
            return {"executed": False, "action": action.value, "reason": "Futures short not yet enabled"}

        return {"executed": False, "action": action.value, "reason": "Unhandled action"}

    def _adjust_quantity(self, quantity: float, symbol_info: Optional[dict]) -> float:
        """Adjust quantity to meet exchange lot size requirements.

        Q4 audit H22 fix: the previous implementation rounded the floor-result
        with banker's rounding which (a) could push qty back to non-step-size
        values and (b) risked half-even bias on borderline lots. We now use
        pure floor-by-step-size: ``floor(qty / step) * step``.
        """
        if not symbol_info:
            return round(quantity, 6)

        filters = {f["filterType"]: f for f in symbol_info.get("filters", [])}
        lot_size = filters.get("LOT_SIZE", {})
        min_qty = float(lot_size.get("minQty", 0.000001))
        step_size = float(lot_size.get("stepSize", 0.000001))

        if quantity < min_qty:
            return 0.0
        if step_size <= 0:
            return max(quantity, 0.0)

        # Q4 audit H22: pure floor-by-step. No second round() — the step
        # itself defines the precision.
        steps = int(quantity / step_size)
        adjusted = steps * step_size
        # Avoid float drift like 0.30000000000000004 by re-applying the
        # step's natural decimal precision when present.
        step_str = f"{step_size:.10f}".rstrip("0")
        if "." in step_str:
            precision = len(step_str.split(".")[-1])
            adjusted = round(adjusted, precision)
        return max(adjusted, 0.0)

    def _allocated_margin(self) -> float:
        """Sum the margin implicitly allocated to open leveraged paper positions.

        F5: leveraged paper opens debit only the fee ("margin kilitleNMEZ"),
        so the balance never shrinks as positions stack and every new open
        re-checks its notional against the full untouched balance — N
        concurrent positions at ``balance * leverage`` notional each give an
        effective account leverage of N × leverage. Computed on the fly from
        position_manager's EXISTING storage (no state-format change):
        margin per position = notional / leverage.
        """
        total = 0.0
        for position in self.position_manager.positions.values():
            if position.leverage > 1:
                total += (position.entry_price * position.quantity) / position.leverage
        return total

    @staticmethod
    def _get_total_commission(order_result: dict) -> Optional[float]:
        """Sum real commission from order fills (L2 fix).

        Returns ``None`` when fills carry no commission field so the caller
        can fall back to the configured fee. A present-but-zero commission
        (e.g. BNB discount) is real and returned as 0.0.
        """
        fills = order_result.get("fills") or []
        commissions = [
            float(f["commission"])
            for f in fills
            if f.get("commission") is not None
        ]
        if not commissions:
            return None
        return sum(commissions)

    def _get_avg_fill_price(self, order_result: dict) -> float:
        """Extract average fill price from order result."""
        fills = order_result.get("fills", [])
        if fills:
            total_qty = sum(float(f["qty"]) for f in fills)
            total_cost = sum(float(f["price"]) * float(f["qty"]) for f in fills)
            return total_cost / total_qty if total_qty > 0 else float(order_result.get("price", 0))
        # Fallback
        cum_quote = float(order_result.get("cummulativeQuoteQty", 0))
        exec_qty = float(order_result.get("executedQty", 0))
        if exec_qty > 0:
            return cum_quote / exec_qty
        return 0.0

    def get_balance(self) -> float:
        """Get current balance (paper or live)."""
        if self.mode == "paper":
            return self.paper_balance
        return self.client.get_account_balance("USDT")

    def set_paper_balance(self, balance: float) -> None:
        """Set paper balance (for state restore)."""
        self.paper_balance = balance
