"""PaperBroker — in-memory deterministic broker for tests + bootstrap.

The adapter is deliberately minimal:

* Cash and equity tracked as floats.
* Market orders fill immediately at the supplied last_price (or price hint
  passed via ``submit_order(notes="last:123.45")``).
* Limit orders go ACCEPTED until the caller explicitly fills them through
  ``simulate_fill(id, price)`` — the SCAN harness uses this so deterministic
  tests don't depend on a price feed.
* No margin, no slippage, no fees. Just shape parity with real brokers.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .base import (
    BaseBroker,
    BrokerError,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    TimeInForce,
)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class PaperBroker(BaseBroker):
    name = "paper"

    def __init__(
        self,
        starting_cash: float = 100_000.0,
        *,
        name: str = "paper",
    ) -> None:
        self.name = name
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}

    # ── Snapshots ────────────────────────────────────────────────────────

    async def account(self) -> dict[str, Any]:
        equity = self.cash + sum(
            (p.current_price or p.entry_price or 0.0) * p.quantity * (1 if p.side == OrderSide.BUY else -1)
            for p in self._positions.values()
        )
        return {
            "name": self.name,
            "cash": round(self.cash, 4),
            "equity": round(equity, 4),
            "buying_power": round(self.cash, 4),
            "starting_cash": self.starting_cash,
            "n_positions": len(self._positions),
            "n_orders": len(self._orders),
        }

    async def list_positions(self) -> list[Position]:
        return list(self._positions.values())

    async def list_orders(
        self, *, status: str = "open", limit: int = 100,
    ) -> list[Order]:
        items = sorted(
            self._orders.values(), key=lambda o: o.submitted_at, reverse=True,
        )
        if status == "open":
            items = [o for o in items if o.status in (OrderStatus.NEW, OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED)]
        elif status == "closed":
            items = [o for o in items if o.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED)]
        return items[:limit]

    # ── Mutations ────────────────────────────────────────────────────────

    async def submit_order(
        self,
        *,
        symbol: str,
        side: OrderSide | str,
        quantity: float,
        order_type: OrderType | str = OrderType.MARKET,
        time_in_force: TimeInForce | str = TimeInForce.DAY,
        limit_price: float | None = None,
        stop_price: float | None = None,
        notes: str = "",
    ) -> Order:
        if quantity <= 0:
            raise BrokerError("quantity must be positive")
        s = self.coerce_side(side)
        t = self.coerce_type(order_type)
        tif = self.coerce_tif(time_in_force)
        order = Order(
            id=str(uuid.uuid4()),
            symbol=symbol.upper(),
            side=s,
            quantity=float(quantity),
            order_type=t,
            time_in_force=tif,
            limit_price=limit_price,
            stop_price=stop_price,
            notes=notes,
        )
        if t == OrderType.MARKET:
            price = self._hint_price(symbol, notes) or limit_price or 0.0
            self._fill(order, price)
        else:
            order.status = OrderStatus.ACCEPTED
        self._orders[order.id] = order
        return order

    async def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if not order:
            return False
        if order.status not in (OrderStatus.NEW, OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED):
            return False
        order.status = OrderStatus.CANCELLED
        return True

    async def close_position(
        self, symbol: str, *, quantity: float | None = None,
    ) -> Order:
        pos = self._positions.get(symbol.upper())
        if not pos:
            raise BrokerError(f"no position for {symbol}")
        qty = quantity if quantity is not None else pos.quantity
        if qty > pos.quantity:
            raise BrokerError(f"requested {qty} > held {pos.quantity}")
        opposite = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY
        return await self.submit_order(
            symbol=symbol,
            side=opposite,
            quantity=qty,
            order_type=OrderType.MARKET,
            notes=f"close_position {symbol}",
        )

    # ── Test hook: simulate fill for limit/stop orders ───────────────────

    def simulate_fill(self, order_id: str, price: float) -> Order:
        order = self._orders.get(order_id)
        if not order:
            raise BrokerError(f"unknown order {order_id}")
        if order.status not in (OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED):
            raise BrokerError(f"order {order_id} not fillable in status {order.status}")
        self._fill(order, price)
        return order

    # ── Internals ────────────────────────────────────────────────────────

    def _hint_price(self, symbol: str, notes: str) -> float | None:
        # Allow callers to pass price hints via notes for deterministic tests.
        if "last:" in notes:
            try:
                return float(notes.split("last:", 1)[1].split()[0])
            except (ValueError, IndexError):
                return None
        pos = self._positions.get(symbol.upper())
        if pos and pos.current_price:
            return float(pos.current_price)
        return None

    def _fill(self, order: Order, price: float) -> None:
        notional = order.quantity * float(price)
        order.avg_fill_price = float(price)
        order.filled_quantity = order.quantity
        order.status = OrderStatus.FILLED
        order.filled_at = _now()
        sym = order.symbol.upper()
        sign = 1 if order.side == OrderSide.BUY else -1
        # Update cash: buys debit, sells credit.
        self.cash -= sign * notional
        # Update position: net qty in BUY direction.
        existing = self._positions.get(sym)
        if existing:
            new_qty = (
                existing.quantity * (1 if existing.side == OrderSide.BUY else -1)
                + order.quantity * sign
            )
            if abs(new_qty) < 1e-9:
                # Realize P&L when flattening.
                if existing.entry_price is not None:
                    realized = (
                        (float(price) - float(existing.entry_price))
                        * existing.quantity
                        * (1 if existing.side == OrderSide.BUY else -1)
                    )
                    existing.realized_pnl += realized
                self._positions.pop(sym, None)
            else:
                # Recompute avg entry on additions, keep on reductions.
                add_qty = order.quantity if (
                    (existing.side == OrderSide.BUY and order.side == OrderSide.BUY)
                    or (existing.side == OrderSide.SELL and order.side == OrderSide.SELL)
                ) else 0
                if add_qty and existing.entry_price is not None:
                    total_cost = (
                        existing.entry_price * existing.quantity
                        + float(price) * add_qty
                    )
                    existing.entry_price = total_cost / (existing.quantity + add_qty)
                existing.quantity = abs(new_qty)
                existing.side = (
                    OrderSide.BUY if new_qty > 0 else OrderSide.SELL
                )
                existing.current_price = float(price)
        else:
            self._positions[sym] = Position(
                symbol=sym,
                side=order.side,
                quantity=order.quantity,
                entry_price=float(price),
                current_price=float(price),
            )
