"""Regression tests for bughunt 2026-05-24 Theme 1 (Bug #1 / A7-C1).

The legacy TBV3 paper-trading bot stores ~51 positions in
``~/Library/Application Support/showMe/runtime/state.json``. Until this fix
the showMe portfolio engine read that file unconditionally via
``PortfolioState.import_legacy_crypto()``, leaking $590K of phantom positions
into PORT/ACCT/PVAR/STRS even on a fresh install with no broker connected.

This violates the [showMe exchanges work isolates TBV3] memory note that
mandates ZERO structural connection to TBV3.

Fix: the import is now gated behind ``SHOWME_IMPORT_LEGACY_TBV3`` (default
OFF). When off, ``PORTFunction.execute()`` returns a structured empty state
with ``connected_exchanges: 0`` so the UI banner matches the data.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from showme.engine.functions.portfolio.port import PORTFunction
from showme.engine.portfolio.state import (
    _LEGACY_IMPORT_ENV,
    PortfolioState,
)


def _write_legacy_state(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "positions": {
                    "PHANTOMUSDT": {
                        "symbol": "PHANTOMUSDT",
                        "entry_price": 0.5,
                        "quantity": 100.0,
                        "current_price": 0.6,
                    },
                    "GHOST2USDT": {
                        "symbol": "GHOST2USDT",
                        "entry_price": 1.0,
                        "quantity": 50.0,
                        "current_price": 1.2,
                    },
                }
            }
        )
    )


def test_import_legacy_crypto_off_by_default_returns_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No env var = no leak, even when state.json exists with positions."""
    monkeypatch.delenv(_LEGACY_IMPORT_ENV, raising=False)
    state_path = tmp_path / "state.json"
    portfolio_path = tmp_path / "portfolio.json"
    _write_legacy_state(state_path)

    portfolio = PortfolioState(portfolio_path)
    assert portfolio.import_legacy_crypto(state_path) == 0
    assert portfolio.positions == []


def test_import_legacy_crypto_off_explicit_false_returns_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit false-y values (0, false, no, off) are honoured."""
    state_path = tmp_path / "state.json"
    portfolio_path = tmp_path / "portfolio.json"
    _write_legacy_state(state_path)

    for falsy in ("", "0", "false", "no", "off", "False", "NO"):
        monkeypatch.setenv(_LEGACY_IMPORT_ENV, falsy)
        portfolio = PortfolioState(portfolio_path)
        assert portfolio.import_legacy_crypto(state_path) == 0, (
            f"value {falsy!r} should disable legacy import"
        )
        assert portfolio.positions == []


def test_import_legacy_crypto_on_with_env_flag_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the flag is set the legacy mirror works as before."""
    state_path = tmp_path / "state.json"
    _write_legacy_state(state_path)

    # Use indexed paths instead of {truthy} so case-insensitive APFS doesn't
    # collide "portfolio-true.json" with "portfolio-TRUE.json" (which would
    # carry state across iterations and break the per-value assertion).
    for idx, truthy in enumerate(("1", "true", "yes", "on", "TRUE", "YES")):
        monkeypatch.setenv(_LEGACY_IMPORT_ENV, truthy)
        portfolio = PortfolioState(tmp_path / f"portfolio-{idx}.json")
        added = portfolio.import_legacy_crypto(state_path)
        assert added == 2, f"value {truthy!r} should enable legacy import"
        symbols = sorted(p.instrument.symbol for p in portfolio.positions)
        assert symbols == ["GHOST2USDT", "PHANTOMUSDT"]


def test_port_function_empty_state_when_legacy_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PORT must report connected_exchanges=0 + empty totals when the flag is off.

    Even if the TBV3 state.json exists at the runtime path the engine would
    normally read from, PORTFunction.execute() must return the ready_no_positions
    payload with zeroed totals so the UI banner "Bağlı borsa yok" makes sense.
    """
    monkeypatch.delenv(_LEGACY_IMPORT_ENV, raising=False)
    # Point both the legacy state.json AND the portfolio.json under tmp via
    # SHOWME_HOME so neither call can reach the user's real ~/Library state.
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    _write_legacy_state(runtime / "state.json")

    result = asyncio.run(PORTFunction().execute())

    assert result.data["status"] == "ready_no_positions"
    assert result.data["connected_exchanges"] == 0
    assert result.data["positions"] == []
    totals = result.data["totals"]
    assert totals == {
        "market_value": 0.0,
        "n_positions": 0,
        "unrealized_pnl": 0.0,
    }
    # Provenance + empty flag carried through.
    assert result.sources == ["portfolio_state"]
    assert result.metadata["empty"] is True
    assert result.metadata["requires_positions"] is True


def test_port_function_legacy_visible_when_flag_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity check: opt-in path must still mirror legacy positions through PORT."""
    monkeypatch.setenv(_LEGACY_IMPORT_ENV, "1")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    _write_legacy_state(runtime / "state.json")

    result = asyncio.run(PORTFunction().execute())

    rows = result.data["positions"]
    symbols = sorted(r["symbol"] for r in rows)
    assert symbols == ["GHOST2USDT", "PHANTOMUSDT"]
    assert result.data["totals"]["n_positions"] == 2
