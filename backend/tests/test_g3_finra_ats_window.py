"""DARK#1 / DPF#1 — FINRA ATS weekly pulls must return the NEWEST weeks.

The FINRA weeklySummary endpoint returns rows oldest-first. A bare ``limit``
(200 for DARK, weeks*4 for DPF) therefore hands the handler the oldest
history only, DARK's stale guard fires, and DPF reports 2022-2023 weeks as
current. These tests drive ``execute()`` through a fake FINRA that mirrors
the live semantics (oldest-first, compareFilters, dateRangeFilters, offset,
limit) so no network is used.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.equity.finra_adapter import FINRAAdapter
from showme.engine.functions.equity import dpf as dpf_mod
from showme.engine.functions.equity.dark import DARKFunction
from showme.engine.functions.equity.dpf import DPFFunction


def _run(coro):
    return asyncio.run(coro)


def _today():
    return datetime.now(timezone.utc).date()


def _latest_monday():
    """Monday two weeks before today: the newest week FINRA would have published."""
    t = _today()
    return t - timedelta(days=t.weekday()) - timedelta(days=14)


def _dataset(symbol: str = "AAPL", weeks_total: int = 260) -> list[dict[str, Any]]:
    """~5 years of weekly ATS rows, sorted OLDEST-FIRST like the live endpoint."""
    latest = _latest_monday()
    rows = []
    for i in range(weeks_total):
        wk = latest - timedelta(weeks=i)
        rows.append({
            "weekStartDate": wk.isoformat(),
            "issueSymbolIdentifier": symbol,
            "summaryTypeCode": "ATS_W_SMBL",
            "tierIdentifier": "T1",
            "totalWeeklyShareQuantity": 1_000_000 + i,
            "totalWeeklyTradeCount": 10_000 + i,
        })
    rows.sort(key=lambda r: r["weekStartDate"])
    return rows


class _Resp:
    status_code = 200

    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def raise_for_status(self) -> None:
        return None

    def json(self) -> list[dict[str, Any]]:
        return self._rows


class FakeFinra:
    """Mirrors the live weeklySummary query semantics."""

    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows
        self.bodies: list[dict[str, Any]] = []

    async def post(self, url, json=None, headers=None, timeout=None, **kw):  # noqa: A002
        body = json or {}
        self.bodies.append(body)
        rows = self.rows
        for f in body.get("compareFilters", []):
            rows = [r for r in rows if r.get(f["fieldName"]) == f["fieldValue"]]
        for f in body.get("dateRangeFilters", []):
            rows = [r for r in rows if f["startDate"] <= r[f["fieldName"]] <= f["endDate"]]
        offset = int(body.get("offset", 0) or 0)
        limit = int(body.get("limit", 1000) or 1000)
        return _Resp(rows[offset: offset + limit])


def _patch_direct_finra(monkeypatch, fake: FakeFinra) -> None:
    async def _get_client():
        return fake

    monkeypatch.setattr("showme.providers._http.get_client", _get_client)


def _wire_adapter(fake: FakeFinra) -> FINRAAdapter:
    adapter = FINRAAdapter({})

    async def _client():
        return fake

    async def _no_auth() -> None:
        return None

    adapter._client_ = _client  # type: ignore[assignment]
    adapter._maybe_auth = _no_auth  # type: ignore[assignment]
    return adapter


async def _no_yfinance(*_args, **_kwargs):
    return {}


def test_dark_direct_path_returns_newest_finra_week(monkeypatch) -> None:
    fake = FakeFinra(_dataset())
    _patch_direct_finra(monkeypatch, fake)
    monkeypatch.setattr(DARKFunction, "_weekly_total_volume", lambda self, sym: _no_yfinance())

    result = _run(DARKFunction(deps=FunctionDeps()).execute(symbol="AAPL", weeks=8))
    data = result.data

    assert data["status"] == "ok", data.get("reason")
    assert data["summary"]["latest_week"] == _latest_monday().isoformat()
    assert len(data["by_week"]) == 8
    assert fake.bodies and "dateRangeFilters" in fake.bodies[0], "request must bound the date window"


def test_dpf_wired_adapter_returns_newest_weeks_not_2023(monkeypatch) -> None:
    fake = FakeFinra(_dataset())
    adapter = _wire_adapter(fake)
    monkeypatch.setattr(dpf_mod, "_weekly_total_volume", _no_yfinance)

    result = _run(
        DPFFunction(deps=FunctionDeps(finra=adapter)).execute(
            instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
            weeks=12,
        )
    )
    data = result.data

    assert data["status"] == "ok", data.get("reason")
    weeks = [r["weekStartDate"] for r in data["weekly"]]
    assert weeks[0] == _latest_monday().isoformat()
    assert len(weeks) == 12
    assert weeks == sorted(weeks, reverse=True)


class _BoomFinra:
    async def ats_weekly(self, symbol=None, limit=200):  # noqa: ANN001
        raise RuntimeError("finra down")


def test_dpf_unavailable_path_ships_no_synthetic_volumes(monkeypatch) -> None:
    """When FINRA cannot be read, DPF must not invent ATS volume rows."""
    monkeypatch.setattr(dpf_mod, "_weekly_total_volume", _no_yfinance)
    result = _run(
        DPFFunction(deps=FunctionDeps(finra=_BoomFinra())).execute(
            instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
            weeks=12,
        )
    )
    data = result.data

    assert data["status"] == "provider_unavailable"
    assert data["weekly"] == [], "no placeholder ATS volumes on the outage path"
    assert data["rows"] == [] and data["history"] == []
    assert data.get("next_actions")


def test_dpf_empty_feed_ships_no_synthetic_volumes(monkeypatch) -> None:
    """A FINRA response with no rows for the symbol is 'empty', not a model."""
    monkeypatch.setattr(dpf_mod, "_weekly_total_volume", _no_yfinance)
    adapter = _wire_adapter(FakeFinra([]))
    result = _run(
        DPFFunction(deps=FunctionDeps(finra=adapter)).execute(
            instrument=Instrument(symbol="ZZZZ", asset_class=AssetClass.EQUITY),
            weeks=12,
        )
    )
    data = result.data

    assert data["status"] in {"provider_unavailable", "empty"}
    assert data["weekly"] == []
    assert not any(
        r.get("source_mode") == "labelled_current_shape_model" for r in data["weekly"]
    )


def test_dark_venue_label_is_not_a_tier_identifier(monkeypatch) -> None:
    """ATS_W_SMBL rows carry no MPID; the aggregate must not be labelled by tier."""
    fake = FakeFinra(_dataset())
    _patch_direct_finra(monkeypatch, fake)
    monkeypatch.setattr(DARKFunction, "_weekly_total_volume", lambda self, sym: _no_yfinance())

    result = _run(DARKFunction(deps=FunctionDeps()).execute(symbol="AAPL", weeks=8))
    data = result.data

    assert data["status"] == "ok", data.get("reason")
    venues = {row["venue"] for row in data["venues"]}
    assert venues == {"ALL_ATS"}, venues


def test_dpf_empty_finra_response_lists_no_provider(monkeypatch) -> None:
    """DPF#1: FINRA returned zero rows, so FINRA supplied no data to list."""
    monkeypatch.setattr(dpf_mod, "_weekly_total_volume", _no_yfinance)
    adapter = _wire_adapter(FakeFinra([]))
    result = _run(
        DPFFunction(deps=FunctionDeps(finra=adapter)).execute(
            instrument=Instrument(symbol="ZZZZ", asset_class=AssetClass.EQUITY),
            weeks=12,
        )
    )

    assert result.data["status"] in {"provider_unavailable", "empty"}
    assert result.sources == [], result.sources


