"""VWAP execution algorithm — slice an order over a duration following a
typical intraday volume profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class VWAPAlgo:
    target_quantity: float
    duration_seconds: int
    slices: int = 12

    def schedule(self) -> list[dict[str, Any]]:
        # Bell-shaped volume profile (US-equity-ish): high at open/close.
        weights = [0.12, 0.10, 0.08, 0.07, 0.06, 0.06, 0.06, 0.07, 0.08, 0.10, 0.10, 0.10][: self.slices]
        s = sum(weights) or 1
        weights = [w / s for w in weights]
        per_slice = [self.target_quantity * w for w in weights]
        slot = self.duration_seconds // max(1, self.slices)
        return [{"offset_s": i * slot, "qty": q} for i, q in enumerate(per_slice)]
