"""WC1 g31 — IVOL honesty and calculation fixes (network patched, no live calls).

* placeholder_value (T10): with the network cut the response must not carry the
  placeholder spot 100 and must not template a surface.
* IVOL#2: ATM IV is the call/put average at the nearest two-sided strike, not the
  call alone via a tie-break.
* IVOL#3: skew (90-110) interpolates put@90% and call@110% on their own strikes
  and is null outside the listed range.
* IVOL#4: the surface states its snapshot basis (as_of) and time-to-expiry
  convention, and warns when the front expiry is very short.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import pytest

from showme.audit import truth
from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.derivative._stubs import (
    IVOLFunction,
    _ivol_atm_term_and_skew,
)

SPOT = 735.29


def _spy() -> Instrument:
    return Instrument(symbol="SPY", asset_class=AssetClass.ETF)


class _Deps:
    def __init__(self, yfinance: Any = None) -> None:
        self.yfinance = yfinance

    def __getattr__(self, item: str) -> Any:  # pragma: no cover
        return None


class _Down:
    """Every outbound call fails, as with the network cut."""

    async def fetch(self, request: DataRequest) -> Any:
        raise ConnectionError("network cut")


class _NoExpiries:
    async def fetch(self, request: DataRequest) -> Any:
        if request.kind == DataKind.OPTIONS_CHAIN and not (request.extra or {}).get("expiry"):
            return {"underlyingPrice": SPOT, "expiries": []}
        return None


def _chain_yf(expiry: str, calls: pd.DataFrame, puts: pd.DataFrame, *, trade_ts: str | None = None) -> Any:
    class _Yf:
        async def fetch(self, request: DataRequest) -> Any:
            if request.kind != DataKind.OPTIONS_CHAIN:
                return None
            if not (request.extra or {}).get("expiry"):
                return {"underlyingPrice": SPOT, "expiries": [expiry]}
            c = calls.copy()
            p = puts.copy()
            if trade_ts is not None:
                c["lastTradeDate"] = pd.Timestamp(trade_ts)
                p["lastTradeDate"] = pd.Timestamp(trade_ts)
            return {"calls": c, "puts": p}

    return _Yf()


def _frame(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame({
        "strike": [r[0] for r in rows],
        "impliedVolatility": [r[1] for r in rows],
        "bid": [r[2] for r in rows],
        "ask": [r[3] for r in rows],
        "lastPrice": [(r[2] + r[3]) / 2 for r in rows],
        "volume": [10] * len(rows),
        "openInterest": [100] * len(rows),
    })


# ── placeholder_value ──────────────────────────────────────────────────────


def test_network_cut_response_has_no_placeholder_spot_or_template() -> None:
    result = asyncio.run(IVOLFunction(deps=_Deps(yfinance=_Down())).execute(instrument=_spy()))
    body = result.data
    assert body["status"] == "provider_unavailable"
    assert body["spot"] is None
    assert "calls_grid" not in body and "puts_grid" not in body
    assert "black_scholes_reference_formula" not in result.sources
    # RED before fix: spot=100.0 was reported and the audit flagged it as a demo price.
    findings = truth.check_response_placeholders(
        body, request_params={}, cfg=truth.load_config(), code="IVOL")
    assert findings == []


def test_no_expiries_returns_honest_state_not_template() -> None:
    result = asyncio.run(IVOLFunction(deps=_Deps(yfinance=_NoExpiries())).execute(instrument=_spy()))
    body = result.data
    # RED before fix: the no-expiry path returned the template with invented constant IVs.
    assert body["status"] == "provider_unavailable"
    assert body["surface"] == [] and body["rows"] == []
    assert "calls_grid" not in body
    assert body["spot"] == pytest.approx(SPOT)
    assert body["reason"] and body["next_actions"]


# ── IVOL#2 ATM ─────────────────────────────────────────────────────────────


def test_atm_iv_is_call_put_average_at_nearest_two_sided_strike() -> None:
    calls = _frame([(720, 0.20, 16.00, 16.40), (735, 0.17, 10.00, 10.40), (750, 0.15, 3.00, 3.40)])
    puts = _frame([(720, 0.25, 2.00, 2.20), (735, 0.18, 9.00, 9.40), (750, 0.22, 15.00, 15.40)])
    expiry = "2026-12-18"
    fn = IVOLFunction(deps=_Deps(yfinance=_chain_yf(expiry, calls, puts)))
    body = asyncio.run(fn.execute(instrument=_spy())).data
    assert body["status"] == "ok"
    # RED before fix: the tie at 735 went to the call alone (0.17).
    assert body["summary"]["atm_iv_front"] == pytest.approx(0.175, abs=1e-6)
    assert body["series"][0]["v"] == pytest.approx(0.175, abs=1e-6)


# ── IVOL#3 skew ────────────────────────────────────────────────────────────


def _row(expiry: str, m: float, side: str, vol: float) -> dict[str, Any]:
    return {"expiry": expiry, "moneyness": m, "option_type": side, "vol": vol}


def test_skew_interpolates_put_at_90_minus_call_at_110() -> None:
    e = "2026-12-18"
    rows = [
        _row(e, 1.00, "CALL", 0.28), _row(e, 1.00, "PUT", 0.29),
        _row(e, 0.85, "PUT", 0.40), _row(e, 0.95, "PUT", 0.30),
        _row(e, 1.05, "CALL", 0.25), _row(e, 1.15, "CALL", 0.35),
    ]
    stats, _ = _ivol_atm_term_and_skew(rows)
    # put@0.90 = 0.35 (interp 0.85..0.95); call@1.10 = 0.30 (interp 1.05..1.15); skew = 0.05.
    # RED before fix: nearest cells (put 0.85 and call 1.05) gave 0.15.
    assert stats["skew"] == pytest.approx(0.05, abs=1e-6)
    assert stats["skew_put_iv_90"] == pytest.approx(0.35, abs=1e-6)
    assert stats["skew_call_iv_110"] == pytest.approx(0.30, abs=1e-6)


def test_skew_is_null_when_a_point_is_outside_listed_strikes() -> None:
    e = "2026-12-18"
    rows = [
        _row(e, 1.00, "CALL", 0.28), _row(e, 1.00, "PUT", 0.29),
        _row(e, 0.95, "PUT", 0.30),  # no put at or below 0.90 to bracket 0.90
        _row(e, 1.05, "CALL", 0.25), _row(e, 1.15, "CALL", 0.35),
    ]
    stats, _ = _ivol_atm_term_and_skew(rows)
    assert stats["skew"] is None
    assert stats["skew_put_iv_90"] is None


# ── IVOL#4 as-of, convention, short-dated warning ──────────────────────────


def test_surface_states_snapshot_basis_and_warns_on_short_front_expiry() -> None:
    now = datetime.now(timezone.utc)
    soon = (now + timedelta(days=1)).date().isoformat()
    calls = _frame([(735, 0.17, 10.00, 10.40)])
    puts = _frame([(735, 0.18, 9.00, 9.40)])
    trade = (now - timedelta(hours=20)).strftime("%Y-%m-%d %H:%M:%S")
    fn = IVOLFunction(deps=_Deps(yfinance=_chain_yf(soon, calls, puts, trade_ts=trade)))
    body = asyncio.run(fn.execute(instrument=_spy())).data
    assert body["status"] == "ok"
    # RED before fix: none of these disclosure fields existed.
    assert body["as_of"] and body["as_of"].startswith(trade[:10])
    assert "as_of_basis" in body and "iv_convention" in body
    assert body["summary"]["front_days_to_expiry"] <= 2
    assert any("calendar day" in w for w in body["warnings"])
