"""ASOF-1: OMON must not compute moneyness or delta around an invented spot.

No network: the yfinance chain call is replaced by an in-memory fake.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.derivative import omon as omon_mod
from showme.engine.functions.derivative.omon import OMONFunction, _resolve_spot


class _NoDeps:
    yfinance = None


class _FailingYFinance:
    async def fetch(self, request: Any) -> Any:  # noqa: ARG002
        raise RuntimeError("quote endpoint refused")


class _DepsWithFailingQuote:
    yfinance = _FailingYFinance()


def _instrument() -> Instrument:
    return Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _chain_without_spot() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "spot": None,
        "expiry": "2030-01-17",
        "expiries": ["2030-01-17"],
        "calls": [
            {
                "strike": 200.0,
                "bid": 5.0,
                "ask": 5.5,
                "impliedVolatility": 0.30,
                "openInterest": 10,
                "volume": 3,
                "lastTradeDate": now,
            }
        ],
        "puts": [],
    }


def test_resolve_spot_returns_none_instead_of_placeholder_when_no_signal() -> None:
    spot = asyncio.run(_resolve_spot(_NoDeps(), _instrument(), {}))
    assert spot is None


def test_resolve_spot_returns_none_when_quote_fails() -> None:
    spot = asyncio.run(_resolve_spot(_DepsWithFailingQuote(), _instrument(), {}))
    assert spot is None


def test_omon_without_spot_does_not_compute_moneyness_or_delta_around_100(monkeypatch: Any) -> None:
    monkeypatch.setattr(omon_mod, "_fetch_chain_sync", lambda *_a, **_k: _chain_without_spot())
    fn = OMONFunction()
    fn.deps = _NoDeps()  # type: ignore[assignment]

    result = asyncio.run(fn.execute(instrument=_instrument()))
    data = result.data
    # No spot from any signal: an explicit provider_unavailable state with no rows,
    # so nothing is priced around a placeholder anchor (OMON honest-spot contract).
    assert data["status"] == "provider_unavailable"
    assert data["spot"] is None
    assert data["spot_source"] == "unavailable"
    assert data["rows"] == []
    assert any("spot" in w.lower() for w in result.warnings)


def test_omon_explicit_spot_param_still_computes_moneyness(monkeypatch: Any) -> None:
    monkeypatch.setattr(omon_mod, "_fetch_chain_sync", lambda *_a, **_k: _chain_without_spot())
    fn = OMONFunction()
    fn.deps = _NoDeps()  # type: ignore[assignment]

    result = asyncio.run(fn.execute(instrument=_instrument(), spot=100.0))
    assert result.data["spot"] == 100.0
    assert result.data["rows"][0]["moneyness"] == 2.0
