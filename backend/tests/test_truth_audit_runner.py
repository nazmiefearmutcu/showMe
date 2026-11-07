"""Orchestration tests for the strict truth audit runner (B1b).

The runner is exercised with an injected request function — no sidecar,
no network. Covers: the dual-input T3 call, one retry then
``NETWORK_FLAKE``, a sidecar restart on a refused connection, resume from
``ledger.partial.json``, and the artifact layout.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import truth_audit_runner as runner  # noqa: E402

NOW = datetime(2026, 11, 7, 20, 0, tzinfo=timezone.utc)

CATALOG = [
    {"code": "GP", "name": "Price Graph", "category": "chart", "asset_classes": ["EQUITY"],
     "description": "Candles.", "usage": {"purpose": "Candlestick price graph with volume.", "inputs": ["symbol", "range"]}},
    {"code": "TOP", "name": "Top News", "category": "news", "asset_classes": [],
     "description": "", "usage": {"purpose": "Top News function.", "inputs": ["query/params when needed"]}},
]


def body(symbol: str, close: float, **over):
    out = {
        "code": "GP", "status": "ok", "data_state": "live",
        "asOf": "2026-11-07T19:59:00+00:00", "sources": ["yahoo_chart"],
        "sourceDetails": [{"name": "yahoo_chart", "status": "ok"}],
        "instrument": {"symbol": symbol, "asset_class": "EQUITY"},
        "rows": [{"date": "2026-11-06", "close": close}, {"date": "2026-11-07", "close": close + 1}],
        "cards": [{"last": close + 1}], "series": [], "warnings": [],
    }
    out.update(over)
    return out


class FakeSidecar:
    def __init__(self, script):
        self.script = script  # callable(code, params, attempt) -> (status, body) or raises
        self.calls: list[tuple[str, dict]] = []
        self.restarts = 0

    def request(self, code, params, timeout):
        self.calls.append((code, dict(params)))
        attempt = sum(1 for c, p in self.calls if c == code and p.get("symbol") == params.get("symbol"))
        return self.script(code, params, attempt)

    def restart(self):
        self.restarts += 1


def make_runner(tmp_path, sidecar, **kw):
    return runner.StrictRunner(
        catalog=CATALOG,
        request=sidecar.request,
        restart=sidecar.restart,
        source_lookup=lambda code: None,
        keyless_alternatives={},
        out_dir=tmp_path / "run",
        now=lambda: NOW,
        **kw,
    )


def healthy(code, params, attempt):
    if code == "GP":
        return 200, body(params["symbol"], 100.0 if params["symbol"] == "AAPL" else 400.0)
    return 200, {"code": code, "status": "ok", "data_state": "live", "asOf": "2026-11-07T19:59:00+00:00",
                 "sources": ["google_news_rss"], "rows": [{"date": "2026-11-07T18:00:00+00:00", "title": "x"}]}


def test_symbol_functions_get_a_second_input_for_t3(tmp_path):
    side = FakeSidecar(healthy)
    make_runner(tmp_path, side).run()
    gp_symbols = [p.get("symbol") for c, p in side.calls if c == "GP"]
    assert "AAPL" in gp_symbols and "MSFT" in gp_symbols
    # TOP takes no symbol: no second-input call
    assert all("symbol" not in p for c, p in side.calls if c == "TOP")


def test_static_output_detected_through_runner(tmp_path):
    def static(code, params, attempt):
        if code == "GP":
            return 200, body(params["symbol"], 100.0)  # same numbers for AAPL and MSFT
        return healthy(code, params, attempt)

    ledger = make_runner(tmp_path, FakeSidecar(static)).run()
    gp = ledger["functions"]["GP"]
    assert gp["grade"] == "RED"
    assert "static_output" in {f["rule"] for case in gp["cases"] for f in case["findings"]}


def test_network_error_retried_once_then_flake(tmp_path):
    def flaky(code, params, attempt):
        if code == "TOP":
            raise ConnectionResetError("connection reset by peer")
        return healthy(code, params, attempt)

    side = FakeSidecar(flaky)
    ledger = make_runner(tmp_path, side).run()
    case = ledger["functions"]["TOP"]["cases"][0]
    assert case["grade"] == "NETWORK_FLAKE"
    first_input_calls = [p for c, p in side.calls if c == "TOP"]
    assert len(first_input_calls) == 2  # original + exactly one retry


def test_persistent_timeout_is_a_red_t8_timeout(tmp_path):
    """A local sidecar that never answers in time is a slow function, not a flake."""
    def slow(code, params, attempt):
        if code == "TOP":
            raise TimeoutError("read timed out")
        return healthy(code, params, attempt)

    ledger = make_runner(tmp_path, FakeSidecar(slow)).run()
    case = ledger["functions"]["TOP"]["cases"][0]
    assert case["grade"] == "RED"
    assert "timeout" in {f["rule"] for f in case["findings"]}


def test_refused_connection_restarts_sidecar_and_resumes(tmp_path):
    state = {"down": True}

    def dies_once(code, params, attempt):
        if code == "GP" and state["down"]:
            state["down"] = False
            raise ConnectionRefusedError("sidecar gone")
        return healthy(code, params, attempt)

    side = FakeSidecar(dies_once)
    ledger = make_runner(tmp_path, side).run()
    assert side.restarts == 1
    assert ledger["functions"]["GP"]["grade"] in {"GREEN", "AMBER"}


def test_resume_skips_completed_cases(tmp_path):
    side = FakeSidecar(healthy)
    first = make_runner(tmp_path, side)
    first.run()
    calls_first = len(side.calls)
    side2 = FakeSidecar(healthy)
    second = make_runner(tmp_path, side2, resume=True)
    ledger = second.run()
    assert len(side2.calls) == 0, "every case was already in ledger.partial.json"
    assert set(ledger["functions"]) == {"GP", "TOP"}
    assert calls_first > 0


def test_artifact_layout_and_offline_checks(tmp_path):
    ledger = make_runner(tmp_path, FakeSidecar(healthy)).run()
    run_dir = tmp_path / "run"
    assert (run_dir / "ledger.json").is_file()
    assert (run_dir / "summary.md").is_file()
    assert any((run_dir / "responses").glob("GP-EQUITY*.json"))
    saved = json.loads((run_dir / "ledger.json").read_text(encoding="utf-8"))
    assert saved["counts"] == ledger["counts"]
    # TOP's catalog help is a template -> T6 red even though the call is fine
    top_rules = {f["rule"] for f in ledger["functions"]["TOP"]["offline_findings"]}
    assert {"empty_description", "template_purpose"} <= top_rules
    assert ledger["functions"]["TOP"]["grade"] == "RED"


def test_native_codes_are_listed_not_silently_dropped(tmp_path):
    catalog = CATALOG + [{"code": "ASK", "name": "Ask", "category": "agent", "asset_classes": []}]
    r = runner.StrictRunner(
        catalog=catalog, request=FakeSidecar(healthy).request, restart=lambda: None,
        source_lookup=lambda code: None, keyless_alternatives={}, out_dir=tmp_path / "n", now=lambda: NOW,
    )
    ledger = r.run()
    assert ledger["functions"]["ASK"]["grade"] == "NOT_AUDITED"


@pytest.mark.parametrize("exc, transient", [
    (TimeoutError("t"), True), (ConnectionResetError("r"), True),
    (ConnectionRefusedError("x"), True), (ValueError("bad json"), False),
])
def test_transient_error_classification(exc, transient):
    assert runner.is_transient(exc) is transient
