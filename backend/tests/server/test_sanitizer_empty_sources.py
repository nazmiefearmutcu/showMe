"""H-1 regression tests: empty/sentinel sources must never earn LIVE.

Survey S2 (2026-09-08) verified that a payload with ``sources=[]`` got
``data_state="live"`` from ``enforce_live_or_label_synthetic`` because
the all-zero summary fell through to the live default. The HVT/IVOL
provider-failure branches (derivative/_stubs.py, template rows +
``sources=[]`` + ``metadata={"fallback": True}``) were the real-world
victims: fabricated template volatility rows wore a LIVE pill.

Contract after the fix:
* Empty source provenance cannot prove liveness. The payload downgrades
  to ``synthetic`` when fallback/degraded markers are present (the
  HVT/IVOL failure shape), otherwise to ``reference``.
* A payload keeps LIVE only when the function explicitly vouches for it
  (truthy ``metadata.live`` or a ``live_*`` data_mode/source_mode/mode).
* Sources lists made purely of the ``no_live_source`` sentinel behave
  exactly like an empty list.
"""

from __future__ import annotations

from typing import Any

import pytest

from showme import server


def _hvt_failure_payload() -> dict[str, Any]:
    """The exact shape derivative/_stubs.py HVT failure branches emit."""
    return {
        "code": "HVT",
        "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
        "data": {
            "status": "provider_unavailable",
            "reason": "yfinance: connection refused",
            "rows": [
                {"window": 30, "realized_vol": 0.24},
                {"window": 60, "realized_vol": 0.22},
            ],
        },
        "metadata": {"fallback": True},
        "sources": [],
        "warnings": [],
    }


def _run(code: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = server.enforce_live_or_label_synthetic(code, {"symbol": "AAPL"}, payload)
    assert isinstance(result, dict)
    return result


def test_hvt_failure_template_with_empty_sources_is_synthetic() -> None:
    """The survey's exact repro: HVT failure template rows carried a LIVE
    pill. They must be labeled synthetic."""
    payload = _run("HVT", _hvt_failure_payload())
    assert payload["data_state"] == "synthetic"
    assert payload["metadata"]["data_state"] == "synthetic"
    assert payload["metadata"]["synthetic"] is True
    assert payload["metadata"]["degraded"] is True
    # Rows are kept — the sanitizer labels, it does not wipe.
    assert payload["rowCount"] == 2


def test_ivol_failure_template_with_empty_sources_is_synthetic() -> None:
    payload = _run(
        "IVOL",
        {
            "code": "IVOL",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"status": "provider_unavailable", "rows": [{"tenor": "30d"}]},
            "metadata": {"fallback": True, "provider_errors": ["chain fetch failed"]},
            "sources": [],
            "warnings": [],
        },
    )
    assert payload["data_state"] == "synthetic"


def test_empty_sources_without_fallback_markers_downgrade_to_reference() -> None:
    """No provenance and no live claim: honest reference (delayed) state,
    never live."""
    payload = _run(
        "GP",
        {
            "code": "GP",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"status": "ok", "rows": [{"px": 100.0}]},
            "metadata": {},
            "sources": [],
            "warnings": [],
        },
    )
    assert payload["data_state"] == "reference"
    assert payload["metadata"].get("synthetic") is not True
    assert payload["metadata"].get("degraded") is not True


@pytest.mark.parametrize("sources", [[], ["no_live_source"], ["", "no_live_source"], [None]])
def test_empty_and_sentinel_source_lists_are_non_live(sources: list[Any]) -> None:
    payload = _run(
        "GP",
        {
            "code": "GP",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"status": "ok", "rows": [{"px": 1.0}]},
            "metadata": {},
            "sources": sources,
            "warnings": [],
        },
    )
    assert payload["data_state"] != "live"


@pytest.mark.parametrize(
    "metadata",
    [
        {"live": True},
        {"live": "true"},
        {"data_mode": "live_official"},
        {"source_mode": "live_yfinance"},
        {"mode": "live_exchange"},
        {"compatibility_mode": "live_realized_vol"},
    ],
)
def test_explicit_live_claim_keeps_live_pill(metadata: dict[str, Any]) -> None:
    """The escape hatch: functions that stamp an explicit live claim keep
    their LIVE pill even when the sources list is empty."""
    payload = _run(
        "TECH",
        {
            "code": "TECH",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"status": "ok", "rows": [{"c": 100.0}]},
            "metadata": metadata,
            "sources": [],
            "warnings": [],
        },
    )
    assert payload["data_state"] == "live"
    assert payload["metadata"].get("degraded") is not True


@pytest.mark.parametrize(
    "metadata",
    [
        {"live": False},
        {"data_mode": "delayed_reference"},
        {"mode": "reference"},
        {},
    ],
)
def test_non_live_or_absent_claims_do_not_prove_liveness(metadata: dict[str, Any]) -> None:
    payload = _run(
        "TECH",
        {
            "code": "TECH",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"status": "ok", "rows": [{"c": 100.0}]},
            "metadata": metadata,
            "sources": [],
            "warnings": [],
        },
    )
    assert payload["data_state"] != "live"


