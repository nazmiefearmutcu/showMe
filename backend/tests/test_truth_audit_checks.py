"""Unit tests for the strict function truth checks (B1, spec section 2).

Every check T1-T8 gets at least one true positive (the defect is caught)
and one true negative (a clean response passes). Bodies are minimal
FunctionResult-shaped dicts as served by ``/api/fn/<code>``.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from showme.audit import truth
from showme.audit.truth import Finding

NOW = datetime(2026, 11, 7, 20, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def cfg():
    return truth.load_config()


def ok_body(**over):
    body = {
        "code": "GP",
        "status": "ok",
        "data_state": "live",
        "asOf": "2026-11-07T19:59:00+00:00",
        "sources": ["yahoo_chart"],
        "sourceDetails": [{"name": "yahoo_chart", "asOf": "2026-11-07T19:59:00+00:00", "status": "ok"}],
        "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
        "rows": [
            {"date": "2026-11-05T00:00:00+00:00", "close": 268.1},
            {"date": "2026-11-06T00:00:00+00:00", "close": 270.4},
        ],
        "series": [],
        "cards": [{"last": 270.4, "change_pct": 0.86}],
        "warnings": [],
    }
    body.update(over)
    return body


def rules(findings: list[Finding]) -> set[str]:
    return {f.rule for f in findings}


# ── config ────────────────────────────────────────────────────────────────


def test_config_loads_tables(cfg):
    assert cfg.max_age_days["daily"] > 0
    assert "NONE" in cfg.fake_source_names
    assert cfg.input_pairs["EQUITY"][0] != cfg.input_pairs["EQUITY"][1]


# ── T1 contract ───────────────────────────────────────────────────────────


def test_t1_clean_ok_passes():
    assert truth.check_contract(ok_body()) == []


def test_t1_flags_transport_and_contract_errors():
    assert "request_error" in rules(truth.check_contract(None, error="TimeoutError"))
    assert "http_error" in rules(truth.check_contract({"detail": "x"}, http_status=500))
    assert "invalid_status" in rules(truth.check_contract(ok_body(status="weird")))


def test_t1_non_ok_needs_reason_and_next_action():
    body = ok_body(status="provider_unavailable")
    assert {"missing_reason", "missing_next_action"} <= rules(truth.check_contract(body))
    honest = ok_body(status="provider_unavailable", reason="FRED down", nextAction="Retry later")
    assert truth.check_contract(honest) == []


def test_t1_sentinel_text():
    body = ok_body(rows=[{"note": "No rows"}])
    assert "sentinel_text" in rules(truth.check_contract(body))


# ── T2 provenance ─────────────────────────────────────────────────────────


def test_t2_real_fresh_source_passes(cfg):
    assert truth.check_provenance(ok_body(), code="GP", category="chart", cfg=cfg, now=NOW) == []


def test_t2_missing_or_fake_source(cfg):
    assert "no_source" in rules(
        truth.check_provenance(ok_body(sources=[], sourceDetails=[]), code="GP", category="chart", cfg=cfg, now=NOW)
    )
    assert "fake_source" in rules(
        truth.check_provenance(ok_body(sources=["NONE"]), code="FLDS", category="api", cfg=cfg, now=NOW)
    )
    assert "fake_source" in rules(
        truth.check_provenance(ok_body(sources=["demo_feed"]), code="X", category="misc", cfg=cfg, now=NOW)
    )


def test_t2_live_claim_from_computed_source_only(cfg):
    details = [{"name": "greeks", "status": "ok"}]  # as the real GREEKS envelope ships
    body = ok_body(sources=["greeks"], sourceDetails=details, data_state="live")
    assert "live_claim_without_provider" in rules(
        truth.check_provenance(body, code="GREEKS", category="portfolio", cfg=cfg, now=NOW)
    )
    honest = ok_body(sources=["greeks"], sourceDetails=details, data_state="model")
    assert "live_claim_without_provider" not in rules(
        truth.check_provenance(honest, code="GREEKS", category="portfolio", cfg=cfg, now=NOW)
    )


def test_t2_stale_daily_data(cfg):
    stale = ok_body(rows=[{"date": "2026-09-01", "close": 1.0}])
    assert "stale_data" in rules(truth.check_provenance(stale, code="GP", category="chart", cfg=cfg, now=NOW))


def test_t2_missing_as_of(cfg):
    body = ok_body()
    body.pop("asOf")
    assert "missing_as_of" in rules(truth.check_provenance(body, code="GP", category="chart", cfg=cfg, now=NOW))


def test_t2_skips_non_ok(cfg):
    body = ok_body(status="empty", sources=[], reason="no positions", nextAction="add positions")
    assert truth.check_provenance(body, code="PVAR", category="portfolio", cfg=cfg, now=NOW) == []


# ── T3 input sensitivity ──────────────────────────────────────────────────


def test_t3_identical_numbers_for_different_inputs():
    a = ok_body()
    b = ok_body(instrument={"symbol": "MSFT", "asset_class": "EQUITY"}, asOf="2026-11-07T19:59:30+00:00")
    assert "static_output" in rules(truth.check_input_sensitivity(a, b))


def test_t3_different_numbers_pass():
    a = ok_body()
    b = ok_body(rows=[{"date": "2026-11-06", "close": 501.2}, {"date": "2026-11-07", "close": 499.0}],
                cards=[{"last": 499.0, "change_pct": -0.44}])
    assert truth.check_input_sensitivity(a, b) == []


def test_t3_ignores_too_few_numbers():
    a = ok_body(rows=[], cards=[{"n": 1}])
    b = ok_body(rows=[], cards=[{"n": 1}])
    assert truth.check_input_sensitivity(a, b) == []


# ── T4 placeholder fingerprints ───────────────────────────────────────────


def test_t4_response_placeholder_not_requested(cfg):
    body = ok_body(rows=[{"metric": "risk budget", "account": 10000, "risk_pct": 0.01}])
    found = truth.check_response_placeholders(body, request_params={"symbol": "AAPL"}, cfg=cfg)
    assert "placeholder_value" in rules(found)


def test_t4_requested_value_is_not_a_placeholder(cfg):
    body = ok_body(rows=[{"strike": 105, "spot": 100}])
    params = {"positions": [{"strike": 105, "spot": 100}]}
    assert truth.check_response_placeholders(body, request_params=params, cfg=cfg) == []


def test_t4_crypto_demo_universe_for_equity_request(cfg):
    body = ok_body(rows=[{"symbol": "BTCUSDT"}, {"symbol": "ETHUSDT"}, {"symbol": "SOLUSDT"}])
    found = truth.check_response_placeholders(body, request_params={"symbol": "AAPL", "asset_class": "EQUITY"}, cfg=cfg)
    assert "demo_universe" in rules(found)


SOURCE_WITH_DEFAULTS = '''
class PSC:
    def execute(self, account=10_000, risk_pct=0.01):
        size = params.get("account", 10000)
        ticket = {"quantity": 0, "strike": 105}
        return run(entry=100)
'''

SOURCE_CLEAN = '''
TRADING_DAYS = 252
def annualize(vol, periods=252):
    return vol * (periods ** 0.5)
def execute(self, account=None):
    if account is None:
        raise ValueError("account required")
    qty = 0.0                       # accumulator, not an input
    for slot in fills:
        qty += float(slot.get("qty", 0.0))   # parsing a data record
'''


def test_t4_response_placeholder_reported_once(cfg):
    body = ok_body(rows=[{"account": 10000}], cards=[{"account": 10000}], data={"account": 10000})
    found = truth.check_response_placeholders(body, request_params={}, cfg=cfg)
    assert len(found) == 1


def test_t4_ast_finds_placeholder_defaults(cfg):
    found = truth.scan_source_placeholders(SOURCE_WITH_DEFAULTS, "psc.py", cfg=cfg)
    assert len(found) >= 5
    assert all(f.check == "T4" and f.severity == "amber" for f in found)
    assert any("psc.py:3" in (f.location or "") for f in found)


def test_t4_ast_ignores_real_constants(cfg):
    assert truth.scan_source_placeholders(SOURCE_CLEAN, "ok.py", cfg=cfg) == []


# ── T5 asset compatibility ────────────────────────────────────────────────


def test_t5_catalog_example_outside_declared_classes():
    entry = {"code": "YAS", "asset_classes": ["BOND"], "usage": {"example": {"symbol": "AAPL", "asset_class": "EQUITY"}}}
    assert "example_asset_mismatch" in rules(truth.check_catalog_entry_assets(entry))
    good = {"code": "YAS", "asset_classes": ["BOND"], "usage": {"example": {"symbol": "US10Y", "asset_class": "BOND"}}}
    assert truth.check_catalog_entry_assets(good) == []


def test_t5_response_asset_class_differs_from_request(cfg):
    body = ok_body(instrument={"symbol": "US10Y", "asset_class": "EQUITY"})
    assert "response_asset_mismatch" in rules(truth.check_response_assets(body, requested_asset="BOND", cfg=cfg))
    assert truth.check_response_assets(ok_body(), requested_asset="EQUITY", cfg=cfg) == []


def test_t5_unsupported_asset_guard_text(cfg):
    body = ok_body(status="input_error", reason="YAS does not support EQUITY", nextAction="pick a bond")
    assert "asset_not_supported" in rules(truth.check_response_assets(body, requested_asset="EQUITY", cfg=cfg))


# ── T6 help text ──────────────────────────────────────────────────────────


def test_t6_template_help_is_flagged(cfg):
    entry = {"code": "MARS", "description": "", "usage": {"purpose": "Multi-Asset Risk function.", "inputs": ["symbol"]}}
    found = rules(truth.check_help_text(entry, cfg=cfg))
    assert {"empty_description", "template_purpose"} <= found


def test_t6_specific_help_passes(cfg):
    entry = {
        "code": "PSC",
        "description": "Risk-based position sizing with R-multiples and Kelly fraction.",
        "usage": {"purpose": "Size a position from account equity, risk % and stop distance (fixed-fractional + Kelly).",
                  "inputs": ["account", "risk_pct", "entry", "stop"]},
    }
    assert truth.check_help_text(entry, cfg=cfg) == []


# ── T7 numeric sanity ─────────────────────────────────────────────────────


def test_t7_clean_numbers_pass(cfg):
    assert truth.check_numeric_sanity(ok_body(), code="GP", cfg=cfg, now=NOW) == []


@pytest.mark.parametrize(
    "rows, rule",
    [
        ([{"vol": math.nan}], "non_finite"),
        ([{"value": math.inf}], "non_finite"),
        ([{"volatility": -0.2}], "negative_volatility"),
        ([{"probability": 1.4}], "probability_out_of_range"),
        ([{"weight": 0.5}, {"weight": 0.2}], "weights_not_normalized"),
        ([{"date": "2027-03-01", "close": 1.0}], "future_date"),
    ],
)
def test_t7_detects_bad_numbers(cfg, rows, rule):
    assert rule in rules(truth.check_numeric_sanity(ok_body(rows=rows), code="GP", cfg=cfg, now=NOW))


def test_t7_calendar_functions_may_have_future_dates(cfg):
    body = ok_body(rows=[{"date": "2027-03-01", "event": "FOMC"}])
    assert truth.check_numeric_sanity(body, code="ECO", cfg=cfg, now=NOW) == []


def test_t7_probability_percent_scale_allowed(cfg):
    body = ok_body(rows=[{"probability_pct": 63.0}])
    assert truth.check_numeric_sanity(body, code="WIRP", cfg=cfg, now=NOW) == []


# ── T8 latency ────────────────────────────────────────────────────────────


def test_t8_latency_budget(cfg):
    assert truth.check_latency("GP", 1.2, warm=True, cfg=cfg) == []
    assert "slow" in rules(truth.check_latency("GP", 5.0, warm=True, cfg=cfg))
    assert "slow" in rules(truth.check_latency("GP", 20.0, warm=False, cfg=cfg))
    assert truth.check_latency("BRIEF", 20.0, warm=False, cfg=cfg) == []


# ── grading ───────────────────────────────────────────────────────────────


def test_grade_green_amber_red():
    red = Finding(check="T2", rule="fake_source", severity="red", detail="x")
    amber = Finding(check="T4", rule="placeholder_default", severity="amber", detail="x")
    assert truth.grade([], status="ok", keyless_alternative_known=False) == "GREEN"
    assert truth.grade([amber], status="ok", keyless_alternative_known=False) == "AMBER"
    assert truth.grade([red, amber], status="ok", keyless_alternative_known=False) == "RED"


def test_grade_honest_unavailable_depends_on_known_alternative():
    assert truth.grade([], status="provider_unavailable", keyless_alternative_known=False) == "AMBER"
    assert truth.grade([], status="provider_unavailable", keyless_alternative_known=True) == "RED"
    assert truth.grade([], status="calc_error", keyless_alternative_known=False) == "RED"
    assert truth.grade([], status="input_error", keyless_alternative_known=False) == "RED"


def test_grade_network_flake_is_separate():
    assert truth.grade([], status="ok", keyless_alternative_known=False, network_flake=True) == "NETWORK_FLAKE"
