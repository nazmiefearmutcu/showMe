"""Regression tests for bughunt 2026-05-24 Theme 1 (Bug #13 / A7-C6).

BLAK's Black-Litterman prior previously used dollar trading volume as a
``market_weight`` proxy. For crypto that pushed BTC to ~99.99% and ETH to
~0.00003%, breaking the implied-returns math.

Fix: resolve real market cap (circulating supply * price) via the
CoinGecko adapter for crypto, yfinance REFDATA for equity. When real mcap
is unavailable for all symbols, fall back to equal weight with
``market_cap_data_state="approximate"`` so the UI can warn.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.blak import (
    BLAKFunction,
    _resolve_market_caps,
)


class _StubCoinGecko:
    """Bare-minimum CoinGecko shim — only the `quote()` shape BLAK uses."""

    def __init__(self, mcap_by_symbol: dict[str, float]) -> None:
        self._mcap_by_symbol = mcap_by_symbol
        self.calls: list[str] = []

    async def quote(self, symbol: str, vs: str = "usd") -> dict[str, Any]:
        self.calls.append(symbol)
        mcap = self._mcap_by_symbol.get(symbol.upper())
        if mcap is None:
            return {}
        return {"usd": 1.0, "usd_market_cap": mcap, "usd_24h_vol": 1.0}


@dataclass
class _StubRefData:
    market_cap: float | None = None


class _StubYf:
    """yfinance REFDATA stub for equity mcap lookup."""

    def __init__(self, mcap_by_symbol: dict[str, float]) -> None:
        self._mcap_by_symbol = mcap_by_symbol

    async def fetch(self, request: Any) -> Any:
        sym = request.instrument.symbol.upper()
        return _StubRefData(market_cap=self._mcap_by_symbol.get(sym))


def test_resolve_market_caps_uses_coingecko_for_crypto() -> None:
    """Crypto symbols route through the CoinGecko adapter, not yfinance."""
    gecko = _StubCoinGecko(
        {"BTCUSDT": 1_600_000_000_000.0, "ETHUSDT": 280_000_000_000.0}
    )
    deps = FunctionDeps(coingecko=gecko)
    lookup, state, sources = asyncio.run(
        _resolve_market_caps(deps, ["BTCUSDT", "ETHUSDT"], {})
    )
    assert lookup == {
        "BTCUSDT": 1_600_000_000_000.0,
        "ETHUSDT": 280_000_000_000.0,
    }
    assert state == "real"
    assert sources == ["coingecko"]
    # Both symbols actually hit the adapter rather than being collapsed onto one.
    assert sorted(gecko.calls) == ["BTCUSDT", "ETHUSDT"]


def test_resolve_market_caps_overrides_short_circuit() -> None:
    """When the user passes ``market_caps`` overrides we use them verbatim."""
    deps = FunctionDeps()
    lookup, state, sources = asyncio.run(
        _resolve_market_caps(deps, ["BTCUSDT", "ETHUSDT"], {
            "BTCUSDT": 1.5e12, "ETHUSDT": 3e11,
        })
    )
    assert lookup == {"BTCUSDT": 1.5e12, "ETHUSDT": 3e11}
    assert state == "real"
    assert sources == []  # zero provider hits


def test_resolve_market_caps_no_provider_returns_approximate() -> None:
    """No CoinGecko adapter + no yfinance => approximate fallback."""
    deps = FunctionDeps()  # everything None
    lookup, state, sources = asyncio.run(
        _resolve_market_caps(deps, ["BTCUSDT", "ETHUSDT"], {})
    )
    assert lookup == {}
    assert state == "approximate"
    assert sources == []


def test_blak_weights_match_real_mcap_ratio() -> None:
    """End-to-end: BLAK must build weights from real mcaps, not dollar volume.

    Prior to the fix BTC took 99.99% of the prior. With real mcaps (BTC ~5x
    ETH here) the weight ratio reflects the true share.
    """
    gecko = _StubCoinGecko(
        {"BTCUSDT": 1_500_000_000_000.0, "ETHUSDT": 300_000_000_000.0}
    )
    deps = FunctionDeps(coingecko=gecko)
    func = BLAKFunction(deps=deps)
    result = asyncio.run(func.execute(symbols=["BTCUSDT", "ETHUSDT"]))

    weights = result.data["market_weights"]
    assert pytest.approx(weights["BTCUSDT"], rel=1e-9) == 1_500 / 1_800
    assert pytest.approx(weights["ETHUSDT"], rel=1e-9) == 300 / 1_800
    assert result.data["market_cap_data_state"] == "real"
    # Provenance now exposes coingecko alongside the return-source.
    assert "coingecko" in result.sources


def test_blak_falls_back_to_equal_weight_with_warning_when_mcap_missing() -> None:
    """No adapter => equal weight + warning + ``approximate`` data_state."""
    deps = FunctionDeps()  # no coingecko, no yfinance
    func = BLAKFunction(deps=deps)
    result = asyncio.run(func.execute(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"]))

    weights = result.data["market_weights"]
    # Equal-weight prior across 3 symbols.
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        assert pytest.approx(weights[sym], rel=1e-9) == 1 / 3
    assert result.data["market_cap_data_state"] == "approximate"
    assert any(
        "market_weight" in w and "approximate" not in w.lower()
        or "equal-weight" in w
        for w in result.warnings
    )


def test_blak_overrides_skip_provider() -> None:
    """Caller-supplied ``market_caps`` short-circuit the provider hop entirely."""
    gecko = _StubCoinGecko({"BTCUSDT": 1.0, "ETHUSDT": 1.0})  # would set 50/50
    deps = FunctionDeps(coingecko=gecko)
    func = BLAKFunction(deps=deps)
    result = asyncio.run(
        func.execute(
            symbols=["BTCUSDT", "ETHUSDT"],
            market_caps={"BTCUSDT": 800.0, "ETHUSDT": 200.0},
        )
    )
    weights = result.data["market_weights"]
    assert pytest.approx(weights["BTCUSDT"], rel=1e-9) == 0.8
    assert pytest.approx(weights["ETHUSDT"], rel=1e-9) == 0.2
    assert gecko.calls == []  # provider never hit
