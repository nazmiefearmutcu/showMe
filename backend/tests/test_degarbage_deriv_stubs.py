"""De-garbage regression tests for derivative _stubs HVT and IVOL.

These two functions used to return canned per-symbol constants behind an
opt-in ``live_*`` flag. The default path now fetches REAL data from
yfinance:

  * HVT  -> realized-volatility term structure from daily OHLCV closes.
  * IVOL -> implied-volatility surface from the live option chain.

The tests drive the handlers with a fake yfinance adapter that returns
real-shaped data so the computation path is exercised deterministically
offline, and also run an opportunistic live-network attempt that SKIPs
cleanly when the network is down (asserting the graceful
``provider_unavailable`` shape instead of fabricated numbers).
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.derivative._stubs import (
    HVTFunction,
    IVOLFunction,
    _vol_template,
)


def _instrument(symbol: str = "AAPL", asset: AssetClass = AssetClass.EQUITY) -> Instrument:
    try:
        return Instrument(symbol=symbol, asset_class=asset)
    except TypeError:
        try:
            return Instrument(symbol=symbol)
        except TypeError:
            return Instrument(symbol)  # type: ignore[call-arg]


# --------------------------------------------------------------------------- #
# Fake yfinance adapter
# --------------------------------------------------------------------------- #
class _FakeYF:
    """Minimal adapter exposing ``async fetch(DataRequest)``.

    Returns a real-shaped OHLCV DataFrame for HVT and a real-shaped
    option-chain dict for IVOL so the handler's own math runs end to end.
    """

    def __init__(self, *, spot: float = 187.5) -> None:
        self.spot = spot

    async def fetch(self, request: DataRequest):  # noqa: ANN001
        if request.kind == DataKind.OHLCV:
            n = 400
            # Deterministic but non-trivial return series so realized vol is
            # a real computed number, not zero and not the canned seed.
            rng = np.random.default_rng(7)
            rets = rng.normal(0.0003, 0.018, n)
            prices = self.spot * np.exp(np.cumsum(rets))
            idx = pd.date_range(
                end=datetime.now(timezone.utc), periods=n, freq="D"
            )
            return pd.DataFrame(
                {
                    "open": prices,
                    "high": prices * 1.01,
                    "low": prices * 0.99,
                    "close": prices,
                    "volume": np.full(n, 1_000_000),
                },
                index=idx,
            )
        if request.kind == DataKind.OPTIONS_CHAIN:
            expiry = request.extra.get("expiry") if request.extra else None
            if expiry is None:
                # Metadata request: hand back the underlying + expiries.
                return {
                    "underlyingPrice": self.spot,
                    "expiries": ["2026-06-19", "2026-07-17", "2026-08-21"],
                }
            strikes = [round(self.spot * m, 2) for m in (0.85, 0.95, 1.0, 1.05, 1.15)]
            calls = pd.DataFrame(
                {
                    "strike": strikes,
                    "impliedVolatility": [0.41, 0.35, 0.31, 0.34, 0.40],
                    "bid": [s * 0.05 for s in strikes],
                    "ask": [s * 0.055 for s in strikes],
                    "lastPrice": [s * 0.052 for s in strikes],
                    "volume": [120, 340, 980, 410, 150],
                    "openInterest": [1100, 2200, 5400, 2600, 1300],
                }
            )
            puts = calls.copy()
            puts["impliedVolatility"] = [0.46, 0.39, 0.34, 0.37, 0.44]
            return {"calls": calls, "puts": puts}
        return None


class _Deps:
    """Lightweight deps stub exposing only ``yfinance``.

    Any other adapter attribute resolves to ``None`` so the handlers'
    ``getattr(deps, ...)`` lookups behave like a real (mostly-empty)
    FunctionDeps without depending on its exact constructor.
    """

    def __init__(self, yfinance=None):
        self.yfinance = yfinance

    def __getattr__(self, item):  # pragma: no cover - only hit for unknowns
        return None


def _set_deps(handler, deps) -> None:
    """Assign deps defensively across BaseFunction variants.

    ``deps`` may be a plain attribute or a property backed by ``_deps``;
    try the common forms so the test does not couple to one shape.
    """
    for setter in (
        lambda: setattr(handler, "deps", deps),
        lambda: object.__setattr__(handler, "_deps", deps),
        lambda: object.__setattr__(handler, "deps", deps),
    ):
        try:
            setter()
        except Exception:
            continue
        if getattr(handler, "deps", None) is deps:
            return
    # Last resort: still try to expose it even if identity check failed.
    try:
        object.__setattr__(handler, "deps", deps)
    except Exception:
        pass


def _build(handler_cls, *, yf=None):
    handler = handler_cls()
    _set_deps(handler, _Deps(yfinance=yf))
    return handler


def _real_deps_or_skip():
    """Best-effort real deps for the opportunistic live path.

    The exact factory location varies across the engine, so probe a few
    known constructors; if none are importable, skip the live test
    instead of failing it. We never fabricate numbers here.
    """
    candidates = (
        ("showme.engine.core.engine", "build_default_deps"),
        ("showme.engine.core.base_function", "FunctionDeps"),
        ("showme.engine.core.function_deps", "FunctionDeps"),
    )
    for module_name, attr in candidates:
        try:
            module = __import__(module_name, fromlist=[attr])
            factory = getattr(module, attr, None)
        except Exception:
            continue
        if factory is None:
            continue
        try:
            deps = factory()
        except Exception:
            continue
        if getattr(deps, "yfinance", None) is not None:
            return deps
    pytest.skip("no real deps with a yfinance adapter available")


# --------------------------------------------------------------------------- #
# HVT
# --------------------------------------------------------------------------- #
def test_hvt_default_path_returns_live_realized_vol():
    handler = _build(HVTFunction, yf=_FakeYF(spot=190.0))
    result = asyncio.run(handler.execute(_instrument("AAPL")))
    data = result.data

    assert data["status"] == "ok"
    assert result.sources == ["yfinance"]
    assert data["rows"], "HVT must return realized-vol rows"
    # Real computed vol: positive, finite, and NOT the canned seed value
    # (the seed template uses samples == 0).
    canned = {r["window_days"]: r["realized_vol"] for r in _vol_template("AAPL")["rows"]}
    for row in data["rows"]:
        assert row["samples"] > 0
        assert math.isfinite(row["realized_vol"])
        assert row["realized_vol"] > 0
        assert row["realized_vol"] != canned.get(row["window_days"])
    assert data["history"], "HVT must return a rolling-vol series"
    assert "stdev(daily close-to-close returns)" in data["methodology"]
    assert data["field_dictionary"]


def test_hvt_reference_flag_still_available():
    handler = _build(HVTFunction, yf=_FakeYF())
    result = asyncio.run(handler.execute(_instrument("AAPL"), reference=True))
    assert result.data["status"] == "reference"
    assert result.metadata.get("mode") == "reference"


def test_hvt_no_adapter_falls_back_gracefully():
    handler = _build(HVTFunction, yf=None)
    result = asyncio.run(handler.execute(_instrument("AAPL")))
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert "methodology" in data
    assert result.metadata.get("fallback") is True


@pytest.mark.timeout(30)
def test_hvt_live_network_or_graceful():
    """Opportunistic live yfinance fetch; offline -> graceful shape."""
    deps = _real_deps_or_skip()
    handler = HVTFunction()
    _set_deps(handler, deps)
    try:
        result = asyncio.run(handler.execute(_instrument("AAPL")))
    except Exception as exc:  # pragma: no cover - network dependent
        pytest.skip(f"network error: {exc}")
    assert result.data["status"] in {"ok", "provider_unavailable"}
    if result.data["status"] == "ok":
        assert result.data["rows"]
        assert all(r["samples"] > 0 for r in result.data["rows"])


# --------------------------------------------------------------------------- #
# IVOL
# --------------------------------------------------------------------------- #
def test_ivol_default_path_returns_live_surface():
    handler = _build(IVOLFunction, yf=_FakeYF(spot=190.0))
    result = asyncio.run(handler.execute(_instrument("AAPL")))
    data = result.data

    assert data["status"] == "ok"
    assert result.sources == ["yfinance"]
    assert data["surface"], "IVOL must return a live surface"
    # Spot threaded from the chain underlying, not the 100 default.
    assert data["spot"] == pytest.approx(190.0)
    seen_types = {row["option_type"] for row in data["surface"]}
    assert {"CALL", "PUT"} <= seen_types
    for row in data["surface"]:
        assert math.isfinite(row["vol"])
        assert row["vol"] > 0
        assert row["moneyness"] is not None
    assert "implied volatility surface" in data["methodology"].lower()
    assert data["field_dictionary"]


def test_ivol_reference_flag_still_available():
    handler = _build(IVOLFunction, yf=_FakeYF())
    result = asyncio.run(handler.execute(_instrument("AAPL"), reference=True))
    assert result.data["status"] == "reference"
    assert result.metadata.get("mode") == "reference"


def test_ivol_no_adapter_falls_back_gracefully():
    handler = _build(IVOLFunction, yf=None)
    result = asyncio.run(handler.execute(_instrument("AAPL")))
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert data["rows"] == []
    assert result.metadata.get("fallback") is True


@pytest.mark.timeout(30)
def test_ivol_live_network_or_graceful():
    deps = _real_deps_or_skip()
    handler = IVOLFunction()
    _set_deps(handler, deps)
    try:
        result = asyncio.run(handler.execute(_instrument("AAPL")))
    except Exception as exc:  # pragma: no cover - network dependent
        pytest.skip(f"network error: {exc}")
    assert result.data["status"] in {"ok", "provider_unavailable"}
    if result.data["status"] == "ok":
        assert result.data["surface"]
        assert all(r["vol"] > 0 for r in result.data["surface"])