def test_dpf_outage_lists_no_provider(monkeypatch) -> None:
    """DPF#1: a FINRA exception supplied no data, so sources stays empty."""
    monkeypatch.setattr(dpf_mod, "_weekly_total_volume", _no_yfinance)
    result = _run(
        DPFFunction(deps=FunctionDeps(finra=_BoomFinra())).execute(
            instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
            weeks=12,
        )
    )

    assert result.data["status"] == "provider_unavailable"
    assert result.sources == [], result.sources


def test_dpf_timeout_lists_no_provider(monkeypatch) -> None:
    """DPF#1: the timeout path never received FINRA rows, so sources is empty."""

    async def _slow(self, instrument, **params):  # noqa: ANN001
        raise asyncio.TimeoutError("dpf slow")

    monkeypatch.setattr(DPFFunction, "_execute_inner", _slow)
    result = _run(
        DPFFunction(deps=FunctionDeps()).execute(
            instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
        )
    )

    assert result.data["status"] == "provider_unavailable"
    assert result.sources == [], result.sources


def _weekly_volume_for_latest(value: float) -> Any:
    async def _vol(self, sym):  # noqa: ANN001
        return {_latest_monday().isoformat(): value}

    return _vol


def test_dark_sources_omit_yfinance_when_it_supplied_no_volume(monkeypatch) -> None:
    """DARK#1: yfinance returned {} (no total volume), so it must not be listed."""
    fake = FakeFinra(_dataset())
    _patch_direct_finra(monkeypatch, fake)
    monkeypatch.setattr(DARKFunction, "_weekly_total_volume", lambda self, sym: _no_yfinance())

    result = _run(DARKFunction(deps=FunctionDeps()).execute(symbol="AAPL", weeks=8))

    assert result.data["status"] == "ok", result.data.get("reason")
    assert result.data["by_week"][0]["dark_pool_pct"] is None
    assert result.sources == ["finra"], result.sources


