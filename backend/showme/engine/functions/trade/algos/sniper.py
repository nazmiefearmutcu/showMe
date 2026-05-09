"""Sniper algo — wait for favorable price, then market-fill."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SniperAlgo:
    side: str           # "BUY" | "SELL"
    target_quantity: float
    limit_price: float

    def should_fire(self, best_bid: float, best_ask: float) -> bool:
        if self.side.upper() == "BUY":
            return best_ask <= self.limit_price
        return best_bid >= self.limit_price
