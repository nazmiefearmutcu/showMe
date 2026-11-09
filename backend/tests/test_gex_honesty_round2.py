"""GEX honesty regressions, second review round (wc1-g06).

* GEX#3: every manifest input is read by the handler, and every choice the
  manifest offers is accepted by the handler (no offered-then-refused option);
  no symbol means needs_input, never a silent SPY.
* GEX#5: no constant implied vol is substituted for a contract whose IV is
  missing or zero; missing open interest is never NaN and is disclosed.
* GEX#6: summary.source_mode agrees with data_mode (the snapshot state).

No network: the yfinance adapter is replaced by in-test stubs.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from showme.engine.core.base_data_source import DataKind
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.derivative.gex import (
    GEXFunction,
    _expiry_count,
    _validate_choices,
)
from showme.engine.services.gamma_exposure import chain_gex

FUTURE_EXPIRY = "2099-12-31"


def _run(coro):
    return asyncio.run(coro)


class _ChainStub:
    """Options-chain stub: one expiry list, one chain per expiry."""

    def __init__(self, calls: pd.DataFrame, puts: pd.DataFrame | None = None) -> None:
        self._calls = calls
        self._puts = puts if puts is not None else pd.DataFrame()

    async def fetch(self, request):  # noqa: ANN001
        if request.kind != DataKind.OPTIONS_CHAIN:
            return None
        if request.extra.get("expiry") is None:
            return {"expiries": [FUTURE_EXPIRY]}
        return {"calls": self._calls, "puts": self._puts}


def _now_stamp() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(timezone.utc))


def _calls_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# GEX#3: manifest inputs are wired; manifest choices are accepted
# --------------------------------------------------------------------------- #
def _manifest_entry():
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    return REGISTRY.get("GEX")


def test_manifest_declares_only_inputs_the_handler_reads() -> None:
    entry = _manifest_entry()
    handler_reads = {
        "underlying", "expiry_filter", "oi_source", "risk_free", "dividend_yield",
        "iv_source", "dealer_assumption",
    }
    declared = {spec.name for spec in entry.inputs}
    assert declared <= handler_reads, sorted(declared - handler_reads)


def test_every_manifest_choice_is_accepted_by_handler() -> None:
    entry = _manifest_entry()
    for spec in entry.inputs:
        for option in spec.options or []:
            if spec.name == "expiry_filter":
                _expiry_count({"expiry_filter": option})  # raises if refused
            elif spec.name in ("iv_source", "oi_source", "dealer_assumption"):
                _validate_choices({spec.name: option})  # raises if refused


def test_underlying_input_selects_the_symbol() -> None:
    stub = _ChainStub(_calls_frame([
        {"strike": 100.0, "openInterest": 10, "impliedVolatility": 0.3,
         "lastTradeDate": _now_stamp()},
    ]))
    fn = GEXFunction(deps=FunctionDeps(yfinance=stub))
    result = _run(fn.execute(underlying="NVDA", spot=100.0, live_options=True))
    assert result.data["symbol"] == "NVDA"
    assert result.data["underlying"] == "NVDA"


def test_no_symbol_is_needs_input_not_spy() -> None:
    stub = _ChainStub(_calls_frame([
        {"strike": 100.0, "openInterest": 10, "impliedVolatility": 0.3},
    ]))
    fn = GEXFunction(deps=FunctionDeps(yfinance=stub))
    result = _run(fn.execute(spot=100.0, live_options=True))
    data = result.data
    assert data["status"] == "needs_input"
    assert data["rows"] == []
    assert "symbol" in data["reason"].lower()


def test_router_injected_default_symbol_is_not_a_user_symbol() -> None:
    stub = _ChainStub(_calls_frame([
        {"strike": 100.0, "openInterest": 10, "impliedVolatility": 0.3},
    ]))
    fn = GEXFunction(deps=FunctionDeps(yfinance=stub))
    result = _run(fn.execute(**{"symbol": "SPY", "__explicit_symbol": False,
                                "spot": 100.0, "live_options": True}))
    assert result.data["status"] == "needs_input"
    assert result.data["rows"] == []


# --------------------------------------------------------------------------- #
# GEX#5: no constant IV is substituted; missing OI is never NaN
# --------------------------------------------------------------------------- #
def test_zero_implied_vol_contract_is_excluded_not_priced_at_default() -> None:
    good = {"strike": 105.0, "openInterest": 1000, "impliedVolatility": 0.3,
            "expiry": FUTURE_EXPIRY}
    bad = {"strike": 100.0, "openInterest": 1000, "impliedVolatility": 0,
           "expiry": FUTURE_EXPIRY}
    with_bad = chain_gex(spot=100.0, calls=[good, bad], puts=[])
    only_good = chain_gex(spot=100.0, calls=[good], puts=[])
    assert with_bad["call_gex_total"] == pytest.approx(only_good["call_gex_total"], rel=1e-6, abs=1e-6)
    assert with_bad["excluded"]["implied_vol"] == 1
    assert with_bad["contracts_used"] == 1


def test_nan_implied_vol_is_excluded_and_counted() -> None:
    bad = {"strike": 100.0, "openInterest": 1000, "impliedVolatility": float("nan"),
           "expiry": FUTURE_EXPIRY}
    out = chain_gex(spot=100.0, calls=[bad], puts=[])
    assert out["contracts_used"] == 0
    assert out["excluded"]["implied_vol"] == 1
    assert out["call_gex_total"] == 0.0


def test_nan_open_interest_is_not_propagated_and_is_disclosed() -> None:
    nan_oi = {"strike": 100.0, "openInterest": float("nan"), "impliedVolatility": 0.3,
              "expiry": FUTURE_EXPIRY}
    out = chain_gex(spot=100.0, calls=[nan_oi], puts=[])
    assert math.isfinite(out["call_gex_total"])
    assert out["call_gex_total"] == 0.0
    assert out["oi_missing"] == 1


def test_payload_with_no_usable_implied_vol_is_provider_unavailable() -> None:
    stub = _ChainStub(_calls_frame([
        {"strike": 100.0, "openInterest": 1000, "impliedVolatility": float("nan")},
        {"strike": 105.0, "openInterest": 1000, "impliedVolatility": 0},
    ]))
    fn = GEXFunction(deps=FunctionDeps(yfinance=stub))
    result = _run(fn.execute(symbol="SPY", spot=100.0, live_options=True))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.data["summary"]["net_gex"] is None


def test_payload_warns_when_contracts_were_left_out_for_iv() -> None:
    stub = _ChainStub(_calls_frame([
        {"strike": 100.0, "openInterest": 1000, "impliedVolatility": 0,
         "lastTradeDate": _now_stamp()},
        {"strike": 105.0, "openInterest": 1000, "impliedVolatility": 0.3,
         "lastTradeDate": _now_stamp()},
    ]))
    fn = GEXFunction(deps=FunctionDeps(yfinance=stub))
    result = _run(fn.execute(symbol="SPY", spot=100.0, live_options=True))
    assert result.data["status"] == "ok"
    assert result.data["summary"]["excluded_contracts"]["implied_vol"] == 1
    assert any("implied volatility" in w.lower() for w in result.warnings)


# --------------------------------------------------------------------------- #
# GEX#6: source_mode agrees with data_mode
# --------------------------------------------------------------------------- #
def test_source_mode_is_live_only_for_a_live_stamped_chain() -> None:
    stub = _ChainStub(_calls_frame([
        {"strike": 100.0, "openInterest": 10, "impliedVolatility": 0.3,
         "lastTradeDate": _now_stamp()},
    ]))
    result = _run(GEXFunction(deps=FunctionDeps(yfinance=stub)).execute(
        symbol="SPY", spot=100.0, live_options=True))
    assert result.data["data_mode"] == "live_yfinance"
    assert result.data["summary"]["source_mode"] == "live_chain"


def test_source_mode_is_not_live_for_a_last_session_chain() -> None:
    stale = (datetime.now(timezone.utc) - timedelta(days=3)).replace(hour=20, minute=59)
    stub = _ChainStub(_calls_frame([
        {"strike": 100.0, "openInterest": 10, "impliedVolatility": 0.3,
         "lastTradeDate": pd.Timestamp(stale)},
    ]))
    result = _run(GEXFunction(deps=FunctionDeps(yfinance=stub)).execute(
        symbol="SPY", spot=100.0, live_options=True))
    assert result.data["data_mode"] == "last_session_yfinance"
    source_mode = result.data["summary"]["source_mode"]
    assert source_mode != "live_chain"
    assert "live" not in source_mode


def test_source_mode_is_not_live_for_an_unstamped_chain() -> None:
    stub = _ChainStub(_calls_frame([
        {"strike": 100.0, "openInterest": 10, "impliedVolatility": 0.3},
    ]))
    result = _run(GEXFunction(deps=FunctionDeps(yfinance=stub)).execute(
        symbol="SPY", spot=100.0, live_options=True))
    assert result.data["data_mode"] == "snapshot_time_unknown"
    source_mode = result.data["summary"]["source_mode"]
    assert source_mode != "live_chain"
    assert "live" not in source_mode

