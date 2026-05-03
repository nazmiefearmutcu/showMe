"""Live algo execution engine — schedules child orders for VWAP/TWAP/Iceberg/Sniper.

Plan §18.5: VWAP/TWAP/Iceberg/Sniper algos. Bu engine, AlgoSchedule
pattern'inden gelen slice'ları broker'a gönderir, fill'leri toplar,
delta hesaplar, TCA için kayıt tutar.

Not: bu canlı broker bağlantısı gerektirir; standalone backtest
``src/services/algo_backtest.py`` üzerinden simüle edilir.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.broker import (
    BaseBroker, BrokerOrder, OrderSide, OrderType, TimeInForce
)
from src.core.instrument import Instrument


_AUDIT_PATH = Path("runtime/algo_audit.jsonl")


@dataclass
class ParentOrder:
    instrument: Instrument
    side: OrderSide
    quantity: float
    algo: str                 # "VWAP"|"TWAP"|"ICEBERG"|"SNIPER"
    duration_seconds: int = 600
    slices: int = 12
    limit_price: float | None = None
    leverage: int | None = None
    parent_id: str = field(default_factory=lambda: f"P-{int(time.time()*1000)}")


@dataclass
class ChildFill:
    parent_id: str
    child_id: str
    timestamp: datetime
    quantity: float
    price: float
    fee: float = 0.0


class AlgoEngine:
    """Async execution loop for parent orders."""

    def __init__(self, broker: BaseBroker) -> None:
        self.broker = broker
        self._running: dict[str, asyncio.Task] = {}
        self.fills: dict[str, list[ChildFill]] = {}

    async def submit(self, parent: ParentOrder) -> str:
        await self.broker.connect()
        if parent.algo.upper() == "VWAP":
            from src.functions.trade.algos.vwap import VWAPAlgo
            schedule = VWAPAlgo(parent.quantity, parent.duration_seconds, parent.slices).schedule()
        elif parent.algo.upper() == "TWAP":
            from src.functions.trade.algos.twap import TWAPAlgo
            schedule = TWAPAlgo(parent.quantity, parent.duration_seconds, parent.slices).schedule()
        else:
            schedule = [{"offset_s": 0, "qty": parent.quantity}]
        self.fills[parent.parent_id] = []
        task = asyncio.create_task(self._run_schedule(parent, schedule))
        self._running[parent.parent_id] = task
        return parent.parent_id

    async def _run_schedule(self, parent: ParentOrder, schedule: list[dict[str, Any]]) -> None:
        start = time.monotonic()
        for slot in schedule:
            elapsed = time.monotonic() - start
            wait = slot["offset_s"] - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            qty = float(slot["qty"])
            if qty <= 0:
                continue
            order = BrokerOrder(
                instrument=parent.instrument, side=parent.side, quantity=qty,
                order_type=OrderType.LIMIT if parent.limit_price else OrderType.MARKET,
                price=parent.limit_price,
                time_in_force=TimeInForce.IOC,
                leverage=parent.leverage,
                metadata={"parent_id": parent.parent_id, "algo": parent.algo},
            )
            try:
                child_id = await self.broker.place_order(order)
                self._audit({
                    "parent_id": parent.parent_id, "child_id": child_id,
                    "ts": datetime.utcnow().isoformat(),
                    "algo": parent.algo, "qty": qty,
                    "instrument": str(parent.instrument), "side": parent.side.value,
                })
            except Exception as e:
                self._audit({
                    "parent_id": parent.parent_id,
                    "ts": datetime.utcnow().isoformat(),
                    "error": str(e),
                })

    async def cancel(self, parent_id: str) -> bool:
        task = self._running.pop(parent_id, None)
        if task and not task.done():
            task.cancel()
            return True
        return False

    @staticmethod
    def _audit(entry: dict[str, Any]) -> None:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_PATH.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
