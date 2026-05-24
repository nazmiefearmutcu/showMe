"""Portfolio state — multi-asset position book + manual entries.

Combines:
  - Legacy crypto positions from runtime/state.json (read-only mirror)
  - Manual additions persisted to runtime/portfolio.json
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from showme.engine.core.instrument import AssetClass, Instrument


@dataclass
class PortfolioPosition:
    instrument: Instrument
    quantity: float
    avg_cost: float
    currency: str = "USD"
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
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
            opened_at=datetime.fromisoformat(d.get("opened_at") or datetime.now(timezone.utc).isoformat()),
            realized_pnl=d.get("realized_pnl", 0),
            notes=d.get("notes", ""),
            account=d.get("account", "main"),
        )


class PortfolioState:
    """Cross-asset portfolio book."""

    def __init__(self, path: str | Path = "runtime/portfolio.json") -> None:
        self.path = _runtime_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.positions: list[PortfolioPosition] = []
        self.cash: dict[str, float] = {}      # per-currency cash
        self.closed_symbols: set[str] = set()
        self.closed_positions: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                self.positions = [PortfolioPosition.from_dict(p) for p in data.get("positions", [])]
                self.cash = data.get("cash", {})
                self.closed_symbols = {str(s).upper() for s in data.get("closed_symbols", [])}
                self.closed_positions = [
                    row for row in data.get("closed_positions", []) if isinstance(row, dict)
                ]
            except Exception:
                self.positions = []
                self.cash = {}
                self.closed_symbols = set()
                self.closed_positions = []

    def save(self) -> None:
        data = {
            "positions": [p.to_dict() for p in self.positions],
            "cash": self.cash,
            "closed_symbols": sorted(self.closed_symbols),
            "closed_positions": self.closed_positions[-500:],
            "saved_at": datetime.now(timezone.utc).isoformat(),
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

    def close_position(
        self,
        symbol: str,
        *,
        exit_price: float | None = None,
        reason: str = "manual_close",
        dry_run: bool = False,
    ) -> dict[str, Any] | None:
        """Preview or close a local position and suppress legacy re-imports.

        Imported TBV3 positions are mirrored from ``runtime/state.json``. A
        close operation therefore needs a durable skip marker; otherwise the
        next ``PORT`` refresh imports the old paper position again.
        """
        clean = symbol.upper()
        position = next((p for p in self.positions if p.instrument.symbol.upper() == clean), None)
        if position is None:
            return None
        price = float(exit_price if exit_price is not None else position.avg_cost)
        realized = (price - float(position.avg_cost)) * float(position.quantity)
        closed_at = datetime.now(timezone.utc).isoformat()
        record = {
            "symbol": position.instrument.symbol,
            "asset_class": position.instrument.asset_class.value,
            "quantity": position.quantity,
            "avg_cost": position.avg_cost,
            "exit_price": price,
            "market_value": price * position.quantity,
            "realized_pnl": realized,
            "opened_at": position.opened_at.isoformat(),
            "closed_at": closed_at,
            "account": position.account,
            "reason": reason,
            "dry_run": dry_run,
        }
        if dry_run:
            return record
        self.positions = [p for p in self.positions if p.instrument.symbol.upper() != clean]
        self.closed_symbols.add(clean)
        self.closed_positions.append(record)
        self.save()
        return record

    def total_market_value(self, prices: dict[str, float]) -> float:
        return sum(p.quantity * prices.get(p.instrument.symbol, p.avg_cost) for p in self.positions)

    def by_asset_class(self) -> dict[AssetClass, list[PortfolioPosition]]:
        out: dict[AssetClass, list[PortfolioPosition]] = {}
        for p in self.positions:
            out.setdefault(p.instrument.asset_class, []).append(p)
        return out

    def import_legacy_crypto(self, state_json_path: str | Path = "runtime/state.json") -> int:
        """Mirror open positions from the legacy bot's state.json (read-only).

        Gated behind ``SHOWME_IMPORT_LEGACY_TBV3`` (default OFF). showMe is the
        multi-exchange cockpit and must remain decoupled from the quarantined
        TBV3 paper-trading bot whose runtime/state.json otherwise leaks ~51
        phantom positions into PORT/ACCT/PVAR/STRS. The memory note
        "showMe exchanges work isolates TBV3" mandates zero structural
        dependency on TBV3. Set ``SHOWME_IMPORT_LEGACY_TBV3=1`` (or
        ``true``/``yes``/``on``) to opt back into the legacy mirror when
        intentionally debugging the import path.
        """
        if not _legacy_import_enabled():
            return 0
        p = _runtime_path(state_json_path)
        if not p.exists():
            return 0
        try:
            data = json.loads(p.read_text())
        except Exception:
            return 0
        legacy_positions = data.get("positions") or {}
        added = 0
        updated = False
        for sym, pos in (legacy_positions.items() if isinstance(legacy_positions, dict) else []):
            if str(sym).upper() in self.closed_symbols:
                continue
            metadata = _legacy_position_metadata(pos)
            instrument = Instrument.crypto(
                symbol=sym,
                currency=pos.get("currency") or "USDT",
                metadata=metadata,
            )
            existing = next((x for x in self.positions if x.instrument.symbol == sym), None)
            if existing:
                if metadata:
                    merged = {**existing.instrument.metadata, **metadata}
                    if merged != existing.instrument.metadata:
                        existing.instrument = replace(existing.instrument, metadata=merged)
                        updated = True
                continue
            self.positions.append(PortfolioPosition(
                instrument=instrument,
                quantity=float(pos.get("quantity", 0) or 0),
                avg_cost=float(pos.get("entry_price", 0) or 0),
                currency=pos.get("currency", "USDT"),
                notes="imported from legacy bot",
            ))
            added += 1
        if added or updated:
            self.save()
        return added


_LEGACY_IMPORT_ENV = "SHOWME_IMPORT_LEGACY_TBV3"


def _legacy_import_enabled() -> bool:
    """Whether the TBV3 legacy state.json mirror is opted in.

    Default OFF. The env var is read on every call so tests can toggle the
    behaviour with ``monkeypatch.setenv``/``delenv`` without re-importing.
    """
    raw = os.environ.get(_LEGACY_IMPORT_ENV, "")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _default_app_home() -> Path | None:
    override = os.environ.get("SHOWME_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "showMe"
    return None


def _runtime_path(path: str | Path) -> Path:
    raw = Path(path)
    if raw.is_absolute():
        return raw
    if raw.parts and raw.parts[0] == "runtime":
        app_home = _default_app_home()
        if app_home is not None:
            return app_home / raw
    return raw


def _legacy_position_metadata(pos: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {"legacy_source": "state.json"}
    current_price = pos.get("current_price")
    if current_price not in (None, ""):
        try:
            metadata["current_price"] = float(current_price)
        except (TypeError, ValueError):
            pass
    open_time = pos.get("open_time")
    if open_time not in (None, ""):
        metadata["open_time"] = open_time
    signal = pos.get("current_signal")
    if signal:
        metadata["current_signal"] = signal
    return metadata
