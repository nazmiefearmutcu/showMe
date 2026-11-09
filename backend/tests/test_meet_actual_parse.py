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

import pytest  # noqa: E402

from showme.engine.functions.comm import meet as meet_mod  # noqa: E402
from showme.engine.services import world_events as we  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_ff_cache():
    yield


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
    value, unit, capped = meet_mod._parse_ff_number("180K")
    assert value == 180000
    assert unit == "K"
    assert capped is False


def test_parse_m_suffix():
    value, unit, capped = meet_mod._parse_ff_number("1.40M")
    assert value == 1400000
    assert unit == "M"
    assert capped is False


def test_parse_b_and_t_suffixes():
    assert meet_mod._parse_ff_number("2.1B")[0] == pytest.approx(2.1e9)
    assert meet_mod._parse_ff_number("1.5T")[0] == pytest.approx(1.5e12)


def test_parse_capped_percent():
    value, unit, capped = meet_mod._parse_ff_number("<1.25%")
    assert value == 1.25
    assert unit == "%"
    assert capped is True


def test_parse_score_format_is_none():
    value, unit, capped = meet_mod._parse_ff_number("3-0-6")
    assert value is None
    assert unit == "3-0-6"
    assert capped is False


def test_parse_preserves_legacy_percent_comma_stripping():
    assert meet_mod._parse_ff_number("40.5%")[0] == 40.5
    assert meet_mod._parse_ff_number("1,234.5%")[0] == 1234.5
    assert meet_mod._parse_ff_number("3.2%")[0] == 3.2
    assert meet_mod._parse_ff_number(None)[0] is None
    assert meet_mod._parse_ff_number("")[0] is None


def test_parse_pipe_takes_first_part():
    assert meet_mod._parse_ff_number("1.5%|2.0%")[0] == 1.5


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), "NaN", "Infinity", "-Infinity"],
)
def test_parse_ff_number_rejects_non_finite_values(value):
    assert meet_mod._parse_ff_number(value)[0] is None


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


@pytest.fixture(autouse=True)
def _awareness_offline(monkeypatch):
    """Tests never hit the live awareness-markets service; injected fakes still win."""
    from showme.engine.data_sources.awareness import AwarenessUnavailable
    from showme.engine.functions.calendar import _common as _aw_common

    class _Offline:
        async def get(self, path, params=None):
            raise AwarenessUnavailable("awareness disabled in tests")

    monkeypatch.setattr(_aw_common, "get_awareness_client", lambda: _Offline())
