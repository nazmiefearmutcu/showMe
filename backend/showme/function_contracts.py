"""Function result contract normalization for `/api/fn/{code}`.

The engine still owns each function's domain payload. This module adds the
shared ShowMe envelope required by the native UI and audit harness without
discarding the legacy ``data`` field that existing panes consume.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


LOG = logging.getLogger("showme.function_contracts")

FnStatus = str
OK: FnStatus = "ok"
EMPTY: FnStatus = "empty"
INPUT_ERROR: FnStatus = "input_error"
INPUT_REQUIRED: FnStatus = "input_required"
PROVIDER_UNAVAILABLE: FnStatus = "provider_unavailable"
CALC_ERROR: FnStatus = "calc_error"

# Bumped on every breaking-shape change to the envelope.
CONTRACT_VERSION = 1


class FunctionEnvelope(BaseModel):
    """Pydantic model describing the envelope shipped to the UI/audit.

    ``extra="allow"`` so we don't break in-flight callers that ship
    additional keys (e.g. legacy ``data``, ``metadata``, ``warnings``,
    ``rowCount``). Validation is best-effort: ``validate_envelope`` returns
    a coerced model and re-raises with an explicit message on failure.
    """

    model_config = ConfigDict(extra="allow")

    code: str
    status: Literal[
        "ok",
        "empty",
        "input_error",
        "input_required",
        "provider_unavailable",
        "calc_error",
    ]
    as_of: str | None = Field(default=None, alias="asOf")
    input_echo: dict | None = Field(default=None, alias="inputEcho")
    payload: dict = Field(default_factory=dict)
    rows: list[dict] | None = None
    series: list[dict] | None = None
    cards: list[dict] | None = None
    source_details: list[dict] | None = Field(default=None, alias="sourceDetails")
    warnings: list[str] = Field(default_factory=list)
    contract_version: int = Field(default=CONTRACT_VERSION, alias="contractVersion")


def validate_envelope(payload: dict) -> FunctionEnvelope:
    """Best-effort coerce a function payload into ``FunctionEnvelope``.

    Re-raises ``ValueError`` with the concrete pydantic error chain so
    callers can log a clear contract-drift signal.
    """
    try:
        return FunctionEnvelope.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(
            f"function envelope validation failed for code={payload.get('code')!r}: {exc}"
        ) from exc

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
    # asOf is the observation date of the data, never the compute time: a
    # monthly CPI print must not read as current because it was served today.
    # The retrieval time is kept separately as retrievedAt.
    payload["retrievedAt"] = payload.get("fetched_at") or _utcnow()
    payload["asOf"] = _observation_as_of(metadata, data, rows, _parse_observation(payload["retrievedAt"]))
    payload["inputEcho"] = _clean_input(params)
    # The router injects a default symbol when the caller chose none and flags
    # it __explicit_symbol=False. That default must never be silent: say so in
    # the envelope (defaultedInputs) and in the visible warnings (XCON-5).
    if params.get("__explicit_symbol") is False and params.get("symbol"):
        default_symbol = str(params["symbol"])
        payload["defaultedInputs"] = {"symbol": default_symbol}
        note = (f"No symbol was given, so this ran on the default symbol {default_symbol}; "
                "pass symbol to choose the instrument.")
        current = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
        if note not in current:
            payload["warnings"] = [*current, note]
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
    payload.setdefault("contractVersion", CONTRACT_VERSION)
    if os.environ.get("SHOWME_VALIDATE_CONTRACT"):
        try:
            validate_envelope(payload)
        except ValueError as exc:
            LOG.warning("contract drift: %s", exc)
    return payload


def _status_family(data_status: str) -> str:
    """Map a function's own ``data.status`` onto the envelope family.

    Functions use many specific statuses (``no_price_history``,
    ``archive_unavailable``, ``unsupported_location`` ...). An unknown one used
    to fall through to ``ok``, so an empty or failed payload was published as
    ok/live (offline audit T10, 2026-11-08). Negative shapes are classified by
    prefix/suffix; anything else keeps the old behaviour.
    """
    s = data_status
    if s in {PROVIDER_UNAVAILABLE, "not_configured", "unavailable"} or s.endswith("_unavailable"):
        return PROVIDER_UNAVAILABLE
    if s in {"unsupported_asset", INPUT_ERROR, INPUT_REQUIRED, "needs_input"} or s.startswith(
        ("unsupported_", "not_applicable")
    ):
        return INPUT_ERROR
    if s == CALC_ERROR or (s.endswith("_error") and s != INPUT_ERROR):
        return CALC_ERROR
    if s in {EMPTY, "empty_portfolio", "ready_no_positions", "insufficient_history"} or s.startswith("no_"):
        return EMPTY
    return ""


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
    family = _status_family(data_status)

    if metadata.get("fallback") or family == PROVIDER_UNAVAILABLE:
        return (
            PROVIDER_UNAVAILABLE,
            reason or _first(metadata.get("provider_errors")) or "provider unavailable",
            _first(actions) or "Connect the required provider and rerun the function.",
        )
    if family == INPUT_ERROR:
        return (
            INPUT_ERROR,
            reason or "input is not compatible with this function",
            _first(actions) or "Change the function input to a supported symbol or asset class.",
        )
    if family == CALC_ERROR:
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

    if family == EMPTY:
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
        if isinstance(value, dict) and value and not _is_blank_value(value):
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
    # A card made only of echoed input / method / provenance fields is not data.
    if not any(key not in _NON_DATA_KEYS for key in scalar_items):
        return []
    return [scalar_items]


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
        return _is_blank_value(data)
    return False


# Keys that echo the request, describe the method or carry provenance: they
# are present even when the provider returned nothing, so they never make a
# payload "useful" on their own (a DES answer with only symbol/asset_class
# filled, or a TECH answer whose only content is {"symbol", "days"}).
_NON_DATA_KEYS = frozenset({
    "status", "reason", "nextAction", "next_actions", "requested", "symbol", "ticker", "asset_class",
    "code", "query", "interval", "days", "range", "period", "params", "input", "inputs", "methodology",
    "field_dictionary", "disclaimer", "as_of", "asOf", "fetched_at", "generated_at", "source", "sources",
    "provider",
})


def _is_blank_value(value: Any) -> bool:
    if value is None or value == "":
        return True
    if isinstance(value, list):
        return len(value) == 0
    if isinstance(value, dict):
        useful = [child for key, child in value.items() if key not in _NON_DATA_KEYS]
        return all(_is_blank_value(child) for child in useful)
    return False


def _clean_input(params: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in params.items()
        if key not in IGNORED_INPUT_KEYS and not key.startswith("__")
    }


_OBSERVATION_KEYS = ("as_of", "asOf", "observation_date", "last_observation", "last_updated", "lastUpdated")
_ROW_OBSERVATION_KEYS = ("as_of", "asOf", "observation_date", "date", "timestamp", "time")


def _parse_observation(value: Any) -> datetime | None:
    """A UTC datetime for an observation stamp (ISO text, datetime or epoch seconds)."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, bool):
        return None
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    elif isinstance(value, (int, float)) and value > 0:
        try:
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A row stamp this close to the retrieval moment is the compute/serve time, not
# an observation (producers stamp now() per row), so it is not used as asOf.
_RETRIEVAL_MARGIN = timedelta(seconds=60)


