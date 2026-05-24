"""Audit Q3 — stablecoin depeg detector in portfolio_aggregate.

If a held stable's USD spot deviates from 1.0 by more than 2%, the
aggregate `totals` must include the symbol in `stable_depeg_alert`.
"""
from __future__ import annotations

import pytest

import showme.portfolio_aggregate as pa
from showme.portfolio_aggregate import (
    STABLE_DEPEG_THRESHOLD,
    _compute_totals,
    detect_stablecoin_depegs,
    set_fx_rate_fetcher,
)


def _make_fetcher(by_symbol: dict[str, float]):
    async def fetcher(symbol: str):
        return by_symbol.get(symbol.upper())
    return fetcher


@pytest.mark.asyncio
async def test_depeg_detector_flags_below_peg():
    set_fx_rate_fetcher(_make_fetcher({"USDT": 0.93}))
    try:
        alerts = await detect_stablecoin_depegs(["USDT"])
        assert len(alerts) == 1
        assert alerts[0]["symbol"] == "USDT"
        assert alerts[0]["spot"] == 0.93
        assert alerts[0]["deviation_pct"] > 2.0
    finally:
        set_fx_rate_fetcher(None)


@pytest.mark.asyncio
async def test_depeg_detector_passes_pegged():
    set_fx_rate_fetcher(_make_fetcher({"USDC": 1.0005}))
    try:
        alerts = await detect_stablecoin_depegs(["USDC"])
        assert alerts == []
    finally:
        set_fx_rate_fetcher(None)


@pytest.mark.asyncio
async def test_depeg_detector_no_alert_on_provider_miss():
    set_fx_rate_fetcher(_make_fetcher({}))
    try:
        alerts = await detect_stablecoin_depegs(["USDT", "USDC"])
        # Provider unavailable → no fake depeg.
        assert alerts == []
    finally:
        set_fx_rate_fetcher(None)


@pytest.mark.asyncio
async def test_compute_totals_surfaces_depeg_alert_list():
    set_fx_rate_fetcher(_make_fetcher({"USDT": 0.94}))
    try:
        groups = [{
            "credential_id": "x",
            "exchange_id": "binance",
            "account_label": "main",
            "permissions": [],
            "account": {"currency": "USDT", "equity": 10_000.0},
            "positions": [],
            "orders": [],
            "error": None,
        }]
        totals = await _compute_totals(groups)
        assert "USDT" in totals["stable_depeg_alert"]
        assert len(totals["stable_depeg_detail"]) == 1
        assert totals["stable_depeg_detail"][0]["symbol"] == "USDT"
    finally:
        set_fx_rate_fetcher(None)


@pytest.mark.asyncio
async def test_threshold_constant_is_2pct():
    assert STABLE_DEPEG_THRESHOLD == pytest.approx(0.02)
