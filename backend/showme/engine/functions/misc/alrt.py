"""ALRT — Alarm engine."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from showme.app_paths import runtime_path
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument

LOG = logging.getLogger("showme.alrt")

# Serializes the load→mutate→save cycle across concurrent FastAPI requests
# so two simultaneous `add`s on the same `/api/fn/ALRT` cannot drop one alert.
_STORE_LOCK = threading.Lock()


def _store():
    return runtime_path("alerts.json")


@dataclass
class Alert:
    id: str
    condition: str            # DSL: "AAPL.price > 200" / "BTC.RSI(1h) < 30"
    actions: list[str] = field(default_factory=list)  # "notify", "execute", "run:DES"
    recipients: list[str] = field(default_factory=list)
    cooldown_seconds: int = 300
    last_fired: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    enabled: bool = True


def _load_alerts() -> tuple[list[Alert], str | None]:
    """Return (alerts, warning).

    A corrupted `alerts.json` previously returned `[]` silently — the user
    would just see "no alerts" with no signal that their rules were
    unreadable. We now surface a warning so the UI can tell the user to
    inspect or restore the store.
    """
    store = _store()
    if not store.exists():
        return [], None
    try:
        raw = json.loads(store.read_text())
        return [Alert(**a) for a in raw], None
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        LOG.warning("ALRT store unreadable at %s: %s", store, exc)
        return [], f"alerts.json unreadable ({type(exc).__name__}); review {store}"


def _save_alerts(alerts: list[Alert]) -> None:
    """Atomic write — tmp file + `os.replace` so a crashed FastAPI worker
    can never leave alerts.json half-written and unreadable on next boot.
    """
    store = _store()
    store.parent.mkdir(parents=True, exist_ok=True)
    tmp = store.with_suffix(store.suffix + ".tmp")
    payload = json.dumps([asdict(a) for a in alerts], indent=2)
    tmp.write_text(payload)
    os.replace(tmp, store)


@FunctionRegistry.register
class ALRTFunction(BaseFunction):
    code = "ALRT"
    name = "Alerts"
    category = "misc"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = params.get("action", "list")
        with _STORE_LOCK:
            alerts, load_warning = _load_alerts()
            warnings = [load_warning] if load_warning else []
            if action == "list":
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        "alerts": [asdict(a) for a in alerts],
                        "count": len(alerts),
                        "actions": ["list", "add", "remove", "toggle"],
                        "evaluator_status": "not_running",
                        "evaluator_note": (
                            "Alerts are persisted but a background evaluator "
                            "that fires them is not wired in this build."
                        ),
                        "condition_examples": [
                            "AAPL.price > 200",
                            "BTCUSDT.price < 80000",
                            "NEWS(BTCUSDT).importance >= 70",
                            "NEWS(AAPL).importance >= 70",
                        ],
                    },
                    warnings=warnings,
                )
            if action == "add":
                condition = params.get("condition")
                if not condition or not str(condition).strip():
                    return _alrt_input_required(
                        self.code,
                        "ALRT add requires a non-empty condition DSL string.",
                        "Pass condition=AAPL.price>200 (or similar) in Params JSON.",
                        warnings,
                    )
                try:
                    cooldown = int(params.get("cooldown", 300))
                except (TypeError, ValueError):
                    cooldown = 300
                a = Alert(
                    id=str(uuid.uuid4())[:8],
                    condition=str(condition),
                    actions=params.get("actions") or ["notify"],
                    recipients=params.get("recipients") or [],
                    cooldown_seconds=cooldown,
                )
                alerts.append(a)
                _save_alerts(alerts)
                return FunctionResult(
                    code=self.code, instrument=None, data=asdict(a), warnings=warnings
                )
            if action == "remove":
                alert_id = params.get("id")
                if not alert_id:
                    return _alrt_input_required(
                        self.code,
                        "ALRT remove requires an id.",
                        "Pass id=<alert-id> from a prior list/add call.",
                        warnings,
                    )
                alerts = [a for a in alerts if a.id != alert_id]
                _save_alerts(alerts)
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={"removed": alert_id},
                    warnings=warnings,
                )
            if action == "toggle":
                alert_id = params.get("id")
                if not alert_id:
                    return _alrt_input_required(
                        self.code,
                        "ALRT toggle requires an id.",
                        "Pass id=<alert-id> from a prior list/add call.",
                        warnings,
                    )
                for a in alerts:
                    if a.id == alert_id:
                        a.enabled = not a.enabled
                _save_alerts(alerts)
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data=[asdict(a) for a in alerts],
                    warnings=warnings,
                )
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_error",
                    "reason": f"unknown ALRT action {action!r}",
                    "rows": [],
                    "next_actions": ["Use one of: list, add, remove, toggle."],
                },
                warnings=warnings + [f"unknown action {action}"],
            )


def _alrt_input_required(
    code: str,
    reason: str,
    action: str,
    warnings: list[str] | None = None,
) -> FunctionResult:
    return FunctionResult(
        code=code,
        instrument=None,
        data={
            "status": "input_required",
            "reason": reason,
            "rows": [],
            "next_actions": [action],
        },
        sources=[],
        warnings=warnings or [],
    )
