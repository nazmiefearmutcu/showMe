"""ALRT — Alarm engine."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


_STORE = Path("runtime/alerts.json")


@dataclass
class Alert:
    id: str
    condition: str            # DSL: "AAPL.price > 200" / "BTC.RSI(1h) < 30"
    actions: list[str] = field(default_factory=list)  # "notify", "execute", "run:DES"
    recipients: list[str] = field(default_factory=list)
    cooldown_seconds: int = 300
    last_fired: str | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    enabled: bool = True


def _load_alerts() -> list[Alert]:
    if not _STORE.exists():
        return []
    try:
        raw = json.loads(_STORE.read_text())
        return [Alert(**a) for a in raw]
    except Exception:
        return []


def _save_alerts(alerts: list[Alert]) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    _STORE.write_text(json.dumps([asdict(a) for a in alerts], indent=2))


@FunctionRegistry.register
class ALRTFunction(BaseFunction):
    code = "ALRT"
    name = "Alerts"
    category = "misc"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = params.get("action", "list")
        alerts = _load_alerts()
        if action == "list":
            return FunctionResult(code=self.code, instrument=None,
                data={"alerts": [asdict(a) for a in alerts],
                                        "count": len(alerts),
                                        "actions": ["list", "add", "remove", "toggle"],
                                        "condition_examples": [
                                            "AAPL.price > 200",
                                            "BTCUSDT.price < 80000",
                                            "NEWS(BTCUSDT).importance >= 70",
                                            "NEWS(AAPL).importance >= 70",
                                        ]})
        if action == "add":
            a = Alert(
                id=str(uuid.uuid4())[:8],
                condition=params["condition"],
                actions=params.get("actions") or ["notify"],
                recipients=params.get("recipients") or [],
                cooldown_seconds=int(params.get("cooldown", 300)),
            )
            alerts.append(a)
            _save_alerts(alerts)
            return FunctionResult(code=self.code, instrument=None, data=asdict(a))
        if action == "remove":
            alerts = [a for a in alerts if a.id != params["id"]]
            _save_alerts(alerts)
            return FunctionResult(code=self.code, instrument=None, data={"removed": params["id"]})
        if action == "toggle":
            for a in alerts:
                if a.id == params["id"]:
                    a.enabled = not a.enabled
            _save_alerts(alerts)
            return FunctionResult(code=self.code, instrument=None, data=[asdict(a) for a in alerts])
        return FunctionResult(code=self.code, instrument=None, data={},
                              warnings=[f"unknown action {action}"])
