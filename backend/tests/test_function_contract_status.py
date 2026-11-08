"""The shared envelope must not publish an empty or failed payload as ok.

Found by the offline honesty audit (T10, 2026-11-08): with the network cut,
TECH/CHGS returned data.status="no_price_history" and DES returned only the
echoed symbol/asset_class, yet the envelope said status=ok (data_state=live)
because unknown statuses and echoed input fields counted as data.
"""
from __future__ import annotations

import pytest

from showme.function_contracts import normalize_function_contract


def envelope(code: str, data, sources=("yfinance",)):
    return normalize_function_contract(code, {}, {"data": data, "sources": list(sources), "metadata": {},
                                                  "warnings": []})


def test_specific_negative_status_is_not_ok():
    data = {"status": "no_price_history", "rows": [], "ohlcv": [], "summary": {"symbol": "EURUSD", "days": 120},
            "reason": "provider returned no price history for EURUSD (120d, interval 1d)",
            "next_actions": ["Try another supported listed symbol."]}
    out = envelope("TECH", data)
    assert out["status"] == "empty"
    assert out["reason"].startswith("provider returned no price history")
    assert out["nextAction"] == "Try another supported listed symbol."


def test_identity_only_payload_is_empty():
    data = {"symbol": "EURUSD=X", "name": None, "asset_class": "FX", "exchange": None, "headquarters": "",
            "market_cap": None, "description": None, "methodology": "Company profile from the reference provider."}
    assert envelope("DES", data)["status"] == "empty"


@pytest.mark.parametrize("inner, expected", [
    ("archive_unavailable", "provider_unavailable"),
    ("dropped_live_unavailable", "provider_unavailable"),
    ("unavailable", "provider_unavailable"),
    ("unsupported_location", "input_error"),
    ("not_applicable_crypto", "input_error"),
    ("needs_input", "input_error"),
    ("insufficient_history", "empty"),
    ("no_recent_split", "empty"),
])
def test_status_families(inner, expected):
    assert envelope("XYZ", {"status": inner, "reason": "why", "rows": []})["status"] == expected


@pytest.mark.parametrize("data", [
    {"symbol": "AAPL", "price": 189.5},
    {"symbol": "AAPL", "dividend_ttm": 0.0},  # zero is a value; DDM's own fix decides when it is not
    {"rows": [{"metric": "x", "value": 1.0}]},
    {"status": "ok", "summary": {"symbol": "AAPL", "last": 1.0}},
    {"status": "ready", "headline": "Fed holds"},
])
def test_real_payloads_stay_ok(data):
    assert envelope("XYZ", data)["status"] == "ok"
