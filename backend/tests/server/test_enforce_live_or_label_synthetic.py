"""Regression tests for the refactored sanitizer.

Pins the 2026-05-24 fix in ``showme.server`` that replaced
``sanitize_function_payload`` with
``enforce_live_or_label_synthetic``. The legacy implementation silently
wiped any row whose only source matched ``reference_*`` / ``*_model`` /
template markers, breaking the user-visible payload for ~25 functions
including WIRP, ECO, ECFC, GMM, CPF, OVDV, WCRS, PSC, every bond pane,
and BTMM's live pill.

The new contract keeps rows in place and stamps them with one of
``live`` / ``synthetic`` / ``reference`` / ``model`` so the UI can pill
accurately. ``warnings`` is no longer cleared. A top-level
``sanitizer_summary`` counts the four categories.

These tests stay purely local (no sidecar boot) and follow the same
shape as ``backend/tests/test_server.py``.
"""
from __future__ import annotations

import pytest

from showme import server


# ─── 1. Mixed live + reference rows: kept, tagged, summary counts ──────


def test_five_live_plus_three_reference_rows_keeps_all_eight() -> None:
    """5 live + 3 ``reference_*`` rows must result in 8 rows total with
    ``data_state == "reference"`` (worst-case wins) and
    ``sanitizer_summary == {live:5, reference:3, synthetic:0, model:0}``.
    """
    rows = [{"symbol": "AAPL", "px": 100.0 + i} for i in range(5)] + [
        {"symbol": "AAPL", "px": 110.0 + i} for i in range(3)
    ]
    sources = [
        "yfinance",
        "yfinance",
        "alpaca",
        "polygon",
        "binance",
        "reference_curve_us10y",
        "reference_curve_us30y",
        "reference_bond_basis",
    ]
    payload = server.enforce_live_or_label_synthetic(
        "WIRP",
        {"symbol": "USDT"},
        {
            "code": "WIRP",
            "instrument": {"symbol": "USDT", "asset_class": "RATE"},
            "data": {"status": "ok", "rows": rows},
            "metadata": {},
            "sources": sources,
            "warnings": [],
        },
    )

    assert payload["rowCount"] == 8, "rows must not be dropped"
    assert len(payload["rows"]) == 8
    assert payload["data_state"] == "reference"
    assert payload["sanitizer_summary"] == {
        "live": 5,
        "synthetic": 0,
        "reference": 3,
        "model": 0,
    }
    # Status must NOT be provider_unavailable — that was the bug.
    assert payload["status"] != "provider_unavailable"
    assert payload["data"]["status"] != "provider_unavailable"
    # Metadata exposes data_state for diagnostics.
    assert payload["metadata"]["data_state"] == "reference"
    # Original sources preserved for the Raw drawer.
    assert payload["metadata"]["original_sources"] == sources


# ─── 2. All model rows: kept and tagged, NOT wiped ─────────────────────


def test_thirty_model_rows_are_kept_and_labeled_not_wiped() -> None:
    """0 live + 30 ``*_model`` rows (PSC ``position_sizing_model``, WCRS
    matrix, CPF forecast rows) must be kept, tagged ``data_state ==
    "model"``, and NOT collapsed to ``provider_unavailable``.
    """
    rows = [{"slot": i, "risk_pct": 1.0 + i * 0.1} for i in range(30)]
    payload = server.enforce_live_or_label_synthetic(
        "PSC",
        {"symbol": "BTCUSDT"},
        {
            "code": "PSC",
            "instrument": {"symbol": "BTCUSDT", "asset_class": "CRYPTO"},
            "data": {"status": "ok", "rows": rows},
            "metadata": {},
            "sources": ["position_sizing_model"] * 30,
            "warnings": [],
        },
    )

    assert payload["rowCount"] == 30
    assert len(payload["rows"]) == 30
    assert payload["data_state"] == "model"
    assert payload["sanitizer_summary"] == {
        "live": 0,
        "synthetic": 0,
        "reference": 0,
        "model": 30,
    }
    assert payload["status"] != "provider_unavailable"
    assert payload["data"]["status"] != "provider_unavailable"
    # Metadata flags degraded so callers can prefer live data when both
    # are available, but the rows are still here.
    assert payload["metadata"]["data_state"] == "model"
    assert payload["metadata"]["degraded"] is True


