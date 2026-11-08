"""CPF honesty tests (wb1-g01): data-mode label, proxy disclosure, horizon-correct
cards, show_actual_history, calendar-month forecast dates, provider chain and
the removed provider_mode input.

Network is patched: ``CPFFunction._yahoo_history`` is replaced with a fake, and
the default ``CPFFunction()`` has no yfinance adapter wired (deps.yfinance is
None), so nothing real is fetched.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from showme.engine.functions.commodity._funcs import CPFFunction


def _history(
    n: int = 200,
    start: float = 90.0,
    step: float = 0.1,
    end: date = date(2026, 11, 6),
) -> list[dict]:
    """n ascending daily closes ending on ``end`` (the last realized actual)."""
    first = end - timedelta(days=n - 1)
    return [
        {"date": (first + timedelta(days=i)).isoformat(), "value": round(start + i * step, 4)}
        for i in range(n)
    ]


def _patch_history(monkeypatch, rows: list[dict], calls: list[str] | None = None) -> None:
    async def _fake(self, symbol, timeout):  # noqa: ARG001
        if calls is not None:
            calls.append(symbol)
        return list(rows)

    monkeypatch.setattr(CPFFunction, "_yahoo_history", _fake)


def _run(series_id: str = "WTISPLC", horizon: str = "1Y", **params):
    return asyncio.run(CPFFunction().execute(series_id=series_id, horizon=horizon, **params))


# CPF#2 — both legs are a futures proxy plus a trend extrapolation, so the mode
# must not be labelled live_official (the official-series label).
def test_futures_proxy_is_not_labelled_live_official(monkeypatch) -> None:
    _patch_history(monkeypatch, _history())
    result = _run()
    assert result.data["status"] == "ok"
    assert result.data["data_mode"] == "futures_proxy_trend"
    assert result.data["cards"]["data_mode"] == "futures_proxy_trend"


# CPF#6 — cards.forecast_1y must be the ~12-month point. For a 6M horizon the
# old code returned the 6M endpoint under the 1Y key.
def test_forecast_1y_card_is_only_the_twelve_month_point(monkeypatch) -> None:
    _patch_history(monkeypatch, _history(end=date(2026, 11, 6)))
    short = _run(horizon="6M")
    assert len(short.data["forecast"]) == 6
    assert short.data["cards"]["forecast_1y"] is None
    assert short.data["cards"]["forecast_at_horizon"] == short.data["forecast"][-1]["value"]

    long_ = _run(horizon="1Y")
    assert long_.data["cards"]["forecast_1y"] == long_.data["forecast"][11]["value"]
    assert long_.data["cards"]["forecast_at_horizon"] == long_.data["forecast"][-1]["value"]


# CPF#8 — forecast points are calendar months after the last actual, not 30-day
# steps (the old 30-day step put the 12th point at +360 days).
def test_forecast_dates_step_by_calendar_months(monkeypatch) -> None:
    _patch_history(monkeypatch, _history(end=date(2026, 11, 6)))
    result = _run(horizon="1Y")
    dates = [p["date"] for p in result.data["forecast"]]
    assert dates[0] == "2026-12-06"
    assert dates[5] == "2027-05-06"
    assert dates[11] == "2027-11-06"


def test_forecast_month_end_clamps_to_last_day_of_month(monkeypatch) -> None:
    _patch_history(monkeypatch, _history(end=date(2026, 1, 31)))
    result = _run(horizon="6M")
    dates = [p["date"] for p in result.data["forecast"]]
    assert dates[:3] == ["2026-02-28", "2026-03-31", "2026-04-30"]


# CPF#5 — show_actual_history=false must not break the forecast. The forecast is
# built from the actual leg, so the leg is always fetched; the flag only hides it
# from rows and the actual series.
def test_hiding_actual_history_still_fetches_and_builds_the_forecast(monkeypatch) -> None:
    calls: list[str] = []
    _patch_history(monkeypatch, _history(), calls)
    result = _run(horizon="1Y", show_actual_history=False)
    assert calls == ["CL=F"], "the actual leg must be fetched even when it is not displayed"
    assert result.data["status"] == "ok"
    assert len(result.data["forecast"]) == 12
    assert result.data["cards"]["latest_actual"] is not None
    assert all(row["kind"] == "forecast" for row in result.data["rows"])
    assert result.data["series"][0]["points"] == []


def test_outage_reason_reports_the_real_failure_not_a_skipped_fetch(monkeypatch) -> None:
    async def _boom(self, symbol, timeout):  # noqa: ARG001
        raise RuntimeError("HTTP 503")

    monkeypatch.setattr(CPFFunction, "_yahoo_history", _boom)
    result = _run(horizon="1Y", show_actual_history=False)
    assert result.data["status"] == "provider_unavailable"
    assert "CL=F" in result.data["reason"]
    assert "HTTP 503" in result.data["reason"]
