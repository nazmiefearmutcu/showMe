"""Regression tests for bughunt 2026-05-24 Theme 1 (Bug #14 / A7-C3).

GET ``/api/fn/PORT_OPT?symbols=AAPL,MSFT,NVDA`` arrived as a Python string,
which the function then iterated character-by-character into
``["A", "P", "S"]``. Same bug in BMTX. BLAK + RPAR already had the guard.

Fix: mirror the ``isinstance(str)`` split-and-strip guard from BLAK/RPAR
into PORT_OPT and BMTX so a comma-separated string is normalized to a list
before any downstream iteration.
"""

from __future__ import annotations

import asyncio


from showme.engine.functions.portfolio.bmtx import BMTXFunction
from showme.engine.functions.portfolio.port_opt import PortOptFunction


def test_port_opt_normalizes_comma_separated_string() -> None:
    """Stringified GET param expands to the full symbol list."""
    # `live=False` short-circuits the yfinance fan-out and exercises the
    # template path that downstream code shares with the live path. The
    # surfaced ``symbols`` list is the same one BLAK/RPAR were already
    # honouring, so any character-by-character iteration regresses here.
    result = asyncio.run(
        PortOptFunction().execute(symbols="AAPL,MSFT,NVDA")
    )
    assert sorted(result.data["symbols"]) == ["AAPL", "MSFT", "NVDA"]


def test_port_opt_normalizes_crypto_symbols_with_spaces() -> None:
    """Whitespace is trimmed exactly like BLAK does."""
    result = asyncio.run(
        PortOptFunction().execute(symbols="BTCUSDT, ETHUSDT ,SOLUSDT")
    )
    assert sorted(result.data["symbols"]) == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def test_port_opt_accepts_list_input_unchanged() -> None:
    """List inputs (the non-buggy path) keep working."""
    result = asyncio.run(
        PortOptFunction().execute(symbols=["AAPL", "MSFT", "NVDA"])
    )
    assert sorted(result.data["symbols"]) == ["AAPL", "MSFT", "NVDA"]


def test_port_opt_pre_fix_repro_would_explode_string() -> None:
    """Negative assertion: the broken behaviour ``["A","P","S"]`` must not return."""
    result = asyncio.run(
        PortOptFunction().execute(symbols="AAPL,MSFT,NVDA")
    )
    assert "A" not in result.data["symbols"]
    assert "P" not in result.data["symbols"]
    assert "S" not in result.data["symbols"]


def test_bmtx_normalizes_comma_separated_string() -> None:
    """BMTX must apply the same fix as PORT_OPT."""
    # `live=False` returns the matrix template but it still echoes the
    # caller's symbol list verbatim, so a string-shred bug shows up here.
    result = asyncio.run(
        BMTXFunction().execute(symbols="AAPL,MSFT,NVDA")
    )
    assert sorted(result.data["symbols"]) == ["AAPL", "MSFT", "NVDA"]


def test_bmtx_normalizes_strategies_string() -> None:
    """BMTX also splits a stringified ``strategies`` param so the matrix is sane."""
    result = asyncio.run(
        BMTXFunction().execute(
            symbols="AAPL,MSFT",
            strategies="sma_crossover,rsi_meanrev",
        )
    )
    strategies = result.data["strategies"]
    assert "sma_crossover" in strategies
    assert "rsi_meanrev" in strategies
    # And confirm the shred didn't happen for either input.
    assert "s" not in strategies
    assert "m" not in strategies


def test_bmtx_accepts_list_unchanged() -> None:
    """List inputs continue to work."""
    result = asyncio.run(
        BMTXFunction().execute(symbols=["AAPL", "MSFT"])
    )
    assert sorted(result.data["symbols"]) == ["AAPL", "MSFT"]
