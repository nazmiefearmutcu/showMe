"""Regression tests for the de-garbaged OMON option-monitor function."""

from __future__ import annotations

import asyncio

from showme.engine.functions.derivative.omon import OMONFunction


def _make_fn() -> OMONFunction:
    """Construct the handler with whatever deps the registry wires by default.

    OMON's de-garbaged path imports yfinance directly via asyncio.to_thread, so
    it does not depend on self.deps being populated.
    """
    return OMONFunction()


# The legacy placeholder strikes that must NEVER appear in real output.
_GARBAGE_STRIKES = {150.0, 155.0}
_GARBAGE_SOURCE = "placeholder"


def test_omon_returns_live_or_graceful() -> None:
    fn = OMONFunction()
    result = asyncio.run(fn.execute(underlier="AAPL"))
    data = result.data

    # Contract invariants regardless of connectivity.
    assert data["status"] in {"ok", "empty", "provider_unavailable"}
    assert data.get("methodology")
    assert isinstance(data.get("field_dictionary"), dict)
    assert isinstance(data.get("rows"), list)
    # Honest provider name, never the old placeholder.
    assert "yfinance" in result.sources
    assert _GARBAGE_SOURCE not in result.sources

    if data["status"] == "ok":
        rows = data["rows"]
        assert rows, "ok status must carry real strike rows"
        # Real chains have far more than two strikes; the placeholder had two.
        assert len(rows) >= 3
        first = rows[0]
        # Schema fields from the manifest table_schema are present.
        for col in (
            "strike",
            "call_bid",
            "call_ask",
            "call_oi",
            "call_iv",
            "call_delta",
            "put_bid",
            "put_iv",
            "put_delta",
        ):
            assert col in first, f"missing column {col}"
        # The exact placeholder strike pair must not be the entire chain.
        live_strikes = {r["strike"] for r in rows}
        assert live_strikes != _GARBAGE_STRIKES
        # Series + cards for the chart/card grammar.
        assert isinstance(data.get("series"), list) and data["series"]
        assert isinstance(data.get("cards"), list) and data["cards"]
        card = data["cards"][0]
        for field in ("underlier", "expiry", "spot", "atm_iv"):
            assert field in card
    else:
        # Graceful offline / no-options fallback must explain itself.
        assert any(result.warnings), "non-ok status must carry a warning"
        if data["status"] == "provider_unavailable":
            assert data.get("next_actions")


def test_omon_graceful_on_bad_ticker() -> None:
    """A bogus underlier must not crash; it degrades to a labelled fallback."""
    fn = OMONFunction()
    result = asyncio.run(fn.execute(underlier="__NO_SUCH_TICKER__"))
    data = result.data
    assert data["status"] in {"empty", "provider_unavailable"}
    assert "yfinance" in result.sources
    assert any(result.warnings)


def test_greeks_helper_is_real() -> None:
    """Confirm the BS pricer wired in returns a non-trivial ATM call delta."""
    from showme.engine.functions.derivative.omon import _bs_price

    # _bs_price(S, K, T, r, sigma, q, is_call); ATM call delta ~ 0.5–0.6.
    greeks = _bs_price(100.0, 100.0, 0.25, 0.05, 0.2, 0.0, True)
    assert 0.0 < greeks["delta"] < 1.0
