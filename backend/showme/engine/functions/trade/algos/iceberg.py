"""Iceberg algo — show only display_size; replenish as filled."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IcebergAlgo:
    total_quantity: float
    display_size: float
    price: float

    def next_slice(self, filled_so_far: float) -> dict:
        remaining = max(0.0, self.total_quantity - filled_so_far)
        qty = min(self.display_size, remaining)
        return {"qty": qty, "price": self.price, "tif": "GTC"}
