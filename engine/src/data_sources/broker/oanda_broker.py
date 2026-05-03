"""OANDA broker adapter — FX practice & live."""

from __future__ import annotations

import os
from typing import Any

import httpx

from src.core.broker import BaseBroker, BrokerOrder, BrokerPosition, BrokerBalance


class OANDABrokerAdapter(BaseBroker):
    name = "oanda"
    supports_short = True
    supports_leverage = True
    supported_asset_classes = ("FX", "COMMODITY")

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.token = os.environ.get("OANDA_API_TOKEN", "")
        self.account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
        self.base_url = (config or {}).get("base_url", "https://api-fxpractice.oanda.com/v3")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=10,
                headers={"Authorization": f"Bearer {self.token}"},
            )
        return self._client

    async def connect(self) -> None:
        self._connected = bool(self.token and self.account_id)

    async def disconnect(self) -> None:
        self._connected = False

    async def place_order(self, order: BrokerOrder) -> str:
        if not self._connected:
            await self.connect()
        if not self._connected:
            return "oanda:disconnected"
        client = await self._client_()
        body = {
            "order": {
                "instrument": order.instrument.symbol,
                "units": str(int(order.quantity if order.side.value == "BUY" else -order.quantity)),
                "type": "MARKET" if order.order_type.value == "MARKET" else "LIMIT",
                **({"price": str(order.price)} if order.price else {}),
                "timeInForce": "FOK" if order.order_type.value == "MARKET" else "GTC",
            }
        }
        r = await client.post(f"/accounts/{self.account_id}/orders", json=body)
        if r.status_code >= 400:
            return f"oanda:error:{r.status_code}"
        return str(r.json().get("orderFillTransaction", {}).get("id", "oanda:unknown"))

    async def cancel_order(self, order_id: str) -> bool:
        client = await self._client_()
        r = await client.put(f"/accounts/{self.account_id}/orders/{order_id}/cancel")
        return r.status_code < 400

    async def get_open_orders(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        client = await self._client_()
        r = await client.get(f"/accounts/{self.account_id}/orders")
        if r.status_code >= 400:
            return []
        return r.json().get("orders", [])

    async def get_positions(self) -> list[BrokerPosition]:
        if not self._connected:
            return []
        client = await self._client_()
        r = await client.get(f"/accounts/{self.account_id}/positions")
        if r.status_code >= 400:
            return []
        from src.core.instrument import Instrument, AssetClass
        out: list[BrokerPosition] = []
        for p in r.json().get("positions", []):
            net = float(p.get("long", {}).get("units", 0)) + float(p.get("short", {}).get("units", 0))
            if abs(net) < 1e-9:
                continue
            inst = Instrument(symbol=p["instrument"], asset_class=AssetClass.FX)
            out.append(BrokerPosition(instrument=inst, quantity=net, avg_price=0.0))
        return out

    async def get_balance(self) -> list[BrokerBalance]:
        if not self._connected:
            return []
        client = await self._client_()
        r = await client.get(f"/accounts/{self.account_id}")
        if r.status_code >= 400:
            return []
        acc = r.json().get("account", {})
        return [BrokerBalance(currency=acc.get("currency", "USD"),
                               total=float(acc.get("balance", 0)),
                               available=float(acc.get("marginAvailable", 0)))]
