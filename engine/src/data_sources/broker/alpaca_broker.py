"""Alpaca broker adapter — US equity, paper + live commission-free."""

from __future__ import annotations

import os
from typing import Any

from src.core.broker import (
    BaseBroker, BrokerOrder, BrokerPosition, BrokerBalance, OrderSide, OrderType
)


class AlpacaBrokerAdapter(BaseBroker):
    name = "alpaca"
    supports_short = True
    supports_leverage = False
    supported_asset_classes = ("EQUITY", "ETF")

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get("ALPACA_API_KEY", "")
        self.api_secret = os.environ.get("ALPACA_API_SECRET", "")
        self.use_paper = os.environ.get("ALPACA_USE_PAPER", "true").lower() == "true"
        self._client = None

    async def connect(self) -> None:
        try:
            from alpaca.trading.client import TradingClient  # type: ignore
            self._client = TradingClient(self.api_key, self.api_secret, paper=self.use_paper)
            self._connected = True
        except Exception:
            self._connected = False

    async def disconnect(self) -> None:
        self._connected = False
        self._client = None

    async def place_order(self, order: BrokerOrder) -> str:
        if not self._connected:
            await self.connect()
        if not self._client:
            return "alpaca:disconnected"
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest  # type: ignore
        from alpaca.trading.enums import OrderSide as ASide, TimeInForce as ATIF  # type: ignore
        side = ASide.BUY if order.side == OrderSide.BUY else ASide.SELL
        tif = ATIF.GTC
        req = (LimitOrderRequest if order.order_type == OrderType.LIMIT else MarketOrderRequest)(
            symbol=order.instrument.symbol, qty=order.quantity, side=side, time_in_force=tif,
            **({"limit_price": order.price} if order.order_type == OrderType.LIMIT else {})
        )
        result = self._client.submit_order(req)
        return str(result.id)

    async def cancel_order(self, order_id: str) -> bool:
        if not self._client:
            return False
        try:
            self._client.cancel_order_by_id(order_id)
            return True
        except Exception:
            return False

    async def get_open_orders(self) -> list[dict[str, Any]]:
        if not self._client:
            return []
        try:
            return [o.model_dump() for o in self._client.get_orders()]
        except Exception:
            return []

    async def get_positions(self) -> list[BrokerPosition]:
        if not self._client:
            return []
        try:
            from src.core.instrument import Instrument, AssetClass
            return [
                BrokerPosition(
                    instrument=Instrument(symbol=p.symbol, asset_class=AssetClass.EQUITY,
                                           exchange=p.exchange or None,
                                           currency="USD"),
                    quantity=float(p.qty), avg_price=float(p.avg_entry_price),
                    unrealized_pnl=float(p.unrealized_pl or 0),
                ) for p in self._client.get_all_positions()
            ]
        except Exception:
            return []

    async def get_balance(self) -> list[BrokerBalance]:
        if not self._client:
            return []
        try:
            acc = self._client.get_account()
            return [BrokerBalance(currency="USD", total=float(acc.equity),
                                   available=float(acc.cash))]
        except Exception:
            return []
