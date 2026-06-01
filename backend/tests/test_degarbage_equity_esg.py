"""Degarbage test for equity ESG (ESG).

Asserts the handler returns real keyless data (Yahoo sustainability or a SEC
text-mined proxy) and never the old gated "provider_unavailable / vendor needed"
stub as the happy path. Live-network assertions are guarded so the suite passes
cleanly offline.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.esg import (
    ESGFunction,
    _PROXY_METHODOLOGY,
    _YF_METHODOLOGY,
    _build_rows_from_sustainability,
    _coerce_float,
    _flatten_sustainability,
)

_OK_SET = {"ok", "provider_unavailable", "empty"}


def _run(coro):
    return asyncio.run(coro)


def _instrument(symbol: str = "AAPL") -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)


def test_esg_returns_real_or_graceful():
    fn = ESGFunction(deps=FunctionDeps())
    res = _run(fn.execute(instrument=_instrument("AAPL")))
    data = res.data

    assert data["status"] in _OK_SET
    assert "methodology" in data and data["methodology"]
    assert isinstance(data.get("rows"), list)
    assert isinstance(data.get("field_dictionary"), dict) and data["field_dictionary"]
    assert res.sources, "must name an honest provider"
    assert "esg_model" not in res.sources, "must not fall back to the canned model source"

    if data["status"] == "ok":
        assert data["rows"], "ok status must carry real rows"
        # ok rows must be real, not all-None placeholder pillars.
        scored = [r for r in data["rows"] if r.get("score") is not None]
        assert scored, "ok rows must contain at least one real numeric score"
        assert set(res.sources) & {"yfinance", "sec_edgar"}
        assert data["methodology"] in {_YF_METHODOLOGY, _PROXY_METHODOLOGY}
    else:
        # graceful path: honest provider naming + actionable guidance.
        assert set(res.sources) & {"yfinance", "sec_edgar"}
        assert data.get("next_actions")


def test_coerce_float():
    assert _coerce_float(16.84) == 16.84
    assert _coerce_float("7.4") == 7.4
    assert _coerce_float(None) is None
    assert _coerce_float("n/a") is None


def test_flatten_sustainability_unwraps_value():
    nested = {"Value": {"totalEsg": 16.8, "environmentScore": 0.6}}
    flat = _flatten_sustainability(nested)
    assert flat["totalEsg"] == 16.8
    assert _flatten_sustainability({"totalEsg": 5}) == {"totalEsg": 5}
    assert _flatten_sustainability(None) == {}


def test_build_rows_from_sustainability_maps_pillars():
    flat = {
        "totalEsg": 16.84,
        "environmentScore": 0.61,
        "socialScore": 7.42,
        "governanceScore": 8.81,
        "highestControversy": 3,
    }
    rows = _build_rows_from_sustainability(flat)
    assert rows is not None
    by_pillar = {r["pillar"]: r["score"] for r in rows}
    assert by_pillar["total"] == 16.84
    assert by_pillar["environment"] == 0.61
    assert by_pillar["social"] == 7.42
    assert by_pillar["governance"] == 8.81
    assert by_pillar["controversy"] == 3.0
    assert all(r["source_mode"] == "live_yfinance" for r in rows)


def test_build_rows_none_when_no_pillar_value():
    # controversy-only or empty must NOT count as a real ESG row set.
    assert _build_rows_from_sustainability({}) is None
    assert _build_rows_from_sustainability({"highestControversy": 2}) is None
    assert _build_rows_from_sustainability({"someOtherKey": 1}) is None
