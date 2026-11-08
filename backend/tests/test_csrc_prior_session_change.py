"""CSRC#1 — a commodity row's change must be the prior-session move, not a 5-session one.

The Yahoo chart request is range=5d, so meta.chartPreviousClose is the close before the
window. CSRC used to label a multi-session move as the day change (CL=F showed -5.84% when
the 1-day move was +0.34%). The MAP fix moved the baseline to the prior daily bar; this
test pins that for the CSRC row path (fetch_quote_snapshot -> screen quote row).

Network is patched: ``requests.get`` returns a recorded-shape chart payload for CL=F.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme import quotes
from showme.engine.functions.screen import _funcs as screen_funcs

# CL=F, Yahoo v8 chart (range=5d, interval=1d), sessions 2026-11-02..06 (14:30 UTC bars).
_TS = [1793629800, 1793716200, 1793802600, 1793889000, 1793975400]
_CLOSES = [96.46, 96.09, 88.12, 90.52, 90.83]  # 11-06 is the latest session
_MARKET_TIME_11_06 = 1793982600  # 2026-11-06 11:30 EST, the quoted price's own time


def _payload() -> dict[str, Any]:
    meta: dict[str, Any] = {
        "regularMarketPrice": 90.83,
        "previousClose": None,
        "chartPreviousClose": 96.46,  # close before the 5-day window: the wrong 1D baseline
        "regularMarketTime": _MARKET_TIME_11_06,
        "regularMarketVolume": 300000,
        "currency": "USD",
        "exchangeName": "NYM",
        "gmtoffset": -18000,
        "timezone": "EST",
    }
    return {"chart": {"result": [{
        "meta": meta,
        "timestamp": _TS,
        "indicators": {"quote": [{"close": _CLOSES, "volume": [1] * len(_CLOSES)}]},
    }], "error": None}}


class _Resp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def _patch(monkeypatch: pytest.MonkeyPatch) -> None:
    def _get(url: str, *args: Any, **kwargs: Any) -> _Resp:
        assert "query1.finance.yahoo.com/v8/finance/chart/" in url, url
        return _Resp(_payload())

    monkeypatch.setattr(quotes.requests, "get", _get)
    quotes.quote_cache_clear()


def test_commodity_quote_row_change_is_the_prior_session_move(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    rows = asyncio.run(screen_funcs._csrc_quote_snapshot_rows(
        ["CL=F"], screen_timeout=5.0, concurrency=1))[0]
    row = next(r for r in rows if r["symbol"] == "CL=F")
    # Prior session is 11-05 (90.52), not the 5-session baseline 96.46.
    assert row["prev_close"] == pytest.approx(90.52)
    assert row["change_pct"] == pytest.approx((90.83 / 90.52 - 1.0) * 100.0, abs=1e-9)
    assert row["change_pct"] == pytest.approx(0.3425, abs=1e-3)
    assert row["change_pct"] > 0  # the sign is the 1-day sign, not the 5-day -5.8%
