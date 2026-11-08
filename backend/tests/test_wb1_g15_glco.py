"""WB1-G15 — GLCO honest open-interest / contract-month fields and timeout parsing (offline).

* GLCO#3 — open interest and contract month are explicit ``None`` with a
  reason on every row (live and model), never blank or the description.
* GLCO#5 — non-numeric timeout params fall back to the default instead of
  raising.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.commodity import _funcs as commodity


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ── GLCO#3: explicit n/a for OI and contract month ──────────────────────────


def _glco_snapshot_row(symbol: str) -> dict[str, Any]:
    meta = commodity.COMMODITY_CONTRACTS[symbol]
    return {
        "symbol": symbol,
        "name": meta["name"],
        "sector": meta["sector"],
        "contract": meta["contract"],
        "unit": meta["unit"],
        "exchange": meta["exchange"],
        "last": 10.0,
        "prev": 9.0,
        "change": 1.0,
        "change_pct": 11.11,
        "open": None,
        "high": None,
        "low": None,
        "volume": None,
        "source": "yfinance",
        "source_mode": "live_yfinance",
        "as_of": "2026-11-06T00:00:00+00:00",
    }


async def _no_history(symbol: str, timeout: float, *, range_: str = "3mo") -> list[dict[str, Any]]:
    return []


def test_glco_live_rows_state_open_interest_and_contract_month_explicitly(monkeypatch: Any) -> None:
    async def _snapshot(yfinance: Any, symbol: str, *, days: int, timeout: float, include_history: bool) -> Any:
        return _glco_snapshot_row(symbol), [], []

    monkeypatch.setattr(commodity, "_contract_snapshot", _snapshot)
    monkeypatch.setattr(commodity, "_yahoo_chart_ohlcv", _no_history)
    res = _run(commodity.GLCOFunction(deps=FunctionDeps(yfinance=object())).execute())
    rows = res.data["rows"]
    assert len(rows) == 14
    for row in rows:
        assert "open_interest" in row and row["open_interest"] is None
        assert row["open_interest_reason"]
        assert "contract_month" in row and row["contract_month"] is None
        assert row["contract_month_reason"]
        # The description stays as metadata; it is no longer the contract month.
        assert row["contract"]


def test_glco_model_rows_state_open_interest_and_contract_month_explicitly() -> None:
    res = _run(commodity.GLCOFunction(deps=FunctionDeps()).execute())
    assert res.data["status"] == "provider_unavailable"
    assert res.data["rows"]
    for row in res.data["rows"]:
        assert row["open_interest"] is None and row["open_interest_reason"]
        assert row["contract_month"] is None and row["contract_month_reason"]


# ── GLCO#5: bad timeout params fall back to defaults ────────────────────────


@pytest.mark.parametrize(
    "bad",
    ["abc", None, "nan", "inf", [1, 2]],
)
def test_glco_timeout_params_fall_back_to_defaults_on_bad_input(monkeypatch: Any, bad: Any) -> None:
    seen: list[float] = []

    async def _snapshot(yfinance: Any, symbol: str, *, days: int, timeout: float, include_history: bool) -> Any:
        seen.append(timeout)
        return None, [], []

    monkeypatch.setattr(commodity, "_contract_snapshot", _snapshot)
    monkeypatch.setattr(commodity, "_yahoo_chart_ohlcv", _no_history)
    res = _run(
        commodity.GLCOFunction(deps=FunctionDeps(yfinance=object())).execute(
            quote_timeout=bad, screen_timeout=bad,
        )
    )
    assert res.data["status"] == "provider_unavailable"
    assert seen, "quote pass must still run"
    # quote_timeout default 2.0 (clamped to [1, 4]).
    assert all(t == 2.0 for t in seen)