def test_dark_sources_list_yfinance_when_it_supplied_volume(monkeypatch) -> None:
    """DARK#1: yfinance volume is what produced dark_pool_pct, so it is listed."""
    fake = FakeFinra(_dataset())
    _patch_direct_finra(monkeypatch, fake)
    monkeypatch.setattr(DARKFunction, "_weekly_total_volume", _weekly_volume_for_latest(5e9))

    result = _run(DARKFunction(deps=FunctionDeps()).execute(symbol="AAPL", weeks=8))

    assert result.data["by_week"][0]["dark_pool_pct"] is not None
    assert result.sources == ["finra", "yfinance"], result.sources


def test_dark_empty_finra_lists_no_provider(monkeypatch) -> None:
    """DARK#1: FINRA returned zero rows, so FINRA supplied no data to list."""
    _patch_direct_finra(monkeypatch, FakeFinra([]))
    monkeypatch.setattr(DARKFunction, "_weekly_total_volume", _weekly_volume_for_latest(5e9))

    result = _run(DARKFunction(deps=FunctionDeps()).execute(symbol="ZZZZ", weeks=8))

    assert result.data["status"] == "provider_unavailable"
    assert result.sources == [], result.sources


def test_dark_finra_outage_lists_no_provider(monkeypatch) -> None:
    """DARK#1: a FINRA exception supplied no data, so sources stays empty."""

    async def _boom(self, symbol, weeks=26):  # noqa: ANN001
        raise RuntimeError("finra down")

    monkeypatch.setattr(DARKFunction, "_fetch_finra_ats", _boom)
    monkeypatch.setattr(DARKFunction, "_weekly_total_volume", _no_yfinance_method)

    result = _run(DARKFunction(deps=FunctionDeps()).execute(symbol="AAPL", weeks=8))

    assert result.data["status"] == "provider_unavailable"
    assert result.sources == [], result.sources


def test_dark_timeout_lists_no_provider(monkeypatch) -> None:
    """DARK#1: the timeout path never received FINRA rows, so sources is empty."""

    async def _slow(self, instrument, **params):  # noqa: ANN001
        raise asyncio.TimeoutError("dark slow")

    monkeypatch.setattr(DARKFunction, "_execute_inner", _slow)
    result = _run(DARKFunction(deps=FunctionDeps()).execute(symbol="AAPL"))

    assert result.data["status"] == "provider_unavailable"
    assert result.sources == [], result.sources


async def _no_yfinance_method(self, sym):  # noqa: ANN001
    return {}
