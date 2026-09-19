"""MEET Gate-2 — golden-set score gates (2026-09-19).

The fixture (``fixtures/meet_golden.json``) is a reviewed classification
corpus with hand-authored adversarial cases for ambiguous country names,
provider tags, generic fund-flow wording, and civilian/military nuclear use.

Gates: country/asset/topic/pair micro-F1 >= 0.95 and event_type/impact
exact-match >= 0.90. Hermetic, deterministic
(fixed now/published_at), no network, <1s.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.services import world_events as we  # noqa: E402

_FIXTURE = _HERE.parent / "fixtures" / "meet_golden.json"
_NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
_PUBLISHED_AT = "2026-09-19T11:00:00+00:00"

_EXPECTED_KEYS = {"countries", "asset_tags", "topic_tags", "event_type", "impact", "pairs"}


def _records():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _actual(record: dict, index: int) -> dict:
    text = record["text"]
    article = dict(record.get("provider") or {})
    article.update({
        "title": text,
        "url": f"https://example.test/golden/{index:03d}",
        "published_at": _PUBLISHED_AT,
    })
    rows = we.world_rows(
        [article],
        now=_NOW,
        source="gdelt",
    )
    assert len(rows) == 1, f"golden row {index} produced no row: {text!r}"
    row = rows[0]
    details = row["details"]
    return {
        "countries": row["countries"],
        "asset_tags": details["asset_tags"],
        "topic_tags": details["topic_tags"],
        "event_type": details["event_type"],
        "impact": row["impact"],
        "pairs": row["pairs"],
    }


def _f1(tp: int, fp: int, fn: int) -> float:
    denom = 2 * tp + fp + fn
    return (2 * tp / denom) if denom else 1.0


def _scores() -> dict[str, float]:
    """Micro-F1 for set fields; exact-match for scalar classifications."""
    records = _records()
    counts = {key: [0, 0, 0] for key in ("countries", "asset_tags", "topic_tags", "pairs")}
    event_ok = impact_ok = 0
    for index, record in enumerate(records):
        expected = record["expected"]
        actual = _actual(record, index)
        for key, (tp, fp, fn) in counts.items():
            exp, act = set(expected[key]), set(actual[key])
            counts[key] = [
                tp + len(exp & act),
                fp + len(act - exp),
                fn + len(exp - act),
            ]
        event_ok += actual["event_type"] == expected["event_type"]
        impact_ok += actual["impact"] == expected["impact"]
    total = len(records)
    return {
        "country_f1": _f1(*counts["countries"]),
        "asset_tag_f1": _f1(*counts["asset_tags"]),
        "topic_tag_f1": _f1(*counts["topic_tags"]),
        "event_type_exact": event_ok / total,
        "impact_exact": impact_ok / total,
        "pairs_f1": _f1(*counts["pairs"]),
        "n": float(total),
    }


def test_fixture_schema_pins_sixty_records():
    records = _records()
    assert len(records) >= 55, f"golden fixture shrank to {len(records)}"
    for record in records:
        assert set(record) in ({"text", "expected"}, {"text", "provider", "expected"}), record
        assert set(record["expected"]) == _EXPECTED_KEYS, record["text"]


def test_country_micro_f1_at_least_095():
    assert _scores()["country_f1"] >= 0.95


def test_asset_tag_micro_f1_at_least_095():
    assert _scores()["asset_tag_f1"] >= 0.95


def test_topic_tag_micro_f1_at_least_095():
    assert _scores()["topic_tag_f1"] >= 0.95


def test_event_type_exact_at_least_090():
    assert _scores()["event_type_exact"] >= 0.90


def test_impact_exact_at_least_090():
    assert _scores()["impact_exact"] >= 0.90


def test_pairs_micro_f1_at_least_095():
    assert _scores()["pairs_f1"] >= 0.95


def test_f1_penalizes_false_positives_when_expected_is_empty():
    assert _f1(0, 1, 0) == 0.0


def test_existing_boj_fixture_exactly_requires_japan():
    records = _records()
    index, record = next(
        (index, record)
        for index, record in enumerate(records)
        if record["text"] == "BOJ's Ueda hints at hike as yen slides"
    )
    assert record["expected"]["countries"] == ["JP"]
    assert _actual(record, index)["countries"] == ["JP"]


def test_golden_scoring_runs_under_one_second():
    started = time.monotonic()
    scores = _scores()
    elapsed = time.monotonic() - started
    assert scores["n"] >= 55
    assert elapsed < 1.0, f"golden scoring took {elapsed:.2f}s"
