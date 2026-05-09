"""Function result contract normalization for `/api/fn/{code}`.

The engine still owns each function's domain payload. This module adds the
shared ShowMe envelope required by the native UI and audit harness without
discarding the legacy ``data`` field that existing panes consume.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


FnStatus = str
OK: FnStatus = "ok"
EMPTY: FnStatus = "empty"
INPUT_ERROR: FnStatus = "input_error"
INPUT_REQUIRED: FnStatus = "input_required"
PROVIDER_UNAVAILABLE: FnStatus = "provider_unavailable"
CALC_ERROR: FnStatus = "calc_error"

ERROR_STATUSES = {
    EMPTY,
    INPUT_ERROR,
    INPUT_REQUIRED,
    PROVIDER_UNAVAILABLE,
    CALC_ERROR,
    "unsupported_asset",
    "empty_portfolio",
    "not_configured",
    "ready_no_positions",
}

TABLE_KEYS = (
    "accounts",
    "articles",
    "bars",
    "cells",
    "constituents",
    "data",
    "events",
    "fills",
    "holdings",
    "items",
    "lots",
    "news",
    "ohlcv",
    "orders",
    "positions",
    "records",
    "results",
    "rows",
    "securities",
    "signals",
    "trades",
    "transcripts",
)

SERIES_KEYS = (
    "bars",
    "candles",
    "curve",
    "drawdown",
    "equity_curve",
    "history",
    "ohlcv",
    "points",
    "returns",
    "series",
    "surface",
)

CARD_KEYS = (
    "best",
    "health",
    "metrics",
    "profile",
    "quality",
    "ratios",
    "stats",
    "summary",
)

IGNORED_INPUT_KEYS = {
    "__explicit_symbol",
    "sec_timeout",
    "yfinance_timeout",
    "finnhub_timeout",
    "quote_timeout",
    "news_timeout",
    "fred_timeout",
    "damodaran_timeout",
    "timeout",
}


def normalize_function_contract(
    code: str,
    params: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Attach the shared function envelope to a legacy function payload."""
    upper = code.upper()
    data = payload.get("data")
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

    rows = _extract_rows(upper, data)
    series = _extract_series(data)
    cards = _extract_cards(data)
    status, reason, next_action = _derive_status(
        upper,
        data,
        rows,
        series,
        cards,
        metadata,
        payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
    )

    data = _attach_data_status(data, status, reason, next_action)
    payload["data"] = data
    payload["status"] = status
    payload["asOf"] = payload.get("fetched_at") or _utcnow()
    payload["inputEcho"] = _clean_input(params)
    payload["payload"] = _contract_payload(data)
    payload["rows"] = rows
    payload["series"] = series
    payload["cards"] = cards
    payload["rowCount"] = len(rows)
    payload["seriesCount"] = len(series)
    payload["cardCount"] = len(cards)
    payload["sourceDetails"] = _source_details(sources, payload["asOf"], status)
    if reason:
        payload["reason"] = reason
    else:
        payload.pop("reason", None)
    if next_action:
        payload["nextAction"] = next_action
    else:
        payload.pop("nextAction", None)
    return payload


def _derive_status(
    code: str,
    data: Any,
    rows: list[dict[str, Any]],
    series: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    metadata: dict[str, Any],
    warnings: list[Any],
) -> tuple[FnStatus, str | None, str | None]:
    data_status = _data_status(data)
    reason = _data_reason(data)
    actions = _data_actions(data)

    if metadata.get("fallback") or data_status in {
        PROVIDER_UNAVAILABLE,
        "not_configured",
    }:
        return (
            PROVIDER_UNAVAILABLE,
            reason or _first(metadata.get("provider_errors")) or "provider unavailable",
            _first(actions) or "Connect the required provider and rerun the function.",
        )
    if data_status in {"unsupported_asset", INPUT_ERROR, INPUT_REQUIRED}:
        return (
            INPUT_ERROR,
            reason or "input is not compatible with this function",
            _first(actions) or "Change the function input to a supported symbol or asset class.",
        )
    if data_status in {CALC_ERROR}:
        return (
            CALC_ERROR,
            reason or "calculation failed",
            _first(actions) or "Inspect the calculation inputs and provider errors.",
        )

    if code == "LOTS":
        if not rows:
            return (
                EMPTY,
                reason or "local portfolio has no tax lots",
                _first(actions) or "Add or import tax lots before running LOTS.",
            )
        return OK, None, None

    if code == "FA":
        ratios = data.get("ratios") if isinstance(data, dict) else None
        if not isinstance(ratios, dict) or not ratios:
            return (
                CALC_ERROR,
                reason or "financial analysis did not produce a ratios payload",
                _first(actions) or "Refresh fundamentals or connect a statement provider with ratio inputs.",
            )

    if data_status in {EMPTY, "empty_portfolio", "ready_no_positions"}:
        return (
            EMPTY,
            reason or "no records returned for the current input",
            _first(actions) or "Change the input or add the required local state.",
        )

    if _is_effectively_empty(data, rows, series, cards):
        return (
            EMPTY,
            reason or "function returned no payload rows, series, cards, or scalar fields",
            _first(actions) or "Change the input or connect the required provider.",
        )

    if warnings:
        # Warnings do not automatically fail a payload, but they must remain
        # visible in the source/status panel.
        return OK, None, None
    return OK, None, None


