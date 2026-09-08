"""ECO — live calendar feeds with an honest empty/error fallback.

Contract after the 2026-09-08 default-polarity flip (survey S2 H-3/c#1):

  * ECO serves REAL calendar feeds by default:
    tradingeconomics → finnhub → keyless ForexFactory weekly JSON
    (``https://nfs.faireconomy.media/ff_calendar_thisweek.json``, parsed
    with a small TTL cache and a fetch timeout).
  * When every live provider fails, ECO returns an honest
    ``provider_unavailable`` envelope with EMPTY rows — the invented
    ``_calendar_feed_model`` schedule is never shown unlabelled at
    HTTP 200.
  * ``reference=true`` is the only way to see the illustrative
    template, and its rows still never carry fabricated ``actual``
    prints.

These tests are fully offline: the ForexFactory HTTP leg is driven via
the ``_http_client`` injection seam (same pattern as ECFC).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest  # noqa: E402

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.functions.macro import eco as eco_mod  # noqa: E402
class _FailingProvider:
    """Stand-in calendar provider whose async call always raises."""

    async def calendar(self, *args, **kwargs):
        raise RuntimeError("provider down")

    async def economic_calendar(self, *args, **kwargs):
        raise RuntimeError("provider down")


class _LiveTE:
    async def calendar(self, *args, **kwargs):
        return [
            {
                "country": "US",
                "event": "CPI YoY",
                "date": None,
                "importance": "high",
                "forecast": 3.1,
                "actual": 3.2,
                "previous": 3.0,
                "unit": "%",
            },
        ]


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeFFClient:
    """Returns a ForexFactory-shaped weekly calendar; counts calls.

    Event dates are computed relative to *now* so the forward date-window
    filter in ``_normalize_events`` never ages the fixture out.
    """

    def __init__(self, payload=None, boom=False):
        if payload is None:
            today = datetime.now(timezone.utc).date()
            d1 = (today + timedelta(days=1)).isoformat()
            d2 = (today + timedelta(days=2)).isoformat()
            payload = [
                {
                    "title": "CPI y/y",
                    "country": "USD",
                    "date": f"{d1}T13:30:00-04:00",
                    "impact": "High",
                    "forecast": "3.2%",
                    "actual": "",
                    "previous": "3.0%",
                },
                {
                    "title": "ECB Rate Decision",
                    "country": "EUR",
                    "date": f"{d2}T14:15:00+02:00",
                    "impact": "High",
                    "forecast": "2.0%",
                    "actual": None,
                    "previous": "2.25%",
                },
            ]
        self._payload = payload
        self._boom = boom
        self.calls = 0

    async def get(self, url, timeout=None):
        self.calls += 1
        if self._boom:
            raise RuntimeError("forex factory unreachable")
        return _FakeResp(self._payload)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_ff_cache():
    eco_mod._ff_cache["fetched_at"] = 0.0
    eco_mod._ff_cache["rows"] = []
    yield
    eco_mod._ff_cache["fetched_at"] = 0.0
    eco_mod._ff_cache["rows"] = []


def test_all_providers_failing_returns_honest_empty_error_state():
    """TE + finnhub + ForexFactory all fail → provider_unavailable with
    EMPTY rows. The invented calendar must NOT appear at HTTP 200."""
    deps = FunctionDeps(tradingeconomics=_FailingProvider(), finnhub=_FailingProvider())
    fn = eco_mod.ECOFunction(deps=deps)
    fn._http_client = _FakeFFClient(boom=True)
    result = _run(fn.execute(country="US", days=30))

    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.data["events"] == []
    assert result.sources == ["no_live_source"]
    # Every provider failure is surfaced — nothing failed silently.
    warning_blob = " ".join(result.warnings).lower()
    assert "tradingeconomics" in warning_blob
    assert "finnhub" in warning_blob
    assert "forex_factory" in warning_blob
    # …and metadata marks the payload as a labelled fallback — a failed
    # live ATTEMPT is not a live CLAIM (R2 C-1: a truthy live stamp here
    # used to ride the sanitizer voucher to a LIVE pill on an empty
    # provider_unavailable envelope).
    assert result.metadata.get("fallback") is True
    assert result.metadata.get("live") is False


def test_forex_factory_success_serves_live_rows():
    """Keyless ForexFactory weekly JSON becomes live calendar rows."""
    deps = FunctionDeps()  # no keyed providers at all
    fn = eco_mod.ECOFunction(deps=deps)
    client = _FakeFFClient()
    fn._http_client = client
    result = _run(fn.execute(days=30))

    assert result.data["status"] == "ok"
    assert result.data["source_mode"] == "forex_factory"
    assert result.sources == ["forex_factory"]
    rows = result.data["rows"]
    assert len(rows) == 2
    us_row = next(r for r in rows if r["country"] == "US")
    assert us_row["event"] == "CPI y/y"
    assert us_row["importance"] == "high"  # lower-cased from "High"
    assert us_row["forecast"] == 3.2  # "3.2%" parsed by the normalizer
    assert us_row["actual"] is None  # blank print stays blank
    assert result.metadata["live"] is True
    assert str(result.metadata["data_mode"]).startswith("live")
    as_of = result.data["as_of"]
    assert isinstance(as_of, str) and datetime.fromisoformat(as_of)


def test_forex_factory_cache_serves_second_call_without_refetch():
    deps = FunctionDeps()
    fn = eco_mod.ECOFunction(deps=deps)
    client = _FakeFFClient()
    fn._http_client = client
    first = _run(fn.execute(days=30))
    second = _run(fn.execute(days=30))
    assert client.calls == 1, "TTL cache must serve the second call"
    assert first.data["rows"] == second.data["rows"]


def test_keyed_provider_success_wins_over_forex_factory():
    """When TradingEconomics returns rows, ForexFactory is not consulted."""
    deps = FunctionDeps(tradingeconomics=_LiveTE(), finnhub=_FailingProvider())
    fn = eco_mod.ECOFunction(deps=deps)
    client = _FakeFFClient()
    fn._http_client = client
    result = _run(fn.execute(country="US", days=30))

    assert result.data["source_mode"] == "tradingeconomics"
    assert result.sources == ["tradingeconomics"]
    assert client.calls == 0, "keyed success must short-circuit the keyless fetch"
    warning_blob = " ".join(result.warnings).lower()
    assert "örnek" not in warning_blob and "sentetik" not in warning_blob
    assert any(row.get("actual") == 3.2 for row in result.data["events"])


def test_reference_true_serves_labelled_template_only():
    """``reference=true`` is the explicit opt-in to the illustrative
    schedule; its rows still never fabricate actual prints."""
    deps = FunctionDeps(tradingeconomics=_FailingProvider(), finnhub=_FailingProvider())
    fn = eco_mod.ECOFunction(deps=deps)
    fn._http_client = _FakeFFClient(boom=True)
    result = _run(fn.execute(country="US", days=30, reference=True))

    assert result.data["status"] == "ok"
    assert result.data["source_mode"] == "calendar_feed_model"
    assert result.sources == ["calendar_feed_model"]
    assert result.metadata["live"] is False
    assert result.metadata["data_mode"] == "modeled"
    assert result.data["events"], "template should produce schedule rows"
    assert all(row.get("actual") is None for row in result.data["events"])
    assert all(row.get("surprise") is None for row in result.data["events"])


def test_synthetic_model_actuals_are_nulled_at_source():
    """The hardcoded calendar template itself must not carry fabricated
    actual prints (the honesty fix at the data source)."""
    events = eco_mod._calendar_feed_model("US", None)
    assert events, "template should produce rows"
    assert all(item["actual"] is None for item in events)
    assert any(item["forecast"] is not None for item in events)


def test_ff_row_normalizer_shape():
    rows = eco_mod._normalize_ff_rows([
        {"title": "Non Farm Payrolls", "country": "USD", "date": "2026-09-04T08:30:00-04:00",
         "impact": "High", "forecast": "180K", "actual": "", "previous": "175K"},
        {"title": "", "country": "USD", "date": "", "impact": "Low"},  # dropped: no title
        "not-a-dict",
    ])
    assert len(rows) == 1
    row = rows[0]
    assert row["country"] == "US"  # currency mapped to canonical token
    assert row["importance"] == "high"
    assert row["forecast"] == "180K"  # left raw; _normalize_events parses it
