"""FLY regression tests (offline).

* FLY#2 - a non-numeric limit is an input error, not an OpenSky outage, and
  no provider call is made.
* FLY#4 - the seed describes the OpenSky flight feed the handler serves, not a
  travel list; its inputs are the ones the handler reads.
* FLY#5 - the Source time card is ISO UTC like the row timestamps.

The OpenSky adapter is replaced with an in-memory fake; nothing touches the
network.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.misc._extras import FLYFunction
from showme.manifest.seeds.fly_seed import fly

_EPOCH = 1794097110  # 2026-11-08T00:18:30Z
_STATE = [
    "abc123", "THY123", "Turkey", _EPOCH, _EPOCH,
    28.9, 41.2, 10000.0, False, 230.0, 90.0, 0.0, None,
    10000.0, None, None, None,
]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _OpenSky:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        return {"time": _EPOCH, "states": [_STATE]}


# ---------------------------------------------------------------- FLY#2 ----


def test_non_numeric_limit_is_input_error_and_skips_provider() -> None:
    opensky = _OpenSky()
    result = _run(FLYFunction(FunctionDeps(opensky=opensky)).execute(limit="abc"))
    assert result.data["status"] == "input_error", result.data
    assert "limit" in result.data["reason"]
    assert result.data["rows"] == []
    assert opensky.calls == 0, "a bad limit must be rejected before the OpenSky call"


def test_non_numeric_limit_is_not_reported_as_provider_outage() -> None:
    result = _run(FLYFunction(FunctionDeps()).execute(limit="abc"))
    assert result.data["status"] != "provider_unavailable"
    assert "invalid literal" not in str(result.data.get("reason", ""))


def test_non_numeric_flight_timeout_is_input_error() -> None:
    opensky = _OpenSky()
    result = _run(FLYFunction(FunctionDeps(opensky=opensky)).execute(flight_timeout="soon"))
    assert result.data["status"] == "input_error"
    assert "flight_timeout" in result.data["reason"]
    assert opensky.calls == 0


def test_numeric_string_limit_still_serves_live_rows() -> None:
    opensky = _OpenSky()
    result = _run(FLYFunction(FunctionDeps(opensky=opensky)).execute(limit="5"))
    assert result.data["status"] == "live"
    assert result.data["rows"][0]["callsign"] == "THY123"


# ---------------------------------------------------------------- FLY#5 ----


def test_source_time_card_is_iso_utc_like_row_timestamps() -> None:
    result = _run(FLYFunction(FunctionDeps(opensky=_OpenSky())).execute())
    card = next(c for c in result.data["cards"] if c["label"] == "Source time")
    expected = datetime.fromtimestamp(_EPOCH, tz=timezone.utc).isoformat()
    assert card["value"] == expected
    assert card["value"] == result.data["rows"][0]["last_contact_utc"]


# ---------------------------------------------------------------- FLY#4 ----


def test_seed_describes_the_opensky_feed_not_a_travel_list() -> None:
    entry = fly
    assert entry.name == "Flight Tracking"
    text = (entry.intent + " " + entry.methodology).lower()
    assert "opensky" in text
    assert "travel" not in entry.name.lower()
    assert "skyscanner" not in text and "booking" not in text
    assert "no network calls" not in text


def test_seed_inputs_are_the_ones_the_handler_reads() -> None:
    names = {spec.name for spec in fly.inputs}
    assert names == {"callsign", "country", "limit", "reference"}
    assert "kind" not in names and "destination" not in names


def test_seed_semantic_tests_match_the_feed_contract() -> None:
    tests = fly.semantic_tests
    joined = " ".join(f"{t.name} {t.description}" for t in tests).lower()
    assert "unavailable" in joined
    assert "store" not in joined and "operator" not in joined
