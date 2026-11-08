"""WC2-G05 regression tests: SECT period returns from daily history, and model values."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pandas as pd


def _run(coro):
    return asyncio.run(coro)


class _Quote:
    def __init__(self, last: float, close_prev: float = 100.0):
        self.last = last
        self.close_prev = close_prev
        self.high_24h = None
        self.low_24h = None


def _history(closes_by_day: dict[date, float]) -> pd.DataFrame:
    idx = pd.DatetimeIndex(
        [datetime(d.year, d.month, d.day, tzinfo=timezone.utc) for d in sorted(closes_by_day)]
    )
    return pd.DataFrame({"close": [closes_by_day[d] for d in sorted(closes_by_day)]}, index=idx)


class _HistYf:
    """Quotes: XLK last=110. History: a bar on the base day and a bar after it."""

    def __init__(self, base_day: date, base_close: float, *, with_history: bool = True):
        self.base_day = base_day
        self.base_close = base_close
        self.with_history = with_history
        self.history_calls: list[str] = []

    async def fetch(self, request, *a, **kw):
        from showme.engine.core.base_data_source import DataKind

        if request.kind == DataKind.QUOTE:
            return _Quote(last=110.0)
        assert request.kind == DataKind.OHLCV
        self.history_calls.append(request.instrument.symbol)
        if not self.with_history:
            return pd.DataFrame()
        later = self.base_day + timedelta(days=3)
        return _history({self.base_day: self.base_close, later: 120.0})


def _sect(yf):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.screen.sect import SECTFunction

    return SECTFunction(FunctionDeps(yfinance=yf))


def test_sect_ytd_change_uses_prior_year_end_close() -> None:
    """YTD return = live last / prior-year-end close - 1, not the 1D quote move."""
    today = datetime.now(timezone.utc).date()
    base_day = date(today.year - 1, 12, 31)
    yf = _HistYf(base_day, base_close=100.0)
    out = _run(_sect(yf).execute(period="YTD", live=True))
    assert out.data["status"] == "ok"
    row = next(r for r in out.data["rows"] if r["etf"] == "XLK")
    assert row["change_pct_period"] == "YTD"
    # last 110 vs base 100 => +10%. A 1D move from close_prev 100 would also be
    # +10%, so the base close is the discriminator: 110 / 100 - 1 with base=100.
    assert abs(row["change_pct"] - 10.0) < 1e-9, row
    assert out.data["change_pct_period"] == "YTD"
    assert not any("1D" in w for w in out.warnings), out.warnings


def test_sect_mtd_base_is_last_close_before_month_start() -> None:
    """A bar dated on the month's first day must not be used as the base."""
    today = datetime.now(timezone.utc).date()
    first_of_month = date(today.year, today.month, 1)
    base_day = first_of_month - timedelta(days=1)
    yf = _HistYf(base_day, base_close=50.0)
    out = _run(_sect(yf).execute(period="MTD", live=True))
    row = next(r for r in out.data["rows"] if r["etf"] == "XLK")
    assert row["change_pct_period"] == "MTD"
    assert abs(row["change_pct"] - (110.0 / 50.0 - 1) * 100) < 1e-9, row


def test_sect_missing_history_gives_null_change_and_disclosed_warning() -> None:
    today = datetime.now(timezone.utc).date()
    yf = _HistYf(date(today.year - 1, 12, 31), base_close=100.0, with_history=False)
    out = _run(_sect(yf).execute(period="YTD", live=True))
    assert out.data["status"] == "ok"
    for row in out.data["rows"]:
        if row["last"] is not None:
            assert row["change_pct"] is None, row
            assert row["change_pct_period"] is None, row
    assert any("YTD" in w and "null" in w for w in out.warnings), out.warnings


def test_sect_1d_still_uses_quote_previous_close_without_history() -> None:
    yf = _HistYf(date(2000, 1, 1), base_close=1.0)
    out = _run(_sect(yf).execute(period="1D", live=True))
    row = next(r for r in out.data["rows"] if r["etf"] == "XLK")
    assert row["change_pct_period"] == "1D"
    assert abs(row["change_pct"] - 10.0) < 1e-9
    assert yf.history_calls == []


def test_sect_model_rows_carry_no_fabricated_prices_or_changes() -> None:
    for period in ("1D", "MTD", "QTD", "YTD"):
        out = _run(_sect(None).execute(period=period))
        assert out.data["status"] == "model"
        assert len(out.data["rows"]) == 11
        for row in out.data["rows"]:
            assert row["last"] is None, row
            assert row["high_24h"] is None and row["low_24h"] is None, row
            assert row["change_pct"] is None, row
            assert row["change_pct_period"] is None, row
            assert row["quote_type"] == "model", row


def test_sect_provider_fallback_rows_carry_no_placeholder_values() -> None:
    class _Dead:
        async def fetch(self, request, *a, **kw):
            raise RuntimeError("throttled")

    out = _run(_sect(_Dead()).execute(period="YTD", live=True))
    assert out.data["status"] == "provider_unavailable"
    assert all(r["last"] is None and r["change_pct"] is None for r in out.data["rows"])
