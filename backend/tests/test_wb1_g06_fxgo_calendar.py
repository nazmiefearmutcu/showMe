"""wb1-g06 regression pins: FXGO dealing board (FXGO#1, #2, #5) and calendar (ASOF-12)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import requests


def _run(coro):
    return asyncio.run(coro)


def _mk_fxgo():
    from showme.engine.functions.trade._funcs import FXGOFunction

    try:
        return FXGOFunction(deps=None)
    except TypeError:
        return FXGOFunction()


# --------------------------------------------------------------------------- #
# FXGO#5 — the bare board call must show the full default grid
# --------------------------------------------------------------------------- #
def test_fxgo_router_injected_fx_peers_do_not_shrink_default_board(monkeypatch):
    """The router injects the FX agent peer group into ``symbols``
    (_agent_runtime._agent_profile -> _agent_function_params). FXGO must not
    read that as a board request: a bare call returns the 10-pair default."""
    from showme.engine.functions.trade._funcs import FXGOFunction
    from showme.server_routes._agent_runtime import _route_function_params

    seen: list[str] = []

    def fake_spot(self, pair):
        seen.append(pair)
        return (1.10, 1.09)

    monkeypatch.setattr(FXGOFunction, "_fetch_fx_spot", fake_spot)
    routed = _route_function_params("FXGO", {})
    res = _run(_mk_fxgo().execute(**routed))
    data = res.data
    assert data["status"] == "ok"
    assert len(data["rows"]) == len(FXGOFunction._BOARD_PAIRS) == 10
    assert data["requested_pairs"] == list(FXGOFunction._BOARD_PAIRS)
    assert data["board_source"] == "default"
    assert len(seen) == 10


def test_fxgo_explicit_symbol_board_is_that_single_pair(monkeypatch):
    from showme.engine.functions.trade._funcs import FXGOFunction

    monkeypatch.setattr(FXGOFunction, "_fetch_fx_spot", lambda self, pair: (150.0, 149.5))
    res = _run(_mk_fxgo().execute(symbol="USDJPY", __explicit_symbol=True))
    assert [r["pair"] for r in res.data["rows"]] == ["USDJPY"]
    assert res.data["board_source"] == "explicit_symbol"


def test_fxgo_explicit_pairs_list_is_honoured(monkeypatch):
    from showme.engine.functions.trade._funcs import FXGOFunction

    monkeypatch.setattr(FXGOFunction, "_fetch_fx_spot", lambda self, pair: (1.1, 1.09))
    res = _run(_mk_fxgo().execute(pairs="EURUSD,AUDUSD"))
    assert [r["pair"] for r in res.data["rows"]] == ["EURUSD", "AUDUSD"]
    assert res.data["board_source"] == "explicit_pairs"


# --------------------------------------------------------------------------- #
# FXGO#2 — previous close is the prior daily session, not the 5-day range start
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _epoch(day: int, hour: int = 0, minute: int = 0) -> int:
    return int(datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc).timestamp())


def _chart_payload(day_closes, *, regular_price, regular_time, chart_prev):
    """Shape of a Yahoo v8 chart response for range=5d, interval=1d."""
    return {
        "chart": {
            "result": [{
                "meta": {
                    "regularMarketPrice": regular_price,
                    "regularMarketTime": regular_time,
                    "chartPreviousClose": chart_prev,
                    "previousClose": None,
                },
                "timestamp": [_epoch(d) for d, _ in day_closes],
                "indicators": {"quote": [{"close": [c for _, c in day_closes]}]},
            }],
            "error": None,
        }
    }


# Daily closes 2026-11-02 .. 2026-11-06 (Friday); quote stamped Friday 22:29 UTC.
_FIVE_DAY_CLOSES = [
    (2, 1.11569), (3, 1.11900), (4, 1.12100), (5, 1.12349), (6, 1.12283),
]


def test_fxgo_previous_close_is_prior_session_not_five_sessions_back(monkeypatch):
    from showme.engine.functions.trade._funcs import FXGOFunction

    payload = _chart_payload(
        _FIVE_DAY_CLOSES,
        regular_price=1.1230,
        regular_time=_epoch(6, 22, 29),
        chart_prev=1.11569,  # Yahoo: close BEFORE the 5-day window
    )
    monkeypatch.setattr(requests, "get", lambda url, **kw: _Resp(payload))

    res = _run(_mk_fxgo().execute(pairs="EURUSD"))
    row = res.data["rows"][0]
    # Prior session is 2026-11-05 (1.12349), not the 1.11569 window start.
    assert row["previous_close"] == pytest.approx(1.12349, abs=1e-6)
    assert row["previous_close_date"] == "2026-11-05"
    assert row["change"] == pytest.approx(1.1230 - 1.12349, abs=1e-6)
    assert row["change_pct"] == pytest.approx((1.1230 - 1.12349) / 1.12349 * 100, abs=1e-3)
    assert "Prior session close" in res.data["field_dictionary"]["previous_close"] or \
        "prior" in res.data["field_dictionary"]["previous_close"].lower()
