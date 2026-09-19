"""MEET gate calibration: additive scoring pinned at 100% on labels.

The fixture (meet_gate_labels.json) is the spec: every historically-pinned
outcome plus the F1/F2 recall lifts and the trivia guards. Threshold and
weights live in rss_adapter; this file locks them.
"""
from __future__ import annotations

import json
from pathlib import Path

from showme.engine.data_sources.news import rss_adapter

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "meet_gate_labels.json"


def _labels():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_gate_matches_labels_exactly():
    misses = [
        (item["title"], item["relevant"])
        for item in _labels()
        if rss_adapter._world_wire_relevant({"title": item["title"]})
        is not item["relevant"]
    ]
    assert misses == []


def test_threshold_and_weights_stable():
    assert rss_adapter._WORLD_WIRE_THRESHOLD == 40
    assert rss_adapter._EVENT_WEIGHT == 35
    assert rss_adapter._COMPANY_WEIGHT == 40
    assert rss_adapter._CONTEXT_WEIGHT == 30
    assert rss_adapter._COUNTRY_WEIGHT == 25
    assert rss_adapter._ADVICE_PENALTY == -20


def test_score_reasons_auditable():
    score, reasons = rss_adapter._world_wire_score(
        "US and China to meet on tariffs as trade war escalates"
    )
    assert score >= 40
    assert {"event", "context"} <= set(reasons)
    assert any(r.startswith("countries:") for r in reasons)
    score, reasons = rss_adapter._world_wire_score("")
    assert (score, reasons) == (0, ["empty"])


def test_advice_cannot_bury_event_but_kills_noise():
    good, _ = rss_adapter._world_wire_score(
        "Federal Reserve cuts rates: best stocks to buy now"
    )
    bad, _ = rss_adapter._world_wire_score("Best stocks to buy for retirement income")
    assert good >= rss_adapter._WORLD_WIRE_THRESHOLD > bad


def test_trivia_without_event_fails_despite_context_countries():
    score, _ = rss_adapter._world_wire_score(
        "Putin tours Beijing stadium ahead of state visit"
    )
    assert score < rss_adapter._WORLD_WIRE_THRESHOLD
