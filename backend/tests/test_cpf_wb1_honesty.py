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
    first: date = date(2026, 1, 1),
) -> list[dict]:
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
