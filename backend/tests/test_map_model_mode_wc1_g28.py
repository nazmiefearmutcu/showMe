"""MAP model mode carries no numbers (wc1-g28, MAP#3).

live=false used to return a fixed pattern (last = 50 + 1.7*i, change from a
repeating cycle). Those numbers look like prices, so the model now lists the
country/ETF map with null last and change_pct, labelled quote_type="model".
Offline: no quote is fetched in model mode.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.screen import wmap


def test_model_mode_emits_no_prices_or_changes() -> None:
    res = asyncio.run(wmap.MAPFunction(FunctionDeps()).execute(live=False))
    assert res.data["status"] == "model"
    assert res.sources == ["world_market_model"]
    rows = res.data["rows"]
    assert len(rows) == len(wmap._COUNTRY_ETFS)
    assert all(row["quote_type"] == "model" for row in rows)
    assert all(row["last"] is None for row in rows)
    assert all(row["change_pct"] is None for row in rows)
    assert "not live" in res.data["reason"]


def test_provider_outage_next_actions_do_not_call_model_deterministic(monkeypatch) -> None:
    """MAP#3 follow-up: the model carries no numbers, so the outage hint must
    not describe it as a deterministic price model."""

    async def _boom(symbol: str) -> dict:
        raise RuntimeError("quote service down")

    monkeypatch.setattr(wmap, "fetch_quote_snapshot", _boom)
    res = asyncio.run(wmap.MAPFunction(FunctionDeps()).execute(live=True, screen_timeout=4))
    assert res.data["status"] == "provider_unavailable"
    actions = res.data["next_actions"]
    assert actions
    assert not any("deterministic" in action.lower() for action in actions), actions
    assert any("without prices" in action for action in actions), actions
