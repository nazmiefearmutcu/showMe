"""wc3-g15 MOST#1: the MOST change percent is measured against the prior session.

The review found MOST rows whose change_pct used a close about six sessions old
(Yahoo ``chartPreviousClose`` on a ``range=5d`` chart). The quote layer now takes
the prior regular-session close from the bars; this test runs the MOST row
mapping on that snapshot and checks the change against the prior session, not
against the 5-day baseline. Network is patched with a recorded-shape payload.
"""
from __future__ import annotations

from typing import Any

import pytest

from showme import quotes
from showme.engine.functions.screen import _funcs

# AMD-shaped chart (range=5d, interval=1d): five bars 11-02..11-06, with the
# close before the window (504.8) as chartPreviousClose.
_TS = [1793629800, 1793716200, 1793802600, 1793889000, 1793975400]
_CLOSES = [404.4, 410.0, 402.5, 395.0, 418.0]
_REGULAR_START_11_06 = 1793975400
_MARKET_TIME_11_06 = 1793982600


def _payload() -> dict[str, Any]:
    meta: dict[str, Any] = {
        "regularMarketPrice": 418.0,
        "previousClose": None,
        "chartPreviousClose": 504.8,  # close before the window: the wrong baseline
        "regularMarketVolume": 1000,
        "currency": "USD",
        "exchangeName": "NMS",
        "timezone": "EST",
        "gmtoffset": -18000,
        "regularMarketTime": _MARKET_TIME_11_06,
        "currentTradingPeriod": {"regular": {"start": _REGULAR_START_11_06,
                                             "end": _REGULAR_START_11_06 + 23400}},
    }
    return {"chart": {"result": [{
        "meta": meta,
        "timestamp": _TS,
        "indicators": {"quote": [{"close": _CLOSES, "volume": [1000] * len(_CLOSES)}]},
    }], "error": None}}


class _Resp:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return _payload()


def test_most_row_change_is_against_prior_session_not_five_day_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(quotes.requests, "get", lambda url, *a, **k: _Resp())
    quotes.quote_cache_clear()
    snapshot = quotes._fetch_yahoo_chart_quote("AMD")

    row = _funcs._snapshot_to_quote_row("AMD", snapshot)

    assert row is not None
    # Prior regular session close is 395.0 (11-05); 5-day baseline 504.8 would give -17.2%.
    assert snapshot["previous_close"] == pytest.approx(395.0)
    assert row["change_pct"] == pytest.approx((418.0 / 395.0 - 1.0) * 100.0, abs=1e-9)
    assert row["change_pct"] > 0
    assert row["change_pct"] != pytest.approx((418.0 / 504.8 - 1.0) * 100.0, abs=0.5)
