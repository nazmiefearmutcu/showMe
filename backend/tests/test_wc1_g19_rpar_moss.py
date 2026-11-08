"""WC1-G19 RPAR regressions: route defaults, manifest universe name, ERC default, bounded fetch.

RPAR#3 route defaults, RPAR#5 manifest universe name, RPAR#6 default ERC method,
RPAR#7 bounded live fetch.

No network: market data is a deterministic fake and the Yahoo fallback is patched.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio import rpar as rpar_mod
from showme.engine.functions.portfolio.rpar import RPARFunction
from showme.manifest import load_seeds
from showme.server_routes import _agent_runtime


class _FakeYfinance:
    def __init__(self) -> None:
        self.requested: list[str] = []

    async def fetch(self, request: Any, *_args: Any, **_kwargs: Any) -> pd.DataFrame:
        symbol = request.instrument.symbol
        self.requested.append(symbol)
        seed = sum(ord(ch) for ch in symbol)
        rng = np.random.default_rng(seed)
        n = 320
        vol = 0.008 + (seed % 7) * 0.003
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, vol, n)))
        idx = pd.bdate_range(end="2026-10-30", periods=n)
        return pd.DataFrame({"close": close}, index=idx)


class _SlowYfinance:
    async def fetch(self, *_args: Any, **_kwargs: Any) -> pd.DataFrame:
        await asyncio.sleep(30)
        return pd.DataFrame()


# ----------------------------- RPAR#5 universe ------------------------------

def test_manifest_universe_name_is_used_instead_of_a_default_basket() -> None:
    fake = _FakeYfinance()
    out = asyncio.run(
        RPARFunction(FunctionDeps(yfinance=fake)).execute(universe=["AAA", "BBB", "CCC"], method="erc")
    )
    assert out.data["symbols"] == ["AAA", "BBB", "CCC"]
    assert set(fake.requested) == {"AAA", "BBB", "CCC"}


def test_missing_universe_is_explicit_state_not_the_hard_coded_basket() -> None:
    fake = _FakeYfinance()
    out = asyncio.run(RPARFunction(FunctionDeps(yfinance=fake)).execute(method="erc"))
    assert fake.requested == []
    assert out.data["status"] == "needs_input"
    assert out.data["weights"] == {}
    assert out.data["symbols"] == []
    assert out.metadata["fallback_reason"] == "universe_missing"


# ----------------------------- RPAR#6 default method ------------------------

def test_default_method_is_equal_risk_contribution() -> None:
    out = asyncio.run(RPARFunction(FunctionDeps(yfinance=_FakeYfinance())).execute(symbols="AAA,BBB,CCC"))
    assert out.data["info"]["method"] == "erc"
    assert out.data["summary"]["method"] == "erc"


# ----------------------------- RPAR#7 bounded fetch -------------------------

def test_live_fetch_is_bounded_by_one_overall_budget(monkeypatch) -> None:
    monkeypatch.setattr(rpar_mod, "_SYMBOL_TIMEOUT_SECONDS", 30.0, raising=False)
    monkeypatch.setattr(rpar_mod, "_FETCH_BUDGET_SECONDS", 0.3, raising=False)

    async def _slow_yahoo(_symbol: str, _days: int) -> pd.Series:
        await asyncio.sleep(30)
        return pd.Series(dtype=float)

    monkeypatch.setattr(rpar_mod, "_yahoo_daily_returns", _slow_yahoo)
    started = time.monotonic()
    out = asyncio.run(RPARFunction(FunctionDeps(yfinance=_SlowYfinance())).execute(symbols="AAA,BBB"))
    elapsed = time.monotonic() - started
    assert elapsed < 5, elapsed
    assert out.data["status"] == "provider_unavailable"
    assert out.metadata["fallback_reason"] == "fetch_budget_exceeded"
    assert out.data["weights"] == {}


# ----------------------------- RPAR#3 route defaults ------------------------

def _route(code: str, params: dict[str, Any], monkeypatch) -> dict[str, Any]:
    load_seeds()
    # Keep the route offline: no crypto alias resolution over the network.
    monkeypatch.setattr(_agent_runtime, "resolve_crypto_symbol_alias", lambda raw, **_kw: None)
    return _agent_runtime._route_function_params(code, dict(params))


def test_route_does_not_inject_a_120_day_window_into_rpar(monkeypatch) -> None:
    routed = _route("RPAR", {"symbols": "AAA,BBB", "method": "erc"}, monkeypatch)
    assert "days" not in routed
    assert "query" not in routed
    assert "range" not in routed
    assert routed["symbols"] == "AAA,BBB"


def test_route_keeps_an_explicit_rpar_lookback(monkeypatch) -> None:
    routed = _route("RPAR", {"symbols": "AAA,BBB", "days": 252}, monkeypatch)
    assert routed["days"] == 252


# ----------------------------- RPAR#5 route universe ------------------------

def test_route_universe_replaces_the_injected_peer_group(monkeypatch) -> None:
    routed = _route("RPAR", {"universe": ["AAA", "BBB"]}, monkeypatch)
    assert routed["universe"] == ["AAA", "BBB"]
    assert "symbols" not in routed


def test_route_without_any_universe_injects_no_peer_group(monkeypatch) -> None:
    routed = _route("RPAR", {}, monkeypatch)
    assert "symbols" not in routed
    assert "symbol" not in routed


