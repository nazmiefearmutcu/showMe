"""PORT_WHATIF — no placeholder cost may be reported as a real P&L.

Finding PORT_WHATIF#1: the pane pre-filled Entry with 100 for every symbol and
the backend defaulted cost to 0, so AAPL at ~342 showed a hypothetical gain of
+24k that existed only because of the placeholder. A missing cost must return
an explicit needs_input state; an explicit cost must still compute the delta.

Offline: the portfolio state and the PORT analytics are replaced by fakes.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest  # noqa: E402

from showme.engine.core.base_function import FunctionDeps, FunctionResult  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.functions.portfolio import _more as more_mod  # noqa: E402
from showme.engine.functions.portfolio import port as port_mod  # noqa: E402

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _FakeState:
    def __init__(self, path=None):
        self.positions = []
        self.cash = {}

    def import_legacy_crypto(self):
        return 0


class _FakePort:
    """PORT stand-in: the book value moves with the position added."""

    def __init__(self, deps=None):
        self.deps = deps

    async def execute(self, _portfolio_override=None, **_params):
        held = bool(getattr(_portfolio_override, "positions", []))
        totals = {"market_value": 0.0, "unrealized_pnl": 0.0, "n_positions": 0}
        if held:
            totals = {"market_value": 342.37 * 100, "unrealized_pnl": 0.0, "n_positions": 1}
        return FunctionResult(code="PORT", instrument=None, data={"totals": totals},
                              sources=["fake_portfolio"])


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(more_mod, "PortfolioState", _FakeState)
    monkeypatch.setattr(port_mod, "PORTFunction", _FakePort)


def _run(params: dict) -> FunctionResult:
    fn = more_mod.PORTWhatIfFunction(FunctionDeps())
    return asyncio.run(fn.execute(instrument=AAPL, **params))


def test_missing_cost_does_not_fabricate_pnl() -> None:
    result = _run({"quantity": 100})
    # Before the fix: status was absent and summary reported cost 0.0 with a
    # fabricated unrealized_pnl_delta.
    assert result.data.get("status") == "needs_input"
    assert "summary" not in result.data
    assert "cost" in result.data.get("missing", [])


def test_blank_or_zero_quantity_is_not_a_trade() -> None:
    result = _run({"cost": 342.37})
    assert result.data.get("status") == "needs_input"
    assert "quantity" in result.data.get("missing", [])


def test_non_numeric_cost_is_input_error() -> None:
    result = _run({"quantity": 100, "cost": "abc"})
    assert result.data.get("status") == "input_error"


def test_explicit_cost_still_computes_delta() -> None:
    result = _run({"quantity": 100, "cost": 342.37})
    assert result.data.get("status") in (None, "ok")
    assert result.data["summary"]["cost"] == pytest.approx(342.37)
    assert result.data["summary"]["market_value_delta"] == pytest.approx(34237.0)
