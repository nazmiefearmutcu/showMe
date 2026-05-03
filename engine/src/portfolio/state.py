"""Portfolio state — multi-asset position book + manual entries.

Combines:
  - Legacy crypto positions from runtime/state.json (read-only mirror)
  - Manual additions persisted to runtime/portfolio.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.instrument import AssetClass, Instrument


@dataclass
class PortfolioPosition:
    instrument: Instrument
    quantity: float
    avg_cost: float
    currency: str = "USD"
    opened_at: datetime = field(default_factory=datetime.utcnow)
    realized_pnl: float = 0.0
    notes: str = ""
    account: str = "main"           # Multi-account ledger key

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument.to_dict(),
            "quantity": self.quantity, "avg_cost": self.avg_cost,
            "currency": self.currency,
            "opened_at": self.opened_at.isoformat(),
            "realized_pnl": self.realized_pnl, "notes": self.notes,
            "account": self.account,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PortfolioPosition":
        return cls(
            instrument=Instrument.from_dict(d["instrument"]),
            quantity=d["quantity"], avg_cost=d["avg_cost"],
            currency=d.get("currency", "USD"),
            opened_at=datetime.fromisoformat(d.get("opened_at") or datetime.utcnow().isoformat()),
            realized_pnl=d.get("realized_pnl", 0),
            notes=d.get("notes", ""),
            account=d.get("account", "main"),
        )


class PortfolioState:
    """Cross-asset portfolio book."""

    def __init__(self, path: str | Path = "runtime/portfolio.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.positions: list[PortfolioPosition] = []
        self.cash: dict[str, float] = {}      # per-currency cash
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                self.positions = [PortfolioPosition.from_dict(p) for p in data.get("positions", [])]
                self.cash = data.get("cash", {})
            except Exception:
                self.positions = []
                self.cash = {}

    def save(self) -> None:
        data = {
            "positions": [p.to_dict() for p in self.positions],
            "cash": self.cash,
            "saved_at": datetime.utcnow().isoformat(),
        }
        self.path.write_text(json.dumps(data, indent=2, default=str))

    def add_position(self, p: PortfolioPosition) -> None:
        self.positions.append(p)
        self.save()

    def remove_position(self, symbol: str) -> bool:
        before = len(self.positions)
        self.positions = [p for p in self.positions if p.instrument.symbol != symbol]
        if len(self.positions) != before:
            self.save()
            return True
        return False

    def total_market_value(self, prices: dict[str, float]) -> float:
        return sum(p.quantity * prices.get(p.instrument.symbol, p.avg_cost) for p in self.positions)

    def by_asset_class(self) -> dict[AssetClass, list[PortfolioPosition]]:
        out: dict[AssetClass, list[PortfolioPosition]] = {}
        for p in self.positions:
            out.setdefault(p.instrument.asset_class, []).append(p)
        return out

    def import_legacy_crypto(self, state_json_path: str | Path = "runtime/state.json") -> int:
        """Mirror open positions from the legacy bot's state.json (read-only)."""
        p = Path(state_json_path)
        if not p.exists():
            return 0
        try:
            data = json.loads(p.read_text())
        except Exception:
            return 0
        legacy_positions = data.get("positions") or {}
        added = 0
        for sym, pos in (legacy_positions.items() if isinstance(legacy_positions, dict) else []):
            instrument = Instrument.crypto(symbol=sym)
            existing = next((x for x in self.positions if x.instrument.symbol == sym), None)
            if existing:
                continue
            self.positions.append(PortfolioPosition(
                instrument=instrument,
                quantity=float(pos.get("quantity", 0) or 0),
                avg_cost=float(pos.get("entry_price", 0) or 0),
                currency=pos.get("currency", "USDT"),
                notes="imported from legacy bot",
            ))
            added += 1
        if added:
            self.save()
        return added
