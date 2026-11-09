"""GP#2-RQ — the seed must not claim an interval check it does not perform.

The GP handler never rejects an interval/range pair: a window the provider
cannot fill at that bar size is returned as a shorter span with a warning
(server.py _gp_window_history). The seed interval text and the semantic-test
name/assertion must say that, not "validated against range" or "rejected".
"""
from __future__ import annotations

from showme.manifest.seeds.gp_seed import gp


def _interval_input():
    return next(inp for inp in gp.inputs if inp.name == "interval")


def test_interval_description_does_not_claim_a_validation_that_does_not_run() -> None:
    description = (_interval_input().description or "").lower()
    assert "(validated against range)" not in description, description
    assert "validated against range" not in description.replace("not validated against the range", ""), description


def test_interval_description_states_the_shorter_span_warning() -> None:
    description = (_interval_input().description or "").lower()
    assert "warning" in description and "shorter" in description, description


def test_short_intraday_semantic_test_is_named_for_the_warning_it_asserts() -> None:
    names = {t.name for t in gp.semantic_tests}
    assert "gp_invalid_interval_for_range_rejected" not in names
    test = next(t for t in gp.semantic_tests if t.name == "gp_short_intraday_span_reported_with_warning")
    assert "rejected" not in test.description.lower()
    assert "short_span_warning_present" in test.assertions
    assert "http_422_or_degraded_with_warning" not in test.assertions
