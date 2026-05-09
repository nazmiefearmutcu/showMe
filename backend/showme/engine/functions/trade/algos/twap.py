"""TWAP — equal time slices."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TWAPAlgo:
    target_quantity: float
    duration_seconds: int
    slices: int = 10

    def schedule(self) -> list[dict]:
        per = self.target_quantity / max(1, self.slices)
        slot = self.duration_seconds // max(1, self.slices)
        return [{"offset_s": i * slot, "qty": per} for i in range(self.slices)]
