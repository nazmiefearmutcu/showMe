"""ESG provenance and data-policy honesty (ESG#1-RQ, ESG#2, ESG#3, ESG#4).

* A missing EFTS ``hits.total.value`` must surface as provider_unavailable with a
  reason, never as a silent zero count (data policy: no invented values).
* The SEC proxy is a live EDGAR query, so its data_mode must not say cached_snapshot.
* Yahoo sustainability rows must not be labelled live_yfinance (Yahoo's ESG frame
  is a periodically refreshed snapshot, not a live feed).
* The field dictionary must not describe the proxy total as a vendor risk score.
"""
from __future__ import annotations

import asyncio

import showme.providers._http as http_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.esg import (
    ESGFunction,
    _FIELD_DICTIONARY,
    _build_rows_from_sustainability,
)


def _run(coro):
    return asyncio.run(coro)


def _instrument() -> Instrument:
    return Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _Resp:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _Client:
    """Per-query payloads keyed by which pillar term the query contains."""

    def __init__(self, payload_for):
        self._payload_for = payload_for

    async def get(self, url, params=None, headers=None, timeout=None):
        return _Resp(self._payload_for(params["q"]))


def _total(value: int) -> dict:
    return {"hits": {"total": {"value": value, "relation": "eq"}, "hits": []}}


def _patch(monkeypatch, payload_for) -> None:
    client = _Client(payload_for)

    async def _get_client():
        return client

    monkeypatch.setattr(http_mod, "get_client", _get_client)


# ---- ESG#1-RQ: missing EFTS total is an explicit unavailable state -------------


def test_missing_efts_total_is_not_reported_as_zero(monkeypatch):
    # The "any" query answers without hits.total.value. The old code turned that
    # into a 0 count and reported status ok with totalEsg 0.
    def payload_for(q):
        if "climate change" in q and "diversity" in q:
            return {"hits": {"hits": []}}  # no total block at all
        return _total(4)

    _patch(monkeypatch, payload_for)
    result = _run(ESGFunction(FunctionDeps()).execute(instrument=_instrument()))
    data = result.data
    assert data["status"] == "provider_unavailable", data
    assert data["totalEsg"] is None
    assert data["environmentScore"] is None
    assert data["rows"] == []
    assert any("hits.total" in e for e in result.metadata.get("provider_errors", [])), result.metadata


def test_zero_efts_total_is_a_real_zero_not_an_error(monkeypatch):
    # A genuine zero-hit answer is data, not a missing value.
    _patch(monkeypatch, lambda q: _total(0))
    result = _run(ESGFunction(FunctionDeps()).execute(instrument=_instrument()))
    assert result.data["status"] == "empty"


# ---- ESG#3: the proxy is a live EDGAR query ----------------------------------


def test_proxy_data_mode_is_live_not_cached_snapshot(monkeypatch):
    def payload_for(q):
        if "climate change" in q and "diversity" in q:
            return _total(9)
        if "climate change" in q:
            return _total(3)
        if "diversity" in q:
            return _total(5)
        return _total(7)

    _patch(monkeypatch, payload_for)
    result = _run(ESGFunction(FunctionDeps()).execute(instrument=_instrument()))
    data = result.data
    assert data["status"] == "ok"
    assert data["data_mode"] == "live_official", data["data_mode"]
    assert data["data_mode"] != "cached_snapshot"
    assert result.sources == ["sec_edgar"]


# ---- ESG#4: Yahoo rows are not labelled live -----------------------------------


def test_yahoo_rows_are_not_labelled_live_yfinance():
    rows = _build_rows_from_sustainability({"totalEsg": 16.84, "environmentScore": 0.6})
    assert rows is not None
    assert all(r["source_mode"] != "live_yfinance" for r in rows)
    assert all(r["source_mode"] == "delayed_reference" for r in rows)


# ---- ESG#2: dictionary describes the proxy total honestly --------------------


def test_field_dictionary_total_does_not_call_proxy_count_a_risk_score():
    text = _FIELD_DICTIONARY["totalEsg"].lower()
    assert "filing" in text, text
    assert "proxy" in text, text
    assert "vendor" in _FIELD_DICTIONARY["totalEsg"].lower()


def test_proxy_total_is_unique_filing_count_not_sum_of_pillars(monkeypatch):
    # Pillar buckets overlap: one filing can match several buckets. Pillar counts
    # 3 + 5 + 7 = 15, but the unique filings matching any term are 9.
    def payload_for(q):
        if "climate change" in q and "diversity" in q:
            return _total(9)
        if "climate change" in q:
            return _total(3)
        if "diversity" in q:
            return _total(5)
        return _total(7)

    _patch(monkeypatch, payload_for)
    result = _run(ESGFunction(FunctionDeps()).execute(instrument=_instrument()))
    data = result.data
    assert data["status"] == "ok"
    pillar_sum = data["environmentScore"] + data["socialScore"] + data["governanceScore"]
    assert pillar_sum == 15
    assert data["totalEsg"] == 9, data["totalEsg"]
    assert data["totalEsg"] != pillar_sum


def test_manifest_total_esg_description_does_not_call_proxy_count_a_risk_score():
    from showme.manifest.seeds.esg_seed import esg as esg_manifest

    description = esg_manifest.field_dict["totalEsg"].description.lower()
    assert "risk / opportunity" not in description, description
    assert "filing" in description, description
    assert "proxy" in description, description


def test_manifest_data_mode_description_lists_live_official():
    from showme.manifest.seeds.esg_seed import esg as esg_manifest

    description = esg_manifest.field_dict["data_mode"].description
    assert "live_official" in description, description
    assert "delayed_reference" not in description, description


# ---- ESG#2: the manifest methodology describes the real provenance paths ------


def test_manifest_methodology_does_not_claim_a_paid_vendor_is_required():
    # The SEC EDGAR proxy returns data_mode=live_official with no vendor plugin, so
    # the methodology must not say ESG needs a paid vendor or returns unavailable
    # without one.
    from showme.manifest.seeds.esg_seed import esg as esg_manifest

    text = esg_manifest.methodology.lower()
    assert "requires a paid vendor" not in text, text
    assert "none is bundled" not in text, text
    assert "live_official" in text, text
    assert "sec edgar" in text, text
    assert "filing" in text, text