def _declared_observation_date(value: Any) -> datetime | None:
    """A top-level or metadata as-of value, only when it is a plain observation date.

    Producers routinely write ``datetime.now()`` into ``as_of``/``last_updated``
    keys, so a full timestamp there cannot be told apart from the compute time.
    Only a date-granular value (YYYY-MM-DD) is accepted as a declared observation.
    """
    if not isinstance(value, str) or not _DATE_ONLY.match(value.strip()):
        return None
    return _parse_observation(value.strip())


def _observation_as_of(
    metadata: dict[str, Any],
    data: Any,
    rows: list[dict] | None,
    retrieved: datetime | None = None,
) -> str | None:
    """Latest observation date the payload declares, or None when it declares none.

    Declared top-level and metadata keys count only when they are date-granular.
    Row date-like fields count only when they are not in the future and not the
    retrieval moment itself (future values are event dates; retrieval-moment values
    are compute stamps). Falls back to None rather than the compute time.
    """
    if retrieved is None:
        retrieved = datetime.now(timezone.utc)
    latest_row_ok = retrieved - _RETRIEVAL_MARGIN
    found: list[datetime] = []
    for holder in (metadata, data if isinstance(data, dict) else None):
        if not isinstance(holder, dict):
            continue
        for key in _OBSERVATION_KEYS:
            parsed = _declared_observation_date(holder.get(key))
            if parsed is not None:
                found.append(parsed)
                break
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for key in _ROW_OBSERVATION_KEYS:
            parsed = _parse_observation(row.get(key))
            if parsed is not None and parsed <= latest_row_ok:
                found.append(parsed)
                break
    if not found:
        return None
    return max(found).isoformat()


def _source_details(sources: list[Any], as_of: str | None, status: FnStatus) -> list[dict[str, Any]]:
    if not sources:
        return [{"name": "none", "asOf": as_of, "status": "missing"}]
    source_status = "ok" if status == OK else status
    return [
        {"name": str(source), "asOf": as_of, "status": source_status}
        for source in sources
    ]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
