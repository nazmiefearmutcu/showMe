"""wc1-g36 DARK regressions: DARK#3, DARK#4, DARK-R1.

DARK#3 - seed methodology and provider chain must match the handler.
DARK#4 - ratios above 100% are withheld (not capped), the yfinance weekly
         history covers the requested FINRA window, no silent AAPL default.
DARK-R1 - an empty wired FINRA adapter frame is the answer; no second
          direct request to the same endpoint.

No network: FINRA and yfinance are faked.
"""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.data_sources.equity.finra_adapter import ats_window_days
from showme.engine.functions.equity.dark import DARKFunction

import test_g3_finra_ats_window as g3


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- DARK#4a


def _weekly_volume_for_latest(value: float) -> Any:
    async def _vol(self, sym):  # noqa: ANN001
        return {g3._latest_monday().isoformat(): value}

    return _vol


def test_dark_ratio_above_100_is_withheld_not_capped(monkeypatch) -> None:
    """ATS volume larger than the weekly total is a data mismatch; never show 100."""
    fake = g3.FakeFinra(g3._dataset())
    g3._patch_direct_finra(monkeypatch, fake)
    # Latest week ATS volume in the fixture is 1_000_000; total is only 500_000.
    monkeypatch.setattr(DARKFunction, "_weekly_total_volume", _weekly_volume_for_latest(500_000.0))

    result = _run(DARKFunctionFactory().execute(symbol="AAPL", weeks=8))
    data = result.data

    assert data["status"] == "ok", data.get("reason")
    assert data["by_week"][0]["dark_pool_pct"] is None
    assert data["cards"]["latest_dark_pool_pct"] is None
    assert data["venues"][0]["dark_pool_pct"] is None
    assert any("exceeds" in w for w in result.warnings), result.warnings


# ---------------------------------------------------------------- DARK#4b


def test_dark_yfinance_history_covers_the_full_finra_window(monkeypatch) -> None:
    """A 6mo weekly pull cannot cover a 26-week FINRA window (~224 days)."""
    seen: dict[str, Any] = {}

    class _Ticker:
        def __init__(self, symbol):  # noqa: ANN001
            self.symbol = symbol

        def history(self, period=None, interval=None, auto_adjust=None):  # noqa: ANN001
            seen["period"] = period
            seen["interval"] = interval
            return pd.DataFrame()

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = _Ticker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    out = _run(DARKFunction(deps=FunctionDeps())._weekly_total_volume("AAPL"))
    assert out == {}
    assert seen["period"] != "6mo"
    assert seen["interval"] == "1wk"
    # Map the yfinance period onto a day count and check it spans the window.
    period_days = {"1y": 365, "2y": 730, "5y": 1825, "max": 10_000}[seen["period"]]
    assert period_days >= ats_window_days(26)


def test_dark_old_week_gets_a_denominator_from_long_history(monkeypatch) -> None:
    """A week older than six months still gets dark_pool_pct when yfinance has it."""
    latest = g3._latest_monday()
    oldest = latest - timedelta(weeks=20)  # ~140 days back: outside a 6mo pull

    class _Ticker:
        def __init__(self, symbol):  # noqa: ANN001
            pass

        def history(self, period=None, interval=None, auto_adjust=None):  # noqa: ANN001
            # Only a 1y+ history contains the old week.
            if period == "6mo":
                idx = [pd.Timestamp(latest)]
                vols = [5e9]
            else:
                idx = [pd.Timestamp(latest), pd.Timestamp(oldest)]
                vols = [5e9, 4e9]
            return pd.DataFrame({"Volume": vols}, index=pd.DatetimeIndex(idx))

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = _Ticker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    fake = g3.FakeFinra(g3._dataset())
    g3._patch_direct_finra(monkeypatch, fake)
    result = _run(DARKFunctionFactory().execute(symbol="AAPL", weeks=26))
    by_week = {r["weekStartDate"]: r for r in result.data["by_week"]}

    assert by_week[oldest.isoformat()]["total_weekly_volume"] == round(4e9)
    assert by_week[oldest.isoformat()]["dark_pool_pct"] is not None


def test_dark_warns_when_some_weeks_lack_a_denominator(monkeypatch) -> None:
    """Missing weekly totals must be said out loud, not left as silent None."""
    fake = g3.FakeFinra(g3._dataset())
    g3._patch_direct_finra(monkeypatch, fake)
    monkeypatch.setattr(DARKFunction, "_weekly_total_volume", _weekly_volume_for_latest(5e9))

    result = _run(DARKFunctionFactory().execute(symbol="AAPL", weeks=8))

    assert result.data["by_week"][0]["dark_pool_pct"] is not None
    assert any("weekly total volume" in w.lower() for w in result.warnings), result.warnings


