"""DEBT#3 regression: local_currency_share must never be a hard-coded constant.

The World Bank feed has no keyless local-currency series, so the handler must
return null for every row and the seed must not attribute a constant table to
the World Bank. The World Bank client is a fake; no network is used.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from showme.engine.functions.bond import _stubs
from showme.manifest import REGISTRY, load_seeds


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeWorldBankClient:
    def __init__(self, series_by_iso3):
        self._series = series_by_iso3

    async def get(self, url, params=None, timeout=None):
        iso3 = url.split("/country/", 1)[1].split("/", 1)[0]
        series = self._series.get(iso3, [])
        return _FakeResponse([{"page": 1, "pages": 1, "per_page": 60, "total": len(series)}, series])


def _fresh_year() -> str:
    return str(datetime.now(timezone.utc).year - 1)


def _run(monkeypatch, series, **params):
    client = _FakeWorldBankClient(series)

    async def _get_client():
        return client

    monkeypatch.setattr(_stubs, "get_client", _get_client)
    return asyncio.run(_stubs.DEBTFunction().execute(**params))


def test_no_hardcoded_local_currency_table_remains():
    assert not hasattr(_stubs.DEBTFunction, "_LOCAL_CCY_REF")


def test_listed_country_local_currency_share_is_null_not_a_constant(monkeypatch):
    res = _run(monkeypatch, {"USA": [{"date": _fresh_year(), "value": 120.0}]}, countries="US")
    assert res.data["status"] == "ok"
    assert res.data["rows"][0]["local_currency_share"] is None


def test_every_row_local_currency_share_is_null(monkeypatch):
    series = {
        "USA": [{"date": _fresh_year(), "value": 120.0}],
        "DEU": [{"date": _fresh_year(), "value": 60.0}],
        "KOR": [{"date": _fresh_year(), "value": 55.0}],
    }
    res = _run(monkeypatch, series, countries="US,DE,KR")
    assert len(res.data["rows"]) == 3
    assert all(r["local_currency_share"] is None for r in res.data["rows"])


def test_warnings_do_not_call_local_currency_a_reference_table(monkeypatch):
    res = _run(monkeypatch, {"USA": [{"date": _fresh_year(), "value": 120.0}]}, countries="US")
    text = " ".join(res.warnings).lower()
    assert "reference table" not in text
    assert "hard-coded" not in text


def test_seed_does_not_attribute_local_currency_to_worldbank():
    load_seeds()
    entry = REGISTRY.get("DEBT")
    source = entry.field_dict["rows[].local_currency_share"].source
    assert source not in ("worldbank", "worldbank_reference")
    assert "hard-coded" not in entry.methodology.lower()
    assert "reference table" not in entry.methodology.lower()
    assert "hard-coded" not in entry.field_dict["rows[].local_currency_share"].description.lower()
