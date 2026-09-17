"""MEET Bloomberg Faz 1 — Actual/Forecast/Previous parse pins.

Covers the backend parse + parallel race acceptance criteria:
  * ``180K -> 180000``, ``1.40M -> 1400000`` (K/M/B/T multipliers),
  * ``<1.25% -> 1.25 + capped`` (leading ``<``),
  * ``3-0-6 -> None`` (score format is not a number),
  * legacy ``%``/``,`` stripping is preserved,
  * ``details["actual"]`` survives ``economic_rows``,
  * an empty FF fetch is NOT written to the TTL cache.

Fully offline: no test performs real network I/O.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest

from showme.engine.functions.macro import eco as eco_mod
from showme.engine.services import world_events as we


@pytest.fixture(autouse=True)
def _reset_ff_cache():
    eco_mod._ff_cache["fetched_at"] = 0.0
    eco_mod._ff_cache["rows"] = []
    yield
    eco_mod._ff_cache["fetched_at"] = 0.0
    eco_mod._ff_cache["rows"] = []


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeFFClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    async def get(self, url, timeout=None):
        self.calls += 1
        return _FakeResp(self._payload)


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_parse_k_suffix():
    value, unit, capped = eco_mod._parse_ff_number("180K")
    assert value == 180000
    assert unit == "K"
    assert capped is False


def test_parse_m_suffix():
    value, unit, capped = eco_mod._parse_ff_number("1.40M")
    assert value == 1400000
    assert unit == "M"
    assert capped is False


def test_parse_b_and_t_suffixes():
    assert eco_mod._parse_ff_number("2.1B")[0] == pytest.approx(2.1e9)
    assert eco_mod._parse_ff_number("1.5T")[0] == pytest.approx(1.5e12)


def test_parse_capped_percent():
    value, unit, capped = eco_mod._parse_ff_number("<1.25%")
    assert value == 1.25
    assert unit == "%"
    assert capped is True


def test_parse_score_format_is_none():
    value, unit, capped = eco_mod._parse_ff_number("3-0-6")
    assert value is None
    assert unit == "3-0-6"
    assert capped is False


def test_parse_preserves_legacy_percent_comma_stripping():
    assert eco_mod._parse_ff_number("40.5%")[0] == 40.5
    assert eco_mod._parse_ff_number("1,234.5%")[0] == 1234.5
    assert eco_mod._parse_ff_number("3.2%")[0] == 3.2
    assert eco_mod._parse_ff_number(None)[0] is None
    assert eco_mod._parse_ff_number("")[0] is None


def test_parse_pipe_takes_first_part():
    assert eco_mod._parse_ff_number("1.5%|2.0%")[0] == 1.5


def test_normalize_ff_rows_keeps_raw_fields():
    rows = eco_mod._normalize_ff_rows([
        {"title": "Non Farm Payrolls", "country": "USD",
         "date": "2026-09-04T08:30:00-04:00",
         "impact": "High", "forecast": "180K", "actual": "<1.25%", "previous": "175K"},
    ])
    assert len(rows) == 1
    row = rows[0]
    assert row["forecast"] == "180K"
    assert row["forecast_raw"] == "180K"
    assert row["actual_raw"] == "<1.25%"
    assert row["previous_raw"] == "175K"


def test_normalize_events_parses_suffixes_and_surprise():
    today = datetime.now(UTC).date().isoformat()
    rows = eco_mod._normalize_events([
        {"country": "US", "event": "Payrolls", "date": today,
         "importance": "high", "forecast": "180K", "actual": "210K", "previous": "175K"},
    ], country=None, importance=None, days=30)
    assert len(rows) == 1
    row = rows[0]
    assert row["forecast"] == 180000
    assert row["actual"] == 210000
    assert row["previous"] == 175000
    assert row["surprise"] == 30000


def test_economic_rows_details_preserves_actual():
    now = datetime.now(UTC)
    stamp = (now + timedelta(hours=4)).isoformat()
    rows, dropped = we.economic_rows([{
        "country": "US",
        "event": "CPI y/y",
        "date": stamp,
        "importance": "High",
        "forecast": "3.2%",
        "actual": "3.3%",
        "previous": "3.0%",
        "unit": "%",
    }], now=now)
    assert dropped == 0
    assert rows[0]["details"]["actual"] == "3.3%"
    assert rows[0]["details"]["forecast"] == "3.2%"
    assert rows[0]["details"]["previous"] == "3.0%"


def test_empty_ff_result_is_not_cached():
    today = datetime.now(UTC).date()
    good = [{
        "title": "CPI y/y", "country": "USD",
        "date": f"{(today + timedelta(days=1)).isoformat()}T13:30:00-04:00",
        "impact": "High", "forecast": "3.2%", "actual": "", "previous": "3.0%",
    }]
    client = _FakeFFClient(good)
    first = _run(eco_mod._forex_factory_events(client=client, timeout=5.0))
    assert len(first) == 1
    assert client.calls == 1

    # An empty upstream reply must not poison the TTL cache: expire the
    # good entry so the empty reply is actually fetched, then verify the
    # cache still holds the good rows.
    eco_mod._ff_cache["fetched_at"] = 0.0
    empty_client = _FakeFFClient([])
    empty = _run(eco_mod._forex_factory_events(client=empty_client, timeout=5.0))
    assert empty == []
    assert empty_client.calls == 1
    assert eco_mod._ff_cache["rows"] != []
    assert len(eco_mod._ff_cache["rows"]) == 1