# ---------------------------------------------------------------- DARK#4c


def test_dark_without_symbol_asks_for_input_instead_of_aapl(monkeypatch) -> None:
    fake = g3.FakeFinra(g3._dataset())
    g3._patch_direct_finra(monkeypatch, fake)
    monkeypatch.setattr(DARKFunction, "_weekly_total_volume", lambda self, sym: g3._no_yfinance())

    result = _run(DARKFunctionFactory().execute())
    data = result.data

    assert data["status"] == "input_required"
    assert data.get("symbol") in (None, "")
    assert data["venues"] == []
    assert data.get("next_actions")
    assert fake.bodies == [], "no FINRA request may be made for an unknown symbol"


# helper so the tests read the same way regardless of how the handler is built
def DARKFunctionFactory():  # noqa: N802
    return DARKFunction(deps=FunctionDeps())


# ---------------------------------------------------------------- DARK#2


class _WideWiredFinra:
    """A wired adapter that returns more weeks than the caller asked for."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def ats_weekly(self, symbol=None, limit=26):  # noqa: ANN001
        return pd.DataFrame(self._rows)


def test_dark_total_off_exchange_sums_only_the_requested_weeks(monkeypatch) -> None:
    """The KPI caption says 8W WINDOW; the total must cover those 8 weeks only."""
    monkeypatch.setattr(DARKFunction, "_weekly_total_volume", lambda self, sym: g3._no_yfinance())
    rows = g3._dataset()  # 260 weeks, far more than the 8 requested

    result = _run(
        DARKFunction(deps=FunctionDeps(finra=_WideWiredFinra(rows))).execute(symbol="AAPL", weeks=8)
    )
    data = result.data

    assert data["status"] == "ok", data.get("reason")
    assert len(data["by_week"]) == 8
    window_total = sum(r["ats_share_volume"] for r in data["by_week"])
    assert data["total_shares_off_exchange"] == window_total
    assert data["total_shares_off_exchange"] < sum(r["totalWeeklyShareQuantity"] for r in rows)


# ---------------------------------------------------------------- DARK#4 (production route)


def _simulate_worker_dispatch(code: str, raw_params: dict[str, Any], finra: Any) -> Any:
    """Mirror server.py's worker: the router's symbol becomes the Instrument."""
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.server_routes._agent_runtime import _route_function_params

    params = _route_function_params(code, dict(raw_params))
    symbol = params.pop("symbol", None)
    asset_class = params.pop("asset_class", None)
    instrument = None
    if symbol:
        instrument = Instrument(symbol=str(symbol), asset_class=AssetClass.EQUITY)
    return _run(DARKFunction(deps=FunctionDeps(finra=finra)).execute(instrument=instrument, **params))


def test_dark_production_route_without_symbol_never_queries_aapl(monkeypatch) -> None:
    """The router injects AAPL with __explicit_symbol=False; that must not reach FINRA."""
    monkeypatch.setattr(DARKFunction, "_weekly_total_volume", lambda self, sym: g3._no_yfinance())
    fake = g3.FakeFinra(g3._dataset())
    g3._patch_direct_finra(monkeypatch, fake)

    for raw in ({"asset_class": "EQUITY"}, {"symbol": "", "asset_class": "EQUITY"}):
        result = _simulate_worker_dispatch("DARK", raw, finra=None)
        assert result.data["status"] == "input_required", raw
        assert result.data.get("symbol") in (None, ""), raw
        assert result.data["venues"] == [], raw
    assert fake.bodies == [], "no FINRA request may be made for an unselected symbol"


def test_dark_production_route_explicit_symbol_still_resolves(monkeypatch) -> None:
    monkeypatch.setattr(DARKFunction, "_weekly_total_volume", lambda self, sym: g3._no_yfinance())
    fake = g3.FakeFinra(g3._dataset("MSFT"))
    g3._patch_direct_finra(monkeypatch, fake)

    result = _simulate_worker_dispatch("DARK", {"symbol": "MSFT", "asset_class": "EQUITY"}, finra=None)

    assert result.data["symbol"] == "MSFT"
    assert result.data["status"] == "ok", result.data.get("reason")
