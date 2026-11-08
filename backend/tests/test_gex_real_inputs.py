"""GEX real-input and honesty regressions (wc1-g06).

Covers the honest-state contract for the GEX function:

* no spot and no live quote -> explicit non-ok state, never a spot of 100;
* no live options chain -> provider_unavailable with no modeled strike grid;
* live payload discloses as_of, data mode, iv/dealer assumptions and r/q;
* time to expiry uses the exchange close for every expiry (GEX#4);
* the manifest documents the sign convention and provider the code really uses.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pandas as pd

from showme.engine.core.base_data_source import DataKind
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.derivative.gex import GEXFunction
from showme.engine.services.gamma_exposure import time_to_expiry_years


def _run(coro):
    return asyncio.run(coro)


class _QuoteFails:
    async def fetch(self, request):  # noqa: ANN001
        raise RuntimeError("network down")


class _Quote:
    def __init__(self, last: float) -> None:
        self.last = last


class _QuoteOnly:
    async def fetch(self, request):  # noqa: ANN001
        if request.kind == DataKind.QUOTE:
            return _Quote(610.0)
        raise RuntimeError("no chain in this stub")


# --------------------------------------------------------------------------- #
# T10 placeholder_value: no spot is invented
# --------------------------------------------------------------------------- #
def test_no_provider_returns_provider_unavailable_not_spot_100() -> None:
    fn = GEXFunction(deps=FunctionDeps(yfinance=None))
    result = _run(fn.execute(symbol="SPY", live_options=True))
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert data["spot"] is None
    assert data["rows"] == []
    assert data["next_actions"]


def test_no_spot_without_live_quote_is_needs_input_not_spot_100() -> None:
    fn = GEXFunction(deps=FunctionDeps(yfinance=_EmptyChainYf()))
    result = _run(fn.execute(symbol="SPY", live_options=True))
    data = result.data
    assert data["status"] == "needs_input"
    assert data["spot"] is None
    assert data["rows"] == []
    assert "spot" in data["reason"].lower()
    assert data["next_actions"]


def test_live_quote_failure_returns_provider_unavailable_not_spot_100() -> None:
    fn = GEXFunction(deps=FunctionDeps(yfinance=_QuoteFails()))
    result = _run(fn.execute(symbol="SPY", live=True, live_options=True))
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert data["spot"] is None
    assert data["rows"] == []


def test_explicit_spot_wins_over_live_quote() -> None:
    fn = GEXFunction(deps=FunctionDeps(yfinance=_QuoteOnly()))
    result = _run(fn.execute(symbol="SPY", spot=500.0, live=True, live_options=False))
    assert result.data["spot"] == 500.0
    assert result.data["model_inputs"]["spot_source"] == "explicit_input"


# --------------------------------------------------------------------------- #
# GEX#5: no fabricated 3-strike grid
# --------------------------------------------------------------------------- #
def test_no_live_options_is_needs_input_without_modeled_grid() -> None:
    fn = GEXFunction(deps=FunctionDeps(yfinance=None))
    result = _run(fn.execute(symbol="SPY", spot=100.0))
    data = result.data
    assert data["status"] == "needs_input"
    assert data["rows"] == []
    assert data["summary"]["synthetic"] is False
    assert data["summary"]["net_gex"] is None


class _EmptyChainYf:
    async def fetch(self, request):  # noqa: ANN001
        if request.kind == DataKind.OPTIONS_CHAIN:
            if request.extra.get("expiry") is None:
                return {"expiries": ["2026-07-17"]}
            return {"calls": pd.DataFrame(), "puts": pd.DataFrame()}
        return None


def test_empty_live_chain_is_provider_unavailable_not_synthetic_ok() -> None:
    fn = GEXFunction(deps=FunctionDeps(yfinance=_EmptyChainYf()))
    result = _run(fn.execute(symbol="SPY", spot=100.0, live_options=True))
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert data["rows"] == []
    assert data["summary"]["n_strikes"] == 0
    assert "no live" in data["reason"].lower() or "no option" in data["reason"].lower()


# --------------------------------------------------------------------------- #
# GEX#6 / GEX#3: payload discloses as_of, modes, assumptions and r / q
# --------------------------------------------------------------------------- #
class _StampedChainYf:
    """Live chain whose option rows carry a last-trade stamp."""

    def __init__(self, last_trade: str) -> None:
        self._stamp = pd.Timestamp(last_trade, tz="UTC")

    async def fetch(self, request):  # noqa: ANN001
        if request.kind != DataKind.OPTIONS_CHAIN:
            return None
        if request.extra.get("expiry") is None:
            return {"expiries": ["2026-11-09"]}
        calls = pd.DataFrame([
            {"strike": 100.0, "openInterest": 1000, "impliedVolatility": 0.3,
             "lastTradeDate": self._stamp},
            {"strike": 105.0, "openInterest": 500, "impliedVolatility": 0.3,
             "lastTradeDate": self._stamp},
        ])
        puts = pd.DataFrame([
            {"strike": 95.0, "openInterest": 2000, "impliedVolatility": 0.3,
             "lastTradeDate": self._stamp},
        ])
        return {"calls": calls, "puts": puts}


def test_live_payload_discloses_as_of_mode_assumptions_and_rates() -> None:
    fn = GEXFunction(deps=FunctionDeps(yfinance=_StampedChainYf("2026-11-06 20:59:00")))
    result = _run(fn.execute(symbol="SPY", spot=100.0, live_options=True))
    data = result.data
    assert data["status"] == "ok"
    assert data["as_of"].startswith("2026-11-06T20:59")
    # Sunday run against a Friday-stamped chain: must not claim live.
    assert data["data_mode"] == "last_session_yfinance"
    assert data["iv_source"] == "market"
    assert data["dealer_assumption"] == "short_calls_long_puts"
    assert data["underlying"] == "SPY"
    assert data["model_inputs"]["risk_free"] == 0.045
    assert data["model_inputs"]["dividend_yield"] == 0.015
    assert data["model_inputs"]["spot_source"] == "explicit_input"


def test_live_payload_fresh_stamp_is_live_yfinance() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    fn = GEXFunction(deps=FunctionDeps(yfinance=_StampedChainYf(today)))
    result = _run(fn.execute(symbol="SPY", spot=100.0, live_options=True))
    assert result.data["data_mode"] == "live_yfinance"


# --------------------------------------------------------------------------- #
# GEX#3: manifest inputs are wired or rejected, not silently ignored
# --------------------------------------------------------------------------- #
def test_expiry_filter_selects_number_of_expiries() -> None:
    class _Many:
        async def fetch(self, request):  # noqa: ANN001
            if request.kind != DataKind.OPTIONS_CHAIN:
                return None
            if request.extra.get("expiry") is None:
                return {"expiries": ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-13"]}
            return {"calls": pd.DataFrame([{"strike": 100.0, "openInterest": 10,
                                            "impliedVolatility": 0.3}]),
                    "puts": pd.DataFrame()}

    fn = GEXFunction(deps=FunctionDeps(yfinance=_Many()))
    one = _run(fn.execute(symbol="SPY", spot=100.0, live_options=True, expiry_filter="next_1"))
    assert one.data["expiries"] == ["2026-11-09"]
    three = _run(fn.execute(symbol="SPY", spot=100.0, live_options=True, expiry_filter="next_3"))
    assert three.data["expiries"] == ["2026-11-09", "2026-11-10", "2026-11-11"]


def test_unsupported_expiry_filter_is_input_error() -> None:
    fn = GEXFunction(deps=FunctionDeps(yfinance=_EmptyChainYf()))
    result = _run(fn.execute(symbol="SPY", spot=100.0, live_options=True,
                             expiry_filter="monthly_only"))
    assert result.data["status"] == "input_error"
    assert result.data["rows"] == []


def test_risk_free_and_dividend_inputs_are_used() -> None:
    fn = GEXFunction(deps=FunctionDeps(yfinance=_StampedChainYf("2026-11-06 20:59:00")))
    base = _run(fn.execute(symbol="SPY", spot=100.0, live_options=True))
    alt = _run(fn.execute(symbol="SPY", spot=100.0, live_options=True,
                          risk_free=0.10, dividend_yield=0.0))
    assert alt.data["model_inputs"]["risk_free"] == 0.10
    assert alt.data["model_inputs"]["dividend_yield"] == 0.0
    assert alt.data["summary"]["call_gex_total"] != base.data["summary"]["call_gex_total"]


# --------------------------------------------------------------------------- #
# GEX#4: time to expiry uses the exchange close for every expiry
# --------------------------------------------------------------------------- #
def test_future_expiry_time_includes_time_of_day_to_close() -> None:
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)  # Sunday noon UTC
    # Monday 2026-11-09 16:00 ET (EST, after DST ended) = 21:00 UTC.
    expected_seconds = (datetime(2026, 11, 9, 21, 0, tzinfo=timezone.utc) - now).total_seconds()
    assert time_to_expiry_years("2026-11-09", now) == expected_seconds / (365 * 86400)


def test_expiry_close_follows_daylight_saving_time() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    # 2026-07-17 16:00 EDT = 20:00 UTC.
    expected_seconds = (datetime(2026, 7, 17, 20, 0, tzinfo=timezone.utc) - now).total_seconds()
    assert time_to_expiry_years("2026-07-17", now) == expected_seconds / (365 * 86400)


# --------------------------------------------------------------------------- #
# GEX#7 / manifest honesty
# --------------------------------------------------------------------------- #
def test_handler_sign_convention_matches_manifest_text() -> None:
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    entry = REGISTRY.get("GEX")
    fn = GEXFunction(deps=FunctionDeps(yfinance=_StampedChainYf("2026-11-06 20:59:00")))
    data = _run(fn.execute(symbol="SPY", spot=100.0, live_options=True)).data
    # Dealers short calls -> negative call contribution; long puts -> positive.
    assert data["summary"]["call_gex_total"] < 0 < data["summary"]["put_gex_total"]
    signed = entry.field_dict["strikes[].signed_gex"].description
    assert "call_gex − put_gex" not in signed
    assert "negative" in signed.lower()
    assert "positive contribution → suppresses" not in entry.methodology


def test_manifest_provider_matches_code_path() -> None:
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    entry = REGISTRY.get("GEX")
    assert entry.provider_chain.primary == "yfinance"
    assert "cboe_options" not in [entry.provider_chain.primary, *entry.provider_chain.fallbacks]
