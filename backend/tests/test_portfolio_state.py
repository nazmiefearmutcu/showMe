from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.portfolio.state import PortfolioState  # noqa: E402
from showme.engine.functions.portfolio.port import PORTFunction  # noqa: E402


def test_import_legacy_crypto_carries_current_price_and_updates_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # bughunt 2026-05-24: legacy mirror is now opt-in. Explicit opt-in
    # preserves the original contract this test pins.
    monkeypatch.setenv("SHOWME_IMPORT_LEGACY_TBV3", "1")
    state_path = tmp_path / "state.json"
    portfolio_path = tmp_path / "portfolio.json"
    state_path.write_text(json.dumps({
        "positions": {
            "4USDT": {
                "symbol": "4USDT",
                "entry_price": 0.010289,
                "quantity": 442835.2730583,
                "current_price": 0.009671,
                "open_time": "2026-04-27T15:44:27.267875+00:00",
                "current_signal": "NEUTRAL",
            },
        },
    }))

    portfolio = PortfolioState(portfolio_path)
    assert portfolio.import_legacy_crypto(state_path) == 1
    position = portfolio.positions[0]
    assert position.instrument.symbol == "4USDT"
    assert position.instrument.metadata["current_price"] == 0.009671
    assert position.instrument.metadata["current_signal"] == "NEUTRAL"

    state_path.write_text(json.dumps({
        "positions": {
            "4USDT": {
                "symbol": "4USDT",
                "entry_price": 0.010289,
                "quantity": 442835.2730583,
                "current_price": 0.01231,
            },
        },
    }))

    assert portfolio.import_legacy_crypto(state_path) == 0
    assert portfolio.positions[0].instrument.metadata["current_price"] == 0.01231


def test_port_uses_legacy_current_price_for_crypto_positions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # bughunt 2026-05-24: legacy mirror is now opt-in.
    monkeypatch.setenv("SHOWME_IMPORT_LEGACY_TBV3", "1")
    state_path = tmp_path / "state.json"
    portfolio_path = tmp_path / "portfolio.json"
    state_path.write_text(json.dumps({
        "positions": {
            "4USDT": {
                "symbol": "4USDT",
                "entry_price": 0.010289,
                "quantity": 100.0,
                "current_price": 0.01231,
            },
        },
    }))
    portfolio = PortfolioState(portfolio_path)
    portfolio.import_legacy_crypto(state_path)

    result = asyncio.run(PORTFunction().execute(_portfolio_override=portfolio))

    row = result.data["positions"][0]
    assert row["symbol"] == "4USDT"
    assert row["last"] == 0.01231
    assert row["market_value"] == pytest.approx(1.231)
    assert result.sources == ["portfolio_state"]


def test_corrupt_portfolio_file_backed_up_and_save_refused(tmp_path: Path) -> None:
    """F5: a corrupt portfolio.json must not be silently wiped and persisted.

    Load failure → corrupt copy saved next to the original + degraded flag set
    + save() refuses to write the empty in-memory book over the recoverable
    file. A healthy file loads with degraded=False as before.
    """
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text('{"positions": [THIS IS NOT JSON')

    portfolio = PortfolioState(portfolio_path)
    assert portfolio.degraded is True
    assert portfolio.degraded_reason
    assert portfolio.positions == []

    backups = list(tmp_path.glob("portfolio.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == '{"positions": [THIS IS NOT JSON'

    before = portfolio_path.read_text()
    portfolio.save()  # must be a logged no-op while degraded
    assert portfolio_path.read_text() == before

    healthy = PortfolioState(tmp_path / "ok.json")
    assert healthy.degraded is False
    healthy.save()
    assert (tmp_path / "ok.json").exists()
