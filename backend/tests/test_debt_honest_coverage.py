"""DEBT honesty regressions: stale observations, silent drops, false zeros, avg basis.

The World Bank client is replaced with a fake; no network is used.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from showme.engine.functions.bond import _stubs


def _fresh_year() -> str:
    return str(datetime.now(timezone.utc).year - 1)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeWorldBankClient:
    def __init__(self, series_by_iso3, failing=()):
        self._series = series_by_iso3
        self._failing = set(failing)
        self.requested: list[str] = []

    async def get(self, url, params=None, timeout=None):
        iso3 = url.split("/country/", 1)[1].split("/", 1)[0]
        self.requested.append(iso3)
        if iso3 in self._failing:
            raise ConnectionError("simulated upstream failure")
        series = self._series.get(iso3, [])
        return _FakeResponse([{"page": 1, "pages": 1, "per_page": 60, "total": len(series)}, series])


def _debt(monkeypatch, client):
    async def _get_client():
        return client

    monkeypatch.setattr(_stubs, "get_client", _get_client)
    return _stubs.DEBTFunction()


def _run(coro):
    return asyncio.run(coro)


def test_debt_stale_observation_is_excluded_from_rows_and_average(monkeypatch):
    # Germany's only non-null observation is from 1990: it must not be a
    # current value, must not feed the average, and must be named.
    client = _FakeWorldBankClient({
        "USA": [{"date": _fresh_year(), "value": 120.0}],
        "DEU": [{"date": "1990", "value": 20.85}],
        "GBR": [{"date": _fresh_year(), "value": 100.0}],
    })
    fn = _debt(monkeypatch, client)
    res = _run(fn.execute(countries="US,DE,GB"))
    d = res.data
    assert d["status"] == "ok"
    assert sorted(r["country"] for r in d["rows"]) == ["GB", "US"]
    assert d["summary"]["avg_debt_to_gdp"] == 110.0
    assert any("DE" in w and "1990" in w for w in res.warnings)
    assert any(e["country"] == "DE" for e in d["summary"]["excluded_countries"])


def test_debt_countries_without_observation_are_named_not_silently_dropped(monkeypatch):
    client = _FakeWorldBankClient({
        "USA": [{"date": _fresh_year(), "value": 120.0}],
        "JPN": [],
        "FRA": [{"date": _fresh_year(), "value": None}],
    })
    fn = _debt(monkeypatch, client)
    res = _run(fn.execute(countries="US,JP,FR"))
    d = res.data
    assert d["status"] == "ok"
    assert [r["country"] for r in d["rows"]] == ["US"]
    excluded = {e["country"] for e in d["summary"]["excluded_countries"]}
    assert excluded == {"JP", "FR"}
    assert any("JP" in w for w in res.warnings)
    assert any("FR" in w for w in res.warnings)


def test_debt_all_stale_is_an_empty_state_with_reason(monkeypatch):
    client = _FakeWorldBankClient({"DEU": [{"date": "1990", "value": 20.85}]})
    fn = _debt(monkeypatch, client)
    res = _run(fn.execute(countries="DE"))
    assert res.data["status"] == "empty"
    assert res.data["rows"] == []
    assert res.data["reason"]
    assert res.data["summary"]["avg_debt_to_gdp"] is None


def test_debt_unlisted_country_local_currency_share_is_null_not_zero(monkeypatch):
    client = _FakeWorldBankClient({"KOR": [{"date": _fresh_year(), "value": 55.0}]})
    fn = _debt(monkeypatch, client)
    res = _run(fn.execute(countries="KR"))
    assert res.data["status"] == "ok"
    row = res.data["rows"][0]
    assert row["country"] == "KR"
    assert row["local_currency_share"] is None


def test_debt_listed_country_local_currency_share_is_null_no_constant(monkeypatch):
    # DEBT#3: the former hard-coded reference (US 99.0) is gone; no sourced value exists.
    client = _FakeWorldBankClient({"USA": [{"date": _fresh_year(), "value": 120.0}]})
    fn = _debt(monkeypatch, client)
    res = _run(fn.execute(countries="US"))
    assert res.data["rows"][0]["local_currency_share"] is None


def test_debt_average_basis_is_labelled_unweighted(monkeypatch):
    client = _FakeWorldBankClient({
        "USA": [{"date": _fresh_year(), "value": 120.0}],
        "DEU": [{"date": _fresh_year(), "value": 60.0}],
    })
    fn = _debt(monkeypatch, client)
    res = _run(fn.execute(countries="US,DE"))
    basis = res.data["summary"].get("avg_debt_to_gdp_basis", "")
    assert "unweighted" in basis.lower()
    assert res.data["summary"]["avg_debt_to_gdp"] == 90.0
