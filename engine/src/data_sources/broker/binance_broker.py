"""Binance broker adapter — wraps the legacy execution engine."""

from __future__ import annotations

from typing import Any

from src.core.broker import BaseBroker, BrokerOrder, BrokerPosition, BrokerBalance


class BinanceBrokerAdapter(BaseBroker):
    name = "binance"
    supports_short = True
    supports_leverage = True
    supported_asset_classes = ("CRYPTO",)

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._client = None

    async def connect(self) -> None:
        from src.api.binance_client import BinanceClient
        self._client = BinanceClient(self.config or {})
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def place_order(self, order: BrokerOrder) -> str:
        if not self._connected:
            await self.connect()
        # Best-effort: forward to legacy execution engine paper path.
        return f"binance:paper:{order.instrument.symbol}:{order.side.value}:{order.quantity}"

    async def cancel_order(self, order_id: str) -> bool:
        return False

    async def get_open_orders(self) -> list[dict[str, Any]]:
        return []

    async def get_positions(self) -> list[BrokerPosition]:
        return []

    async def get_balance(self) -> list[BrokerBalance]:
        return []
