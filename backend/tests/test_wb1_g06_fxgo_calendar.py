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
