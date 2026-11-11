"""MEET numeric depth: parsed values, unit-aware surprise, revisions, tz offset.

Hermetic (live FF snapshot carries no Actual+Forecast pairs most weeks).
"""
from __future__ import annotations

import pytest

import asyncio
from datetime import UTC, datetime, timedelta

from showme.engine.functions.comm import meet as meet_mod
from showme.engine.services import world_events as we


def _run(coro):
    return asyncio.run(coro)


def _row(title="CPI y/y", actual="3.3%", forecast="3.2%", previous="3.0%",
         country="USD", hours=3):
    return {
        "title": title, "country": country,
        "date": (datetime.now(UTC) + timedelta(hours=hours)).isoformat(),
        "impact": "High", "forecast": forecast, "actual": actual,
        "previous": previous,
    }


def test_attach_computes_surprise_and_pct():
    rows, _ = we.economic_rows([_row()], now=datetime.now(UTC))
    meet_mod._attach_numerics(rows)
    d = rows[0]["details"]
    assert d["actual_num"] == 3.3 and d["forecast_num"] == 3.2
    assert d["unit"] == "%"
    assert d["surprise"] == 0.1
    assert d["surprise_pct"] == round(0.1 / 3.2, 6)
    assert d["surprise_basis"] == "actual_minus_forecast"


def test_scaled_units_are_comparable():
    rows, _ = we.economic_rows(
        [_row(title="Payrolls", actual="180K", forecast="175K")],
        now=datetime.now(UTC),
    )
    meet_mod._attach_numerics(rows)
    d = rows[0]["details"]
    assert d["actual_num"] == 180000.0 and d["forecast_num"] == 175000.0
    assert d["surprise"] == 5000.0


def test_percent_vs_unitless_is_unit_mismatch():
    rows, _ = we.economic_rows(
        [_row(actual="3.3%", forecast="3.2")], now=datetime.now(UTC)
    )
    meet_mod._attach_numerics(rows)
    d = rows[0]["details"]
    assert d["surprise"] is None and d["surprise_pct"] is None
    assert d["surprise_basis"] == "unit_mismatch"


def test_non_numeric_and_missing_bases():
    rows, _ = we.economic_rows(
        [_row(title="A", actual="N/A", forecast="3.2"),
         _row(title="B", actual="", forecast="")],
        now=datetime.now(UTC),
    )
    meet_mod._attach_numerics(rows)
    assert rows[0]["details"]["surprise_basis"] == "non_numeric"
    assert rows[1]["details"]["surprise_basis"] == "missing_value"


def test_raw_strings_untouched():
    rows, _ = we.economic_rows([_row()], now=datetime.now(UTC))
    meet_mod._attach_numerics(rows)
    d = rows[0]["details"]
    assert d["actual"] == "3.3%" and d["forecast"] == "3.2%"


def test_unit_never_takes_raw_text():
    rows, _ = we.economic_rows(
        [_row(title="A", actual="N/A", forecast="3.2", previous="3.0"),
         _row(title="B", actual="abc", forecast="", previous="")],
        now=datetime.now(UTC),
    )
    meet_mod._attach_numerics(rows)
    assert rows[0]["details"]["unit"] == ""
    assert rows[0]["details"]["surprise_basis"] == "non_numeric"
    assert rows[1]["details"]["unit"] == ""
    assert rows[1]["details"]["surprise_basis"] == "non_numeric"


def test_unit_falls_back_to_previous_print():
    rows, _ = we.economic_rows(
        [_row(title="C", actual="", forecast="", previous="3.0%")],
        now=datetime.now(UTC),
    )
    meet_mod._attach_numerics(rows)
    assert rows[0]["details"]["unit"] == "%"
    assert rows[0]["details"]["surprise_basis"] == "missing_value"


def test_capped_cells_flag_estimate():
    rows, _ = we.economic_rows(
        [_row(title="C", actual="<0.1", forecast="0.05")],
        now=datetime.now(UTC),
    )
    meet_mod._attach_numerics(rows)
    d = rows[0]["details"]
    assert d["surprise"] == 0.05
    assert d["capped"] is True
    assert d["surprise_basis"] == "capped_estimate"


def test_revision_prefers_actual_and_flags():
    now = datetime.now(UTC)
    stamp = (now + timedelta(hours=3)).isoformat()
    base = {"title": "CPI y/y", "country": "USD", "date": stamp,
            "impact": "High", "forecast": "3.2%", "previous": "3.0%"}

    rows, _ = we.economic_rows(
        [{**base, "actual": ""}, {**base, "actual": "3.3%"}], now=now,
        stats={},
    )
    assert len(rows) == 1
    assert rows[0]["details"]["actual"] == "3.3%"
    assert rows[0]["details"].get("revised") is True


def test_identical_duplicate_not_flagged_revised():
    now = datetime.now(UTC)
    stamp = (now + timedelta(hours=3)).isoformat()
    base = {"title": "CPI y/y", "country": "USD", "date": stamp,
            "impact": "High", "forecast": "3.2%", "actual": "3.3%"}
    stats: dict = {}
    rows, _ = we.economic_rows([dict(base), dict(base)], now=now, stats=stats)
    assert len(rows) == 1 and stats["duplicate_rows_dropped"] == 1
    assert rows[0]["details"].get("revised") is not True


def test_provider_tz_offset_kept():
    rows, _ = we.economic_rows(
        [{"title": "CPI", "country": "USD",
          "date": "2026-09-19T08:30:00-04:00", "impact": "High"}],
        now=datetime.now(UTC),
    )
    assert rows[0]["when_utc"].endswith("+00:00")
    assert rows[0]["details"]["provider_tz_offset"] == "-04:00"


class _FakeGDELT:
    def __init__(self, articles=None):
        self.articles = articles or []

    async def fetch(self, request):
        return list(self.articles)


class _FakeFFClient:
    def __init__(self, payload):
        self._payload = payload

    async def get(self, url, timeout=None):
        class _R:
            def raise_for_status(self):
                return None

            def json(inner_self):
                return self._payload

        return _R()


@pytest.fixture(autouse=True)
def _awareness_offline(monkeypatch):
    """Tests never hit the live awareness-markets service; injected fakes still win."""
    from showme.engine.data_sources.awareness import AwarenessUnavailable
    from showme.engine.functions.calendar import _common as _aw_common

    class _Offline:
        async def get(self, path, params=None):
            raise AwarenessUnavailable("awareness disabled in tests")

    monkeypatch.setattr(_aw_common, "get_awareness_client", lambda: _Offline())
