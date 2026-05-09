"""Interactive Brokers adapter — TWS/IB Gateway via ib_insync."""

from __future__ import annotations

import os
from typing import Any

from showme.engine.core.broker import BaseBroker, BrokerOrder, BrokerPosition, BrokerBalance


class IBKRBrokerAdapter(BaseBroker):
    name = "ibkr"
    supports_short = True
    supports_leverage = True
    supported_asset_classes = ("EQUITY", "ETF", "BOND", "FX", "COMMODITY", "DERIVATIVE")

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.host = os.environ.get("IBKR_HOST", "127.0.0.1")
        self.port = int(os.environ.get("IBKR_PORT", "7497"))   # 7497 paper, 7496 live
        self.client_id = int(os.environ.get("IBKR_CLIENT_ID", "1"))
        self._ib = None

    async def connect(self) -> None:
        try:
            from ib_insync import IB  # type: ignore
            self._ib = IB()
            self._ib.connect(self.host, self.port, clientId=self.client_id)
            self._connected = True
        except Exception:
            self._connected = False

    async def disconnect(self) -> None:
        try:
            if self._ib:
                self._ib.disconnect()
        finally:
            self._connected = False
            self._ib = None

    async def place_order(self, order: BrokerOrder) -> str:
        if not self._connected:
            await self.connect()
        if not self._ib:
            return "ibkr:disconnected"
        from ib_insync import Stock, MarketOrder, LimitOrder  # type: ignore
        contract = Stock(order.instrument.symbol, "SMART", order.instrument.currency or "USD")
        action = "BUY" if order.side.value == "BUY" else "SELL"
        if order.order_type.value == "LIMIT" and order.price:
            ib_order = LimitOrder(action, order.quantity, order.price)
        else:
            ib_order = MarketOrder(action, order.quantity)
        trade = self._ib.placeOrder(contract, ib_order)
        return str(trade.order.orderId)

    async def cancel_order(self, order_id: str) -> bool:
        if not self._ib:
            return False
        try:
            for trade in self._ib.openTrades():
                if str(trade.order.orderId) == order_id:
                    self._ib.cancelOrder(trade.order)
                    return True
        except Exception:
            return False
        return False

    async def get_open_orders(self) -> list[dict[str, Any]]:
        return []

    async def get_positions(self) -> list[BrokerPosition]:
        return []

    async def get_balance(self) -> list[BrokerBalance]:
        return []
