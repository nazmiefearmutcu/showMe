"""HF classify + explain tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from showme.integrations import hf as hf_mod


@pytest.fixture(autouse=True)
def _clear_cache():
    hf_mod._HF_CACHE.clear()
    hf_mod._PIPELINE = None
    yield
    hf_mod._HF_CACHE.clear()
    hf_mod._PIPELINE = None


def test_classify_returns_unknown_when_pipeline_unavailable(monkeypatch):
    monkeypatch.setattr(hf_mod, "_get_pipeline", lambda: None)
    r = hf_mod.classify("hello")
    assert r["label"] == "unknown"
    assert r["score"] == 0.0
    assert "error" in r


def test_classify_returns_label_when_pipeline_available(monkeypatch):
    def _fake_pipe(text, top_k=3, truncation=True):
        return [
            {"label": "POSITIVE", "score": 0.85},
            {"label": "NEUTRAL", "score": 0.10},
            {"label": "NEGATIVE", "score": 0.05},
        ]
    monkeypatch.setattr(hf_mod, "_get_pipeline", lambda: _fake_pipe)
    r = hf_mod.classify("good times")
    assert r["label"] == "POSITIVE"
    assert r["score"] > 0.8
    assert len(r["top_3"]) == 3


def test_explain_produces_tr_summary():
    spec = {
        "name": "RSI test",
        "timeframe": "1h",
        "indicators": [
            {"alias": "rsi14", "id": "rsi", "params": {"period": 14}},
        ],
        "entry_rules": [
            {"kind": "crosses_below", "left": "rsi14", "right": "literal:30"},
        ],
        "exit_rules": [
            {"kind": "crosses_above", "left": "rsi14", "right": "literal:70"},
        ],
        "entry_logic": "all",
        "exit_logic": "any",
        "position": {"side": "long", "sizing_kind": "fixed_quote",
                     "sizing_value": 100, "stop_loss_pct": 2.0},
    }
    out = hf_mod.explain(spec)
    assert isinstance(out, str)
    assert len(out) >= 50
    assert "RSI test" in out
    assert "1h" in out
    assert "rsi14" in out


def test_rule_to_tr_kinds():
    from showme.integrations.hf import _rule_to_tr
    assert "yukarı kestiğinde" in _rule_to_tr({"kind": "crosses_above", "left": "rsi", "right": "literal:30"})
    assert "aşağı kestiğinde" in _rule_to_tr({"kind": "crosses_below", "left": "rsi", "right": "literal:30"})
    assert ">" in _rule_to_tr({"kind": "greater_than", "left": "a", "right": "b"})
    assert "<" in _rule_to_tr({"kind": "less_than", "left": "a", "right": "b"})
    assert "≈" in _rule_to_tr({"kind": "equals_approximately", "left": "a", "right": "b", "tolerance": 0.1})


def test_explain_empty_spec_still_returns_string():
    out = hf_mod.explain({})
    assert isinstance(out, str)
    assert "(isimsiz)" in out