# ─── 3. Warnings array must be preserved (BTMM live pill) ──────────────


def test_warnings_array_is_preserved_for_btmm_live_pill() -> None:
    """BTMM's ``live`` pill flips to ``warn`` when ``payload.warnings``
    is non-empty. The legacy sanitizer always cleared it after copying
    into ``provider_errors``; the new version copies AND keeps the
    array intact.
    """
    payload = server.enforce_live_or_label_synthetic(
        "BTMM",
        {"symbol": "EURUSD"},
        {
            "code": "BTMM",
            "instrument": {"symbol": "EURUSD", "asset_class": "FX"},
            "data": {
                "status": "ok",
                "rows": [{"session": "asia", "high": 1.085, "low": 1.082}],
            },
            "metadata": {},
            "sources": ["fx_provider"],
            "warnings": ["stale_5d"],
        },
    )

    # The warning must still be visible on the payload — this is the
    # whole point of the BTMM pill fix.
    assert payload["warnings"] == ["stale_5d"]
    # AND it must also be mirrored into provider_errors for the
    # diagnostics drawer (legacy behavior kept).
    assert "stale_5d" in payload["metadata"].get("provider_errors", [])


# ─── 4. Pure live sources stay live with summary ───────────────────────


def test_pure_live_sources_are_classified_live() -> None:
    payload = server.enforce_live_or_label_synthetic(
        "GP",
        {"symbol": "AAPL", "asset_class": "EQUITY"},
        {
            "code": "GP",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {
                "status": "ok",
                "rows": [{"t": 1, "c": 100.0}, {"t": 2, "c": 101.0}],
            },
            "metadata": {},
            "sources": ["yfinance", "polygon"],
            "warnings": [],
        },
    )

    assert payload["data_state"] == "live"
    assert payload["sanitizer_summary"] == {
        "live": 2,
        "synthetic": 0,
        "reference": 0,
        "model": 0,
    }
    # Live payloads do not get a degraded flag, no synthetic stamp.
    assert payload["metadata"].get("degraded") is not True
    assert payload["metadata"].get("synthetic") is not True


# ─── 5. Mixed model + live: dominant data_state == model ───────────────


def test_mixed_model_and_live_sources_dominant_is_model() -> None:
    payload = server.enforce_live_or_label_synthetic(
        "CPF",
        {"symbol": "MSFT"},
        {
            "code": "CPF",
            "instrument": {"symbol": "MSFT", "asset_class": "EQUITY"},
            "data": {"status": "ok", "rows": [{"q": i, "fcst": i * 1.1} for i in range(16)]},
            "metadata": {},
            "sources": ["analyst_consensus", "forecast_blend_model"] * 8,
            "warnings": [],
        },
    )

    # 8 live + 8 model — the cautious dominant label is "model" so the
    # UI pills "MODEL" instead of pretending all 16 rows are live.
    assert payload["sanitizer_summary"]["live"] == 8
    assert payload["sanitizer_summary"]["model"] == 8
    assert payload["data_state"] == "model"
    assert payload["rowCount"] == 16


# ─── 6. Exception path still routes to fallback ────────────────────────


def test_exception_type_routes_to_fallback_envelope() -> None:
    """Real provider failures (network/SDK exceptions) must still drop
    to the existing ``fallback_function_payload`` envelope — these are
    honest broken-pipe cases, NOT deterministic computed data.
    """
    payload = server.enforce_live_or_label_synthetic(
        "BGAS",
        {"symbol": "BTCUSDT"},
        {
            "code": "BGAS",
            "instrument": {"symbol": "BTCUSDT", "asset_class": "CRYPTO"},
            "data": {"status": "ok", "rows": [{"slot": 1}]},
            "metadata": {"exception_type": "RuntimeError"},
            "sources": ["eia"],
            "warnings": ["EIA_API_KEY not set"],
        },
    )

    # The fallback envelope path is unchanged: status becomes
    # provider_unavailable, fallback flag is set, sources collapse to
    # the sentinel.
    assert payload["status"] == "provider_unavailable"
    assert payload["metadata"]["fallback"] is True
    assert payload["sources"] == ["no_live_source"]
    # The warning is preserved in provider_errors for the drawer.
    assert any(
        "EIA_API_KEY not set" in str(p)
        for p in payload["metadata"].get("provider_errors", [])
    )


