"""Round 19 — ASKB orchestrator + planner tests (no live data needed)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from showme.agents import plan_for, summarize, pick_viz  # noqa: E402
from showme.agents.planner import Plan  # noqa: E402


# ── Planner — intent classification ──────────────────────────────────────

def test_planner_detects_scan_intent():
    p = plan_for("find me crypto opportunities high conviction")
    assert p.intent == "scan"
    assert "search" in p.agents
    assert "summarizer" in p.agents
    assert "viz" in p.agents
    assert p.args.get("phases", "").startswith("A,B")
    assert p.args.get("asset_class") == "CRYPTO"


def test_planner_detects_portfolio_intent():
    p = plan_for("show me my portfolio book")
    assert p.intent == "portfolio_overview"
    assert p.action.startswith("Pull portfolio")


def test_planner_function_intent_with_code_and_symbol():
    p = plan_for("show me FA on MSFT", function_codes={"FA", "DES"})
    assert p.intent == "function"
    assert p.args["code"] == "FA"
    assert "MSFT" in p.args["symbols"]


def test_planner_lookup_falls_back_for_unknown_intent_with_symbol():
    p = plan_for("what's TSLA doing today")
    # "doing today" doesn't match any intent regex → fallback because TSLA was
    # extracted as a symbol.
    assert p.intent == "lookup"
    assert "TSLA" in p.args["symbols"]
    assert "viz" in p.agents


def test_planner_unknown_intent_no_symbol():
    p = plan_for("hello")
    assert p.intent == "unknown"
    assert p.agents == []


def test_planner_skips_function_codes_as_symbols():
    p = plan_for("show me FA on AAPL", function_codes={"FA", "DES"})
    # FA shouldn't pollute the symbols list since it's a function code.
    assert "FA" not in p.args.get("symbols", [])
    assert "AAPL" in p.args["symbols"]


def test_planner_does_not_treat_i_as_ticker():
    p = plan_for("morning briefing what should I watch")
    assert p.intent == "briefing"
    assert "I" not in p.args.get("symbols", [])
    assert "symbols" not in p.rationale


def test_planner_picks_direction_hint():
    p = plan_for("find me bullish breakouts in equities")
    assert p.args.get("direction") == "LONG"


def test_planner_empty_query_returns_unknown_no_agents():
    p = plan_for("")
    assert p.intent == "unknown"
    assert p.agents == []


def test_planner_briefing_uses_fanout_agent():
    p = plan_for("morning briefing what should I watch")
    assert p.intent == "briefing"
    assert "fanout" in p.agents
    assert "summarizer" in p.agents
    assert "viz" in p.agents
    assert "search" not in p.agents  # fanout supplants search


def test_planner_briefing_action_describes_branches():
    p = plan_for("give me a market overview")
    assert p.intent == "briefing"
    assert "Fan-out" in p.action


def test_summarize_fanout_handles_empty_branches():
    from showme.agents import summarize as summarize_fn
    from showme.agents.planner import Plan as P

    out = summarize_fn(P(intent="briefing", action="brief", agents=["fanout"]),
                       {"kind": "fanout", "branches": {}})
    assert "no usable branches" in out["narrative"].lower() or "Briefing" in out["narrative"]


def test_pick_viz_briefing_returns_three_pane_split():
    from showme.agents import pick_viz as pick_viz_fn
    from showme.agents.planner import Plan as P

    viz = pick_viz_fn(P(intent="briefing", action="brief", agents=["fanout"]),
                       {"kind": "fanout", "branches": {}})
    assert viz["kind"] == "split"
    codes = {p["code"] for p in viz["panes"]}
    assert {"PORT", "SCAN", "TOP"}.issubset(codes)


# ── Summarizer — narrative generation ────────────────────────────────────

def test_summarize_scan_includes_counts_and_top_tickers():
    plan = Plan(intent="scan", action="run scan", args={"asset_class": "CRYPTO"},
                agents=["search", "summarizer", "viz"])
    sr = {
        "kind": "scan",
        "data": {
            "asset_class": "CRYPTO",
            "universe_key": "CRYPTO:MAJORS",
            "rows": [
                {"symbol": "BTCUSDT", "direction": "LONG", "confidence": 80,
                 "fine": {"overextension": {"overextended": True}},
                 "position_overlap": {"held": True}},
                {"symbol": "ETHUSDT", "direction": "LONG", "confidence": 70},
                {"symbol": "SOLUSDT", "direction": "SHORT", "confidence": 65},
            ],
        },
        "warnings": [],
    }
    out = summarize(plan, sr)
    assert "3 candidates" in out["narrative"]
    assert "CRYPTO:MAJORS" in out["narrative"]
    assert "BTCUSDT" in out["narrative"]
    assert any(h["label"] == "long" and h["value"] == 2 for h in out["highlights"])
    assert any(h["label"] == "short" and h["value"] == 1 for h in out["highlights"])
    assert any(h["label"] == "held in book" and h["value"] == 1 for h in out["highlights"])


def test_summarize_function_with_dict_payload():
    plan = Plan(intent="function", action="run FA",
                args={"code": "FA", "symbols": ["MSFT"]},
                agents=["search", "summarizer", "viz"])
    sr = {
        "kind": "function",
        "code": "FA",
        "data": {
            "elapsed_ms": 4080,
            "sources": ["sec_edgar"],
            "data": {"income_statement": {}, "balance_sheet": {}, "ratios": {}},
        },
        "warnings": [],
    }
    out = summarize(plan, sr)
    assert "MSFT" in out["narrative"]
    assert "4080" in out["narrative"]
    assert "sec_edgar" in out["narrative"]


def test_summarize_noop_explains_unhandled():
    plan = Plan(intent="unknown", action="noop", agents=[])
    out = summarize(plan, {"kind": "noop"})
    assert "couldn't classify" in out["narrative"].lower()


# ── Viz — pane hint mapping ──────────────────────────────────────────────

def test_pick_viz_scan_hints_to_scan_pane():
    plan = Plan(intent="scan", action="run", agents=["search", "summarizer", "viz"])
    viz = pick_viz(plan, {"kind": "scan", "data": {"rows": [1, 2, 3], "universe_key": "X"}})
    assert viz["kind"] == "table"
    assert viz["open_pane_hint"] == {"code": "SCAN"}
    assert viz["rows_n"] == 3


def test_pick_viz_function_des_hints_to_des_pane():
    plan = Plan(intent="function", action="run DES",
                args={"code": "DES", "symbols": ["AAPL"]},
                agents=["search", "summarizer", "viz"])
    viz = pick_viz(plan, {"kind": "function", "code": "DES"})
    assert viz["kind"] == "cards"
    assert viz["open_pane_hint"]["code"] == "DES"
    assert viz["open_pane_hint"]["symbol"] == "AAPL"


def test_pick_viz_function_gp_hints_to_chart():
    plan = Plan(intent="function", action="run GP",
                args={"code": "GP", "symbols": ["TSLA"]},
                agents=["search", "summarizer", "viz"])
    viz = pick_viz(plan, {"kind": "function", "code": "GP"})
    assert viz["kind"] == "chart"
    assert viz["open_pane_hint"]["symbol"] == "TSLA"


def test_pick_viz_unknown_kind_returns_none():
    plan = Plan(intent="unknown", action="noop", agents=[])
    viz = pick_viz(plan, {"kind": "noop"})
    assert viz == {"kind": "none"}


# ── Search _jsonify (defensive serialization) ───────────────────────────

def test_jsonify_walks_dict_and_list():
    from showme.agents.search import _jsonify

    out = _jsonify({"a": [1, 2, 3], "b": {"c": True, "d": None}})
    assert out == {"a": [1, 2, 3], "b": {"c": True, "d": None}}


def test_jsonify_clamps_nan_and_inf_floats():
    from showme.agents.search import _jsonify

    out = _jsonify({"x": float("nan"), "y": float("inf"), "z": 1.5})
    assert out["x"] is None
    assert out["y"] is None
    assert out["z"] == 1.5


def test_jsonify_handles_pandas_series():
    pd = pytest.importorskip("pandas")
    from showme.agents.search import _jsonify

    s = pd.Series({"a": 1, "b": 2})
    out = _jsonify(s)
    assert out == {"a": 1, "b": 2}


def test_jsonify_handles_pandas_dataframe():
    pd = pytest.importorskip("pandas")
    from showme.agents.search import _jsonify

    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    out = _jsonify(df)
    assert out == [{"x": 1, "y": 3}, {"x": 2, "y": 4}]
