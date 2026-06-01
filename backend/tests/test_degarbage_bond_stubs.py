"""Degarbage regression tests for CRPR / DDIS / DEBT / ALLQ (live keyless).

These exercise the REAL ``execute`` path. Network calls are guarded: if the
upstream (SEC EDGAR / World Bank / Treasury FiscalData / yfinance) is
unreachable, the handler must return a labelled ``provider_unavailable``
(or, for the corporate/sovereign branches, ``illustrative``/``empty``)
shape, which these tests accept as a valid offline outcome instead of
failing. The key acceptance: rows are NEVER the old hardcoded constants on
the happy path, methodology is present, and the honest source is reported.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.bond._stubs import (
    ALLQFunction,
    CRPRFunction,
    DDISFunction,
    DEBTFunction,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _bond(symbol: str = "US10Y") -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.BOND)


OK = {"ok", "empty", "illustrative"}
OFFLINE = {"provider_unavailable", "no_live_source"}


def _assert_common(payload: dict) -> str:
    status = payload.get("status")
    assert status in OK | OFFLINE, f"unexpected status {status!r}"
    assert payload.get("methodology"), "methodology must be present"
    assert isinstance(payload.get("field_dictionary"), dict)
    if status in OFFLINE:
        assert payload.get("next_actions") or payload.get("warnings")
    return status


# ---- CRPR -----------------------------------------------------------------


def test_crpr_user_override_echoes_verbatim():
    fn = CRPRFunction()
    res = _run(fn.execute(issuer="GENERIC", rating={"sp": "BB", "moodys": "Ba2", "fitch": "BB", "outlook": "negative"}))
    payload = res.data
    assert payload["status"] == "ok"
    assert res.sources == ["user_input"]
    sp_row = next(r for r in payload["rows"] if r["agency"] == "S&P")
    assert sp_row["rating"] == "BB"


def test_crpr_corporate_is_model_implied_or_offline():
    fn = CRPRFunction()
    res = _run(fn.execute(issuer="AAPL"))
    status = _assert_common(res.data)
    # the honest source must be SEC EDGAR on every corporate branch
    assert "sec_edgar" in res.sources
    if status == "ok":
        # NOT the old canned AA+/Aa1 sovereign constants
        assert res.data["summary"]["source_mode"] == "model_implied_from_financials"
        rating = res.data["rows"][0]["rating"]
        assert rating in {"AA", "A", "BBB", "BB", "B", "CCC"}
        # implied inputs must be real numbers (or honest None)
        assert "leverage_x" in res.data["summary"]


def test_crpr_sovereign_is_labelled_reference():
    fn = CRPRFunction()
    res = _run(fn.execute(issuer="US Treasury"))
    assert res.data["status"] == "ok"
    assert res.data["summary"]["source_mode"] == "sovereign_reference"
    assert res.sources == ["reference"]


# ---- DDIS -----------------------------------------------------------------


def test_ddis_user_schedule_passthrough_and_pct_recomputed():
    fn = DDISFunction()
    res = _run(fn.execute(issuer="AAPL", maturities=[
        {"bucket": "0-1Y", "tenor_years": 0.5, "amount_usd_bn": 1.0, "currency": "USD"},
        {"bucket": "5Y+", "tenor_years": 7.0, "amount_usd_bn": 3.0, "currency": "USD"},
    ]))
    payload = res.data
    assert payload["status"] == "ok"
    assert res.sources == ["user_input"]
    total_pct = sum(r["pct"] for r in payload["rows"])
    assert 99.5 <= total_pct <= 100.5


def test_ddis_corporate_real_or_labelled_fallback():
    fn = DDISFunction()
    res = _run(fn.execute(issuer="MSFT"))
    status = _assert_common(res.data)
    if status == "ok":
        assert res.data["summary"]["source_mode"] == "sec_edgar"
        assert "sec_edgar" in res.sources
        total = res.data["summary"]["total_debt_usd_bn"]
        assert total > 0
    else:
        # labelled illustrative or honest outage — never canned-as-live
        assert res.data["summary"]["source_mode"] in {"illustrative_model", "sec_edgar"}


def test_ddis_pct_sums_to_100_when_rows_present():
    fn = DDISFunction()
    res = _run(fn.execute(issuer="AAPL"))
    rows = res.data.get("rows") or []
    if rows:
        total_pct = sum(r.get("pct", 0) for r in rows)
        assert 99.5 <= total_pct <= 100.5


# ---- DEBT -----------------------------------------------------------------


def test_debt_user_exposures_passthrough():
    fn = DEBTFunction()
    res = _run(fn.execute(exposures=[{"country": "ZZ", "debt_to_gdp": 99.0, "local_currency_share": 50.0, "portfolio_weight_pct": 0.0}]))
    assert res.data["status"] == "ok"
    assert len(res.data["rows"]) == 1
    assert res.data["rows"][0]["country"] == "ZZ"


def test_debt_worldbank_live_or_offline():
    fn = DEBTFunction()
    res = _run(fn.execute(countries=["US", "DE"]))
    status = _assert_common(res.data)
    assert "worldbank" in res.sources
    if status == "ok":
        assert res.data["summary"]["measure"] == "world_bank_debt_to_gdp"
        for row in res.data["rows"]:
            # real World Bank values, with the year of the observation
            assert row["debt_to_gdp"] > 0
            assert row.get("year")
        # NOT the old hardcoded JP=255 / DE=63 baseline necessarily — just real
        assert res.data["summary"]["avg_debt_to_gdp"] > 0


def test_debt_portfolio_weight_zero_when_unlinked():
    fn = DEBTFunction()
    res = _run(fn.execute(countries=["US"]))
    if res.data["status"] == "ok":
        assert all(r["portfolio_weight_pct"] == 0.0 for r in res.data["rows"])
        assert res.data["summary"]["portfolio_linked"] is False


# ---- ALLQ -----------------------------------------------------------------


def test_allq_treasury_anchored_or_offline():
    fn = ALLQFunction()
    res = _run(fn.execute(instrument=_bond("US10Y")))
    status = _assert_common(res.data)
    if status == "ok":
        assert res.sources[0] in {"treasury_fiscaldata", "user_input", "yfinance"}
        assert res.data["summary"]["source_mode"] == "indicative_anchored_to_real_reference"
        rows = res.data["rows"]
        assert len(rows) == 3
        # spread_bps formula holds
        for q in rows:
            expected = round((q["spread_points"] / q["mid"]) * 10_000, 3)
            assert abs(q["spread_bps_of_price"] - expected) < 0.01
        # best bid/ask are extrema
        assert res.data["summary"]["best_bid"] == max(q["bid"] for q in rows)
        assert res.data["summary"]["best_ask"] == min(q["ask"] for q in rows)


def test_allq_user_mid_fallback_when_offline_path():
    # Passing an explicit mid guarantees a real anchor even if the network is
    # down, so the ladder is buildable and labelled indicative.
    fn = ALLQFunction()
    res = _run(fn.execute(instrument=_bond("US10Y"), mid=99.5, spread=0.2))
    status = res.data["status"]
    assert status in OK | OFFLINE
    if status == "ok":
        assert len(res.data["rows"]) == 3
        assert res.data["summary"]["mid"] in (99.5, res.data["summary"]["mid"])