# ─── 7. Legacy alias still works (sanitize_function_payload) ───────────


def test_legacy_sanitize_function_payload_alias_still_works() -> None:
    """The legacy name must be a thin forwarder so the import sites in
    ``server_routes/function_index.py`` and ``server_routes/_agent_runtime.py``
    do not break.
    """
    payload_in = {
        "code": "WIRP",
        "instrument": {"symbol": "USD", "asset_class": "RATE"},
        "data": {"status": "ok", "rows": [{"meeting": "2026-06"}]},
        "metadata": {},
        "sources": ["reference_fomc_curve"],
        "warnings": [],
    }

    via_legacy = server.sanitize_function_payload("WIRP", {}, dict(payload_in, data={"status": "ok", "rows": [{"meeting": "2026-06"}]}, metadata={}))
    via_new = server.enforce_live_or_label_synthetic(
        "WIRP", {}, dict(payload_in, data={"status": "ok", "rows": [{"meeting": "2026-06"}]}, metadata={})
    )

    # Both must produce the same data_state + summary + rowCount.
    assert via_legacy["data_state"] == via_new["data_state"] == "reference"
    assert via_legacy["sanitizer_summary"] == via_new["sanitizer_summary"]
    assert via_legacy["rowCount"] == via_new["rowCount"] == 1


# ─── 8. Source classification primitive ────────────────────────────────


@pytest.mark.parametrize(
    "source,expected",
    [
        ("yfinance", "live"),
        ("polygon", "live"),
        ("sec_edgar", "live"),
        ("binance", "live"),
        ("reference_curve_us10y", "reference"),
        ("reference_bond_basis", "reference"),
        ("position_sizing_model", "model"),
        ("forecast_blend_model", "model"),
        ("funding_rate_model", "model"),
        ("trace_proxy_model", "model"),
        ("fundamentals_template", "synthetic"),
        ("price_sample", "synthetic"),
        ("continuity_baseline", "synthetic"),
        ("auction_model", "synthetic"),  # explicit override in markers
        ("briefing_model", "synthetic"),  # explicit override in markers
    ],
)
def test_classify_source_state(source: str, expected: str) -> None:
    assert server._classify_source_state(source) == expected


# ─── 9. sanitizer_summary stamped even on pure live ────────────────────


def test_sanitizer_summary_stamped_on_every_payload() -> None:
    """The summary must always be present so the UI never has to guess
    why it is missing.
    """
    payload = server.enforce_live_or_label_synthetic(
        "GP",
        {"symbol": "AAPL"},
        {
            "code": "GP",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"status": "ok", "rows": []},
            "metadata": {},
            "sources": [],
            "warnings": [],
        },
    )
    assert "sanitizer_summary" in payload
    assert payload["sanitizer_summary"] == {
        "live": 0,
        "synthetic": 0,
        "reference": 0,
        "model": 0,
    }
    assert payload["data_state"] == "live"


# ─── 10. Bond pane reference rows now flow through ─────────────────────


def test_all_ten_bond_panes_now_get_labeled_reference_rows() -> None:
    """All 10 bond panes use ``reference_*`` source labels. Previously
    every one of them returned ``provider_unavailable`` with empty
    rows; now they keep their computed rows tagged ``data_state ==
    "reference"``.
    """
    bond_codes = ["ALLQ", "TRACE", "TYU", "FVU", "USU", "UBU", "ZNU", "ZTU", "ZFU", "ZBU"]
    for code in bond_codes:
        rows = [{"dealer": "Composite A", "bid": 99.0, "ask": 99.5}]
        payload = server.enforce_live_or_label_synthetic(
            code,
            {"symbol": "US10Y"},
            {
                "code": code,
                "instrument": {"symbol": "US10Y", "asset_class": "BOND"},
                "data": {"status": "ok", "rows": rows},
                "metadata": {},
                "sources": ["reference_dealer_quote_curve"],
                "warnings": [],
            },
        )
        # The 10-bond-pane breakage was the headline of the bug report.
        # All 10 must now show 1 row, not 0.
        assert payload["rowCount"] == 1, f"{code}: rows wiped (regression)"
        assert payload["data_state"] == "reference", f"{code}: data_state mismatch"
        assert payload["status"] != "provider_unavailable", f"{code}: still wiped"
