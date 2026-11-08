"""wc1-g36 review follow-ups: DARK stale-week total and POLY seed optionality.

No network: FINRA and yfinance are faked.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.equity.dark import DARKFunction
from showme.manifest import REGISTRY, load_seeds

import test_g3_finra_ats_window as g3


def _run(coro):
    return asyncio.run(coro)


def _stale_rows(symbol: str = "AAPL", weeks_total: int = 10) -> list[dict[str, Any]]:
    """Weekly ATS rows whose newest week is years old (FINRA stopped publishing)."""
    latest = date(2024, 1, 1)
    rows = []
    for i in range(weeks_total):
        wk = latest - timedelta(weeks=i)
        rows.append({
            "weekStartDate": wk.isoformat(),
            "issueSymbolIdentifier": symbol,
            "summaryTypeCode": "ATS_W_SMBL",
            "tierIdentifier": "T1",
            "totalWeeklyShareQuantity": 1_000_000 + i,
            "totalWeeklyTradeCount": 10_000 + i,
        })
    rows.sort(key=lambda r: r["weekStartDate"])
    return rows


class _WiredFinra:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def ats_weekly(self, symbol=None, limit=26):  # noqa: ANN001
        import pandas as pd

        return pd.DataFrame(self._rows)


def test_dark_stale_week_ships_no_off_exchange_total(monkeypatch) -> None:
    """A stale latest week is provider_unavailable with empty rows; the KPI total must be 0 too."""
    monkeypatch.setattr(DARKFunction, "_weekly_total_volume", lambda self, sym: g3._no_yfinance())

    result = _run(
        DARKFunction(deps=FunctionDeps(finra=_WiredFinra(_stale_rows()))).execute(symbol="AAPL", weeks=8)
    )
    data = result.data

    assert data["status"] == "provider_unavailable"
    assert data["venues"] == [] and data["by_week"] == []
    assert data["total_shares_off_exchange"] == 0


def test_poly_seed_topic_is_optional_because_the_pane_omits_an_empty_topic() -> None:
    """The POLY pane sends no query until a topic is typed, so the seed must not require one."""
    load_seeds()
    seed = REGISTRY.get("POLY")
    query = next(i for i in seed.inputs if i.name == "query")
    assert query.required is False
