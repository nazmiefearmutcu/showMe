"""WCRS honesty regressions (wb1-g10).

Network-free: every provider / fetcher the matrix can reach is replaced by a
spy, so a test fails loudly if a live tier is called when it must not be.
"""
from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.fx import _funcs as fx
from showme.engine.functions.fx._funcs import WCRSFunction


def _run(coro):
    return asyncio.run(coro)


def _spy_live_tiers(monkeypatch, calls: list) -> None:
    async def _frankfurter(base, quotes, **kwargs):  # noqa: ARG001
        calls.append(("frankfurter", base))
        return {q: 1.0 for q in quotes}

    async def _history(fn, symbol, params):  # noqa: ARG001
        calls.append(("history", symbol))
        return [], None

    monkeypatch.setattr(fx, "fetch_frankfurter_rates", _frankfurter)
    monkeypatch.setattr(fx, "_history_rows", _history)


# ── WCRS#3: explicit live_fx=false must switch every live tier off ────


def test_wcrs_live_fx_false_disables_every_live_tier(monkeypatch) -> None:
    calls: list = []
    _spy_live_tiers(monkeypatch, calls)

    result = _run(WCRSFunction(deps=FunctionDeps()).execute(live_fx=False))

    assert calls == [], f"live_fx=false must not reach any live tier: {calls}"
    assert result.data["source_mode"] == "reference_cross_rate_matrix"


def test_wcrs_default_still_reaches_the_live_tiers(monkeypatch) -> None:
    """Guard against a vacuous test: with no opt-out the live path runs."""
    calls: list = []
    _spy_live_tiers(monkeypatch, calls)

    _run(WCRSFunction(deps=FunctionDeps()).execute())

    assert any(kind == "frankfurter" for kind, _ in calls)