def _attach_data_status(
    data: Any,
    status: FnStatus,
    reason: str | None,
    next_action: str | None,
) -> Any:
    if not isinstance(data, dict):
        return data
    out = dict(data)
    out.setdefault("status", status)
    if status != OK:
        out.setdefault("reason", reason or status)
        if next_action:
            out.setdefault("nextAction", next_action)
            out.setdefault("next_actions", [next_action])
    return out


def _contract_payload(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            k: v
            for k, v in data.items()
            if k
            not in {
                "rows",
                "status",
                "reason",
                "nextAction",
                "next_actions",
            }
        }
    return data


def _extract_rows(code: str, data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [_objectify(row) for row in data]
    if not isinstance(data, dict):
        return []
    if code == "FA":
        rows: list[dict[str, Any]] = []
        for key in ("income_statement", "balance_sheet", "cash_flow"):
            value = data.get(key)
            if isinstance(value, list):
                rows.extend(_objectify(row) for row in value)
        return rows
    for key in TABLE_KEYS:
        value = data.get(key)
        if isinstance(value, list):
            return [_objectify(row) for row in value]
    for value in data.values():
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            return [_objectify(row) for row in value]
    return []


def _extract_series(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    for key in SERIES_KEYS:
        value = data.get(key)
        if isinstance(value, list):
            return [_objectify(row) for row in value]
    return []


def _extract_cards(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    cards: list[dict[str, Any]] = []
    for key in CARD_KEYS:
        value = data.get(key)
        if isinstance(value, dict) and value:
            cards.append({"section": key, **value})
        elif isinstance(value, list):
            cards.extend(_objectify(row) for row in value if isinstance(row, dict))
    if cards:
        return cards
    scalar_items = {
        key: value
        for key, value in data.items()
        if not isinstance(value, (dict, list)) and value not in (None, "")
    }
    return [scalar_items] if scalar_items else []


def _objectify(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {"value": value}


def _data_status(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    return str(data.get("status") or data.get("state") or "").strip().lower()


def _data_reason(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("reason", "message", "note", "error"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _data_actions(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return []
    actions: list[str] = []
    for key in ("next_actions", "nextAction", "required_setup", "actions"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            actions.append(value.strip())
        elif isinstance(value, list):
            actions.extend(str(item).strip() for item in value if str(item).strip())
    return actions


def _first(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            if str(item).strip():
                return str(item).strip()
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _is_effectively_empty(
    data: Any,
    rows: list[dict[str, Any]],
    series: list[dict[str, Any]],
    cards: list[dict[str, Any]],
) -> bool:
    if rows or series or cards:
        return False
    if data is None:
        return True
    if isinstance(data, (str, bytes)):
        return len(data) == 0
    if isinstance(data, list):
        return len(data) == 0
    if isinstance(data, dict):
        useful = {
            key: value
            for key, value in data.items()
            if key not in {"status", "reason", "nextAction", "next_actions", "requested"}
        }
        if not useful:
            return True
        return all(_is_blank_value(value) for value in useful.values())
    return False


def _is_blank_value(value: Any) -> bool:
    if value is None or value == "":
        return True
    if isinstance(value, list):
        return len(value) == 0
    if isinstance(value, dict):
        return not value or all(_is_blank_value(child) for child in value.values())
    return False


def _clean_input(params: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in params.items()
        if key not in IGNORED_INPUT_KEYS and not key.startswith("__")
    }


def _source_details(sources: list[Any], as_of: str, status: FnStatus) -> list[dict[str, Any]]:
    if not sources:
        return [{"name": "none", "asOf": as_of, "status": "missing"}]
    source_status = "ok" if status == OK else status
    return [
        {"name": str(source), "asOf": as_of, "status": source_status}
        for source in sources
    ]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
