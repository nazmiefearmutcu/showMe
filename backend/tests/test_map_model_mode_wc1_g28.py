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
