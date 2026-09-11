"""L5 flagship regression: failure semantics veto LIVE.

The 2026-09-11 backend survey (survey-4 §5.6) reproduced a residual
honesty loophole: a provider-exhausted envelope that lists its REAL
provider chain in ``sources`` earned ``data_state="live"`` while its own
status said ``provider_unavailable`` (DES sets
``sources_used = list(provider_order)`` at its exhausted path). The UI
pill therefore read **LIVE · EXCHANGE** over an error payload.

Contract after the fix (``enforce_live_or_label_synthetic``):

* a declared failure ``status`` on ``payload["data"]`` (or top-level),
* a truthy ``metadata.fallback`` / ``metadata.degraded``,
* or a ``metadata.exception_type`` envelope

can never earn LIVE, no matter how live the source NAMES look. The
payload is pinned to the honest ``provider_unavailable`` state and the
exhausted-fallback semantics (``fallback``/``degraded``/``data_mode``)
are stamped so downstream status derivation and the UI pill agree.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme import server


def _des_failure_payload() -> dict[str, Any]:
    """The exact DES provider-exhausted shape from survey-4 §5.6.

    DES stamps ``sources_used = list(provider_order)`` and a
    ``status="provider_unavailable"`` data payload with NO fallback flag —
    the shape that used to earn ``data_state="live"``.
    """
    return {
        "code": "DES",
        "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
        "data": {
            "symbol": "AAPL",
            "name": "AAPL",
            "asset_class": "EQUITY",
            "status": "provider_unavailable",
            "reason": "Reference data providers returned no usable company description.",
            "rows": [],
        },
        "metadata": {
            "asset_class": "EQUITY",
            "provider_errors": [
                "yfinance: connection refused",
                "finnhub: 503",
                "sec_edgar: timeout",
            ],
        },
        "sources": ["yfinance", "finnhub", "sec_edgar"],
        "warnings": [],
    }


def _run(payload: dict[str, Any], code: str = "DES") -> dict[str, Any]:
    result = server.enforce_live_or_label_synthetic(code, {"symbol": "AAPL"}, payload)
    assert isinstance(result, dict)
    return result


# ─── The survey repro: DES failure cannot earn LIVE ────────────────────────


def test_des_provider_exhausted_envelope_cannot_earn_live() -> None:
    payload = _run(_des_failure_payload())

    # Pre-fix this was data_state="live" (sanitizer_summary {'live': 3}).
    assert payload["status"] == "provider_unavailable"
    assert payload["data_state"] == "provider_unavailable"
    assert payload["data_state"] != "live"
    # The provider NAMES stay visible for diagnostics — they simply cannot
    # prove liveness any more.
    assert payload["sanitizer_summary"]["live"] == 3
    assert payload["metadata"]["fallback"] is True
    assert payload["metadata"]["degraded"] is True
    assert payload["metadata"]["data_state"] == "provider_unavailable"
    # The UI reads metadata.data_mode first: PROVIDER DOWN, never LIVE.
    assert payload["metadata"]["data_mode"] == "provider_unavailable"
    assert payload["metadata"]["original_sources"] == ["yfinance", "finnhub", "sec_edgar"]
    assert any(
        "failure semantics" in str(entry).lower()
        for entry in payload["metadata"].get("provider_errors", [])
    )


def test_des_provider_exhausted_engine_stamps_fallback_end_to_end() -> None:
    """The DES handler itself must stamp metadata.fallback on exhaustion."""

    class _BoomAdapter:
        async def fetch(self, *_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("provider down")

    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.functions.equity.des import DESFunction

    deps = FunctionDeps(
        yfinance=_BoomAdapter(),
        finnhub=_BoomAdapter(),
        sec_edgar=_BoomAdapter(),
    )
    result = asyncio.run(
        DESFunction(deps).execute(instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY))
    )
    assert result.data["status"] == "provider_unavailable"
    assert result.metadata.get("fallback") is True
    assert result.metadata.get("degraded") is True

    payload = _run(result.to_dict())
    assert payload["data_state"] == "provider_unavailable"
    assert payload["data_state"] != "live"
    # The real provider chain is still surfaced (not wiped).
    assert payload["sanitizer_summary"]["live"] == 3


# ─── Other failure declaration forms ──────────────────────────────────────


def test_metadata_fallback_with_live_names_cannot_earn_live() -> None:
    payload = _run(
        {
            "code": "GP",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"status": "ok", "rows": [{"px": 100.0}]},
            "metadata": {"fallback": True},
            "sources": ["yfinance"],
            "warnings": [],
        },
        code="GP",
    )
    assert payload["data_state"] == "provider_unavailable"
    assert payload["status"] == "provider_unavailable"
    assert payload["metadata"]["data_mode"] == "provider_unavailable"


def test_metadata_degraded_with_live_names_cannot_earn_live() -> None:
    payload = _run(
        {
            "code": "GP",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"status": "ok", "rows": [{"px": 100.0}]},
            "metadata": {"degraded": True},
            "sources": ["binance"],
            "warnings": [],
        },
        code="GP",
    )
    assert payload["data_state"] == "provider_unavailable"
    assert payload["status"] == "provider_unavailable"


@pytest.mark.parametrize(
    "status",
    ["provider_unavailable", "not_configured", "calc_error", "error"],
)
def test_failure_statuses_veto_live_even_with_live_sources(status: str) -> None:
    payload = _run(
        {
            "code": "GP",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"status": status, "rows": [{"px": 100.0}]},
            "metadata": {},
            "sources": ["yfinance", "polygon"],
            "warnings": [],
        },
        code="GP",
    )
    assert payload["data_state"] != "live"
    assert payload["data_state"] == "provider_unavailable"


def test_empty_status_is_not_a_failure_and_can_stay_live() -> None:
    """An empty result set from a live feed is not a provider failure."""
    payload = _run(
        {
            "code": "GP",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"status": "empty", "rows": []},
            "metadata": {},
            "sources": ["yfinance"],
            "warnings": [],
        },
        code="GP",
    )
    assert payload["data_state"] == "live"


# ─── Non-regressions ──────────────────────────────────────────────────────


def test_success_envelope_with_live_sources_stays_live() -> None:
    payload = _run(
        {
            "code": "DES",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"status": "ok", "name": "Apple Inc.", "rows": [{"field": "name"}]},
            "metadata": {"asset_class": "EQUITY"},
            "sources": ["yfinance", "finnhub"],
            "warnings": [],
        }
    )
    assert payload["data_state"] == "live"
    assert payload["status"] == "ok"
    assert payload["metadata"].get("fallback") is not True
    assert payload["metadata"].get("degraded") is not True


def test_hvt_failure_template_is_still_synthetic_not_provider_state() -> None:
    """Existing H-1 contract: empty sources + fallback template ⇒ synthetic."""
    payload = _run(
        {
            "code": "HVT",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"status": "provider_unavailable", "rows": [{"window": 30}]},
            "metadata": {"fallback": True},
            "sources": [],
            "warnings": [],
        },
        code="HVT",
    )
    assert payload["data_state"] == "synthetic"


def test_model_rows_keep_model_state_even_with_failure_status() -> None:
    """A mixed reference/model ladder is already non-live — unchanged."""
    payload = _run(
        {
            "code": "TAUC",
            "instrument": None,
            "data": {"status": "provider_unavailable", "rows": [{"auction_date": "2026-09-20"}]},
            "metadata": {"provider_errors": ["treasurydirect timeout"]},
            "sources": ["yfinance", "treasury_auction_model"],
            "warnings": [],
        },
        code="TAUC",
    )
    # ``treasury_auction_model`` contains the ``auction_model`` synthetic
    # marker → synthetic dominates; either way it is not LIVE.
    assert payload["data_state"] != "live"


# ─── Primitive ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "metadata,payload_extra,expected",
    [
        ({}, {"data": {"status": "provider_unavailable"}}, True),
        ({}, {"data": {"status": "ok"}}, False),
        ({"fallback": True}, {"data": {"status": "ok"}}, True),
        ({"degraded": "yes"}, {"data": {"status": "ok"}}, True),
        ({"exception_type": "RuntimeError"}, {"data": {"status": "ok"}}, True),
        ({"fallback": False, "degraded": False}, {"data": {"status": "ok"}}, False),
        ({}, {"data": {"status": "empty"}}, False),
    ],
)
def test_payload_declares_failure_primitive(
    metadata: dict[str, Any], payload_extra: dict[str, Any], expected: bool
) -> None:
    payload = {"data": payload_extra["data"]}
    assert server._payload_declares_failure(metadata, payload) is expected


def test_top_level_status_also_vetoes() -> None:
    result = _run(
        {
            "code": "GP",
            "status": "provider_unavailable",
            "data": {"status": "ok", "rows": [{"px": 1.0}]},
            "metadata": {},
            "sources": ["yfinance"],
            "warnings": [],
        },
        code="GP",
    )
    assert result["data_state"] == "provider_unavailable"


def test_failure_veto_is_idempotent() -> None:
    """A second sanitizer pass must not resurrect the LIVE label."""
    first = _run(_des_failure_payload())
    second = server.enforce_live_or_label_synthetic(
        "DES", {"symbol": "AAPL"}, first
    )
    assert second["data_state"] == "provider_unavailable"
    assert second["metadata"]["data_mode"] == "provider_unavailable"