def test_fallback_envelope_sentinel_sources_stay_non_live() -> None:
    """fallback_function_payload emits sources=['no_live_source'] — if
    such a payload reaches the sanitizer it must stay non-live."""
    payload = _run(
        "BGAS",
        {
            "code": "BGAS",
            "instrument": {"symbol": "BTCUSDT", "asset_class": "CRYPTO"},
            "data": {"status": "ok", "rows": []},
            "metadata": {"fallback": True, "degraded": True},
            "sources": ["no_live_source"],
            "warnings": [],
        },
    )
    assert payload["data_state"] == "synthetic"


def test_populated_live_sources_still_live() -> None:
    """Guard the non-regression: real provenance still classifies live."""
    payload = _run(
        "TECH",
        {
            "code": "TECH",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"status": "ok", "rows": [{"c": 100.0}]},
            "metadata": {},
            "sources": ["yfinance"],
            "warnings": [],
        },
    )
    assert payload["data_state"] == "live"


# ---------------------------------------------------------------------------
# R2 C-1/H-1 regression: a self-declared fallback envelope that ALSO stamps
# ``live: True`` (ECO's all-providers-failed envelope, av/brief
# not_configured envelopes) must not ride the metadata voucher to LIVE.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "metadata",
    [
        {"live": True, "fallback": True, "data_mode": "provider_unavailable"},
        {"live": True, "data_mode": "not_configured"},
        {"live": True, "degraded": True},
        {"live": True, "data_mode": "empty"},
        {"data_mode": "live_official", "fallback": True},
    ],
)
def test_failure_envelopes_cannot_voucher_live(metadata: dict[str, Any]) -> None:
    payload = _run(
        "ECO",
        {
            "code": "ECO",
            "instrument": None,
            "data": {"status": "provider_unavailable", "rows": [], "events": []},
            "metadata": metadata,
            "sources": ["no_live_source"],
            "warnings": ["all providers failed"],
        },
    )
    assert payload["data_state"] != "live"


# ---------------------------------------------------------------------------
# R2 M-1 regression: dict-shaped sources unwrap their identifying key.
# ---------------------------------------------------------------------------


def test_dict_shaped_sentinel_source_is_non_live() -> None:
    payload = _run(
        "GP",
        {
            "code": "GP",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"status": "ok", "rows": [{"px": 1.0}]},
            "metadata": {},
            "sources": [{"name": "no_live_source"}],
            "warnings": [],
        },
    )
    assert payload["data_state"] != "live"


# ---------------------------------------------------------------------------
# R2 M-4 regression: an explicit falsy ``metadata.live`` vetoes the live
# branch even when formula-named sources classify live by name.
# ---------------------------------------------------------------------------


def test_explicit_live_false_vetoes_unmarked_source_names() -> None:
    """GEX's modeled path: sources=['black_scholes_gamma_formula'] (no
    marker → classifies live) + metadata {'live': False, 'data_mode':
    'modeled'} must NOT come out live."""
    payload = _run(
        "GEX",
        {
            "code": "GEX",
            "instrument": {"symbol": "SPX", "asset_class": "INDEX"},
            "data": {"status": "ok", "rows": [{"strike": 5000, "gamma": 0.001}]},
            "metadata": {"live": False, "data_mode": "modeled"},
            "sources": ["black_scholes_gamma_formula"],
            "warnings": [],
        },
    )
    assert payload["data_state"] != "live"


# ---------------------------------------------------------------------------
# R2 L-1 regression: dummy/mock/placeholder-style source names must never
# classify as live. Before the blocklist these all earned a LIVE pill.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "dummy_feed",
        "mock_provider",
        "stub_chain",
        "fake_quotes",
        "demo_data",
        "test_universe",
        "estimated_levels",
        "illustrative_curve",
        "hardcoded_px",
        "sample_rows",
        "placeholder_rates",
        "template_book",
        "synthetic_ladder",
    ],
)
def test_blocklisted_source_names_classify_non_live(source: str) -> None:
    assert server._classify_source_state(source) == "synthetic"


def test_blocklisted_source_payload_is_not_live() -> None:
    """End-to-end: a payload whose only source is a dummy name cannot keep
    a LIVE pill even with a live data_mode claim."""
    payload = _run(
        "GP",
        {
            "code": "GP",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"status": "ok", "rows": [{"px": 1.0}]},
            "metadata": {"data_mode": "live_yfinance"},
            "sources": ["dummy_feed"],
            "warnings": [],
        },
    )
    assert payload["data_state"] == "synthetic"


def test_blocklist_does_not_swallow_real_providers_or_model_names() -> None:
    """Non-regression: real provider names stay live, and plain ``_model``
    names without blocklist substrings keep their (non-live) model label —
    including ``local_backtest_model``, whose 'test' substring now maps it
    to synthetic instead of model (still non-live either way)."""
    assert server._classify_source_state("yfinance") == "live"
    assert server._classify_source_state("binance") == "live"
    assert server._classify_source_state("fred") == "live"
    assert server._classify_source_state("position_sizing_model") == "model"
    assert server._classify_source_state("local_backtest_model") == "synthetic"
