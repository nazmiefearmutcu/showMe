"""ALRT — Alarm engine."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from showme.app_paths import runtime_path
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument

LOG = logging.getLogger("showme.alrt")

# Serializes the load→mutate→save cycle across concurrent FastAPI requests
# so two simultaneous `add`s on the same `/api/fn/ALRT` cannot drop one alert.
_STORE_LOCK = threading.Lock()

_MUTATING_ACTIONS = frozenset({"add", "remove", "toggle"})

_NOT_ARMED_WARNING = (
    "Alert stored but not armed: no background evaluator is wired in this build, "
    "so this rule will not fire."
)


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
    note: str | None = None   # operator rationale (alrt_seed.py "note" input)


# Condition grammar the evaluator in services/alert_engine.py understands:
#   <SYMBOL>.<field> <op> <number>      e.g. AAPL.price > 200
#   NEWS(<SYMBOL>).importance <op> <n>  e.g. NEWS(AAPL).importance >= 70
_QUOTE_RE = re.compile(
    r"^\s*([A-Za-z0-9._\^]+)\.([A-Za-z_]+)\s*(>=|<=|==|!=|>|<|=)\s*(-?\d+(?:\.\d+)?)\s*$"
)
_NEWS_RE = re.compile(
    r"^\s*NEWS\(([^)]+)\)\.importance\s*(>=|<=|==|!=|>|<|=)\s*(\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)
# Quote fields AlertEngine._compare_quote_field can evaluate.
_QUOTE_FIELDS = frozenset({"price", "bid", "ask", "volume", "change_pct", "chg"})
# Structured inputs declared by alrt_seed.py (field / direction).
_SEED_FIELDS = frozenset({"price", "change_pct", "volume"})
_SEED_DIRECTION_OPS = {"above": ">", "below": "<"}
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._\^]+$")


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
            if load_warning and action in _MUTATING_ACTIONS:
                # ALRT#4: _load_alerts returns [] for an unreadable file, so
                # saving now would replace the user's bytes with a near-empty list.
                return _alrt_input_error(
                    self.code,
                    "alerts.json is unreadable, so this change was refused to avoid overwriting it.",
                    f"Inspect or restore {_store()}, then retry.",
                    warnings,
                )
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
                condition, rejection = _resolve_add_condition(self.code, params, warnings)
                if rejection is not None:
                    return rejection
                cooldown, cooldown_warning = _parse_cooldown(params.get("cooldown"))
                if cooldown_warning:
                    warnings = warnings + [cooldown_warning]
                a = Alert(
                    id=str(uuid.uuid4())[:8],
                    condition=condition,
                    actions=params.get("actions") or ["notify"],
                    recipients=params.get("recipients") or [],
                    cooldown_seconds=cooldown,
                    note=_clean_note(params.get("note")),
                )
                alerts.append(a)
                _save_alerts(alerts)
                # ALRT#1: nothing evaluates stored rules in this build, so a
                # successful add must not read as an armed alert.
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        **asdict(a),
                        "status": "stored_not_armed",
                        "armed": False,
                        "evaluator_status": "not_running",
                    },
                    warnings=warnings + [_NOT_ARMED_WARNING],
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


_DEFAULT_COOLDOWN_S = 300


def _parse_cooldown(raw: Any) -> tuple[int, str | None]:
    """Return (cooldown_seconds, warning). A bad value is replaced, and the
    warning names the replaced value so the caller can see it (ALRT#7)."""
    if raw is None:
        return _DEFAULT_COOLDOWN_S, None
    value = _whole_seconds(raw)
    if value is None:
        return _DEFAULT_COOLDOWN_S, (
            f"cooldown {raw!r} is not a whole number of seconds; using {_DEFAULT_COOLDOWN_S} s."
        )
    if value < 0:
        return _DEFAULT_COOLDOWN_S, (
            f"cooldown {raw!r} is negative; using {_DEFAULT_COOLDOWN_S} s."
        )
    return value, None


def _whole_seconds(raw: Any) -> int | None:
    """Return raw as whole seconds, or None when it is not exactly an integer.

    ALRT#7 follow-up: int() silently truncated 60.7 to 60 and turned True into 1,
    so booleans and non-integral numbers are rejected instead of coerced.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if math.isfinite(raw) and raw.is_integer() else None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def _clean_note(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _condition_is_parseable(condition: str) -> bool:
    if _NEWS_RE.match(condition):
        return True
    m = _QUOTE_RE.match(condition)
    return bool(m) and m.group(2).lower() in _QUOTE_FIELDS


def _format_threshold(value: float) -> str:
    # Plain decimal notation so the result always matches _QUOTE_RE.
    return format(Decimal(repr(value)).normalize(), "f")


def _resolve_add_condition(
    code: str, params: dict[str, Any], warnings: list[str]
) -> tuple[str | None, FunctionResult | None]:
    """Return (condition, None) to store, or (None, result) to refuse.

    Either a condition DSL string is passed, or the seed's structured inputs
    (symbol / field / direction / threshold) are turned into one. Nothing is
    stored unless the resulting condition is in the grammar the evaluator
    understands (ALRT#3), and cross_up / cross_down are refused because no
    stateful evaluator exists to honour them (ALRT#2).
    """
    raw_condition = params.get("condition")
    if raw_condition is not None and str(raw_condition).strip():
        condition = str(raw_condition).strip()
        if not _condition_is_parseable(condition):
            return None, _alrt_input_error(
                code,
                f"ALRT condition {condition!r} does not parse, so no evaluator could run it.",
                "Use <SYMBOL>.<price|bid|ask|volume|change_pct> <op> <number>, "
                "e.g. AAPL.price > 200, or NEWS(AAPL).importance >= 70.",
                warnings,
            )
        return condition, None

    symbol = str(params.get("symbol") or "").strip()
    threshold_raw = params.get("threshold")
    if not symbol or threshold_raw is None or str(threshold_raw).strip() == "":
        return None, _alrt_input_required(
            code,
            "ALRT add requires a condition, or a symbol and threshold.",
            "Pass condition=AAPL.price>200, or symbol=AAPL field=price "
            "direction=above threshold=200.",
            warnings,
        )
    field_name = str(params.get("field") or "price").strip().lower()
    direction = str(params.get("direction") or "above").strip().lower()
    if not _SYMBOL_RE.match(symbol):
        return None, _alrt_input_error(
            code, f"ALRT symbol {symbol!r} is not a valid symbol.",
            "Use a plain ticker such as AAPL or BTCUSDT.", warnings,
        )
    if field_name not in _SEED_FIELDS:
        return None, _alrt_input_error(
            code, f"ALRT field {field_name!r} is not supported.",
            "Use one of: price, change_pct, volume.", warnings,
        )
    op = _SEED_DIRECTION_OPS.get(direction)
    if op is None:
        reason = (
            f"ALRT direction {direction!r} needs a stateful crossing evaluator, "
            "which is not wired in this build."
            if direction.startswith("cross")
            else f"ALRT direction {direction!r} is not supported."
        )
        return None, _alrt_input_error(
            code, reason, "Use direction=above or direction=below.", warnings,
        )
    try:
        threshold = float(threshold_raw)
    except (TypeError, ValueError):
        threshold = math.nan
    if not math.isfinite(threshold):
        return None, _alrt_input_error(
            code, f"ALRT threshold {threshold_raw!r} is not a finite number.",
            "Pass a finite number such as threshold=200.", warnings,
        )
    return f"{symbol}.{field_name} {op} {_format_threshold(threshold)}", None


def _alrt_input_error(
    code: str,
    reason: str,
    action: str,
    warnings: list[str] | None = None,
) -> FunctionResult:
    return FunctionResult(
        code=code,
        instrument=None,
        data={
            "status": "input_error",
            "reason": reason,
            "rows": [],
            "next_actions": [action],
        },
        sources=[],
        warnings=warnings or [],
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
