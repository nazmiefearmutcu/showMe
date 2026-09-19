"""Deterministic advisory live-probe metric and threshold tests."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import meet_probe as probe  # noqa: E402


class _Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Client:
    def __init__(self, payload):
        self.payload = payload

    def get(self, *args, **kwargs):
        return _Response(self.payload)


def test_financecalendar_all_untimed_is_advisory_degraded():
    raw = {"events": [{"title": "Holiday", "time_utc": None, "impact": "low"}],
           "attribution": {"source": "financecalendar.com"}}
    row = probe._probe_fc(_Client(raw), 1)
    assert row["ok"] is False
    assert any("timed" in reason for reason in row["threshold_failures"])
    assert "DEGRADED" in probe._render([row], "now", 1, True)


def test_gdelt_metrics_include_time_url_uniqueness_and_freshness():
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    raw = {"articles": [
        {"title": "Fed decision", "url": "https://x.test/1", "seendate": stamp},
        {"title": "Fed update", "url": "https://x.test/1", "seendate": stamp},
        {"title": "Undated", "url": "https://x.test/2"},
    ]}
    row = probe._probe_gdelt(_Client(raw), 1, 10)
    assert row["timed_count"] == 2
    assert row["undated_count"] == 1
    assert row["unique_count"] == 2
    assert row["duplicate_count"] == 1
    assert row["freshest_age_minutes"] is not None
    assert row["ok"] is False
    assert row["threshold_failures"]


def test_probe_thresholds_flag_stale_duplicate_rss_without_failing_process():
    row = probe._blank("rss")
    row.update({"http_status": 200, "count": 10, "field_complete_count": 10,
                "timed_count": 10, "unique_count": 5,
                "freshest_age_minutes": 500, "feeds_healthy_count": 14,
                "feeds_expected_count": 14})
    probe._evaluate(row)
    assert row["ok"] is False
    assert any("freshest" in reason for reason in row["threshold_failures"])
    assert any("unique" in reason for reason in row["threshold_failures"])


def test_forex_factory_past_only_week_is_marked_coverage_degraded():
    row = probe._blank("ff")
    row.update({"http_status": 200, "count": 10, "timed_count": 10,
                "field_complete_count": 10, "unique_count": 10,
                "upcoming_count": 0})
    probe._evaluate(row)
    assert row["ok"] is False
    assert any("upcoming" in reason for reason in row["threshold_failures"])


def test_gdelt_probe_request_matches_meet_query_window_and_limit(monkeypatch):
    from showme.engine.services import world_events as we

    fixed_now = datetime(2026, 9, 19, 12, 34, 56, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(probe, "datetime", FixedDatetime)

    class Capture(_Client):
        def get(self, *args, **kwargs):
            self.params = kwargs["params"]
            return _Response({"articles": []})

    client = Capture({})
    probe._probe_gdelt(client, 1, 5)
    params = client.params
    assert params["query"] == we.world_query()
    assert params["maxrecords"] == we.MEET_GDELT_LIMIT
    assert params["startdatetime"] == (fixed_now - probe.timedelta(days=we.MEET_GDELT_LOOKBACK_DAYS)).strftime("%Y%m%d%H%M%S")
    assert params["mode"] == "ArtList"
    assert params["sort"] == "DateDesc"


def test_gdelt_probe_caps_request_at_app_deadline():
    class Capture(_Client):
        def get(self, *args, **kwargs):
            self.timeout = kwargs["timeout"]
            return _Response({"articles": []})

    client = Capture({})
    probe._probe_gdelt(client, 10, 75)
    assert client.timeout == 5.0


def test_gdelt_probe_marks_response_beyond_app_deadline_degraded():
    row = probe._blank("gdelt")
    row.update({"http_status": 200, "count": 1, "timed_count": 1,
                "field_complete_count": 1, "unique_count": 1,
                "freshest_age_minutes": 1, "latency_ms": 7000})
    probe._evaluate(row)
    assert row["ok"] is False
    assert any("deadline" in failure for failure in row["threshold_failures"])
