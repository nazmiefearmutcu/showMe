"""ANR#1 - yfinance recommendation periods must never be dated to the request day.

yfinance ``recommendations_summary`` carries only period labels (``0m``,
``-1m``, ``-2m``, ``-3m``) and no calendar dates. The legacy
``_date_from_row`` mapped ``0m`` to *today*, so the consensus, the target
price and ``source_details.asOf`` all claimed the request date as their
as-of date (a false freshness claim). Only dated ``upgrades_downgrades``
rows may supply a date.

The test drives ``ANRFunction.execute`` with the yfinance adapter replaced by
an offline fake (no network).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.anr import ANRFunction, _date_from_row


# Dated broker action, a few days before the run date. Relative so the
# 365-day stale cutoff never drops it on a later run.
_ACTION_DAY = (datetime.now(timezone.utc) - timedelta(days=4)).date().isoformat()

_RAW: dict[str, Any] = {
    "currentPrice": 200.0,
    "targetHighPrice": 280.0,
    "targetLowPrice": 180.0,
    "targetMeanPrice": 240.0,
    "targetMedianPrice": 238.0,
    "recommendations_summary": [
        {"period": "0m", "strongBuy": 10, "buy": 12, "hold": 8, "sell": 1, "strongSell": 0},
        {"period": "-1m", "strongBuy": 9, "buy": 11, "hold": 9, "sell": 1, "strongSell": 0},
        {"period": "-2m", "strongBuy": 9, "buy": 10, "hold": 9, "sell": 2, "strongSell": 0},
        {"period": "-3m", "strongBuy": 8, "buy": 10, "hold": 10, "sell": 2, "strongSell": 0},
    ],
    "upgrades_downgrades": [
        {
            "GradeDate": f"{_ACTION_DAY}T00:00:00",
            "Firm": "Example Research",
            "ToGrade": "Buy",
            "FromGrade": "Hold",
            "Action": "up",
            "priceTargetAction": "Raises",
            "currentPriceTarget": 250.0,
            "priorPriceTarget": 230.0,
        },
    ],
}


class _FakeYFinance:
    async def fetch(self, request: Any) -> Any:  # noqa: ARG002 - adapter protocol
        return SimpleNamespace(extras={"raw": _RAW})


def _run_anr() -> Any:
    fn = ANRFunction(deps=FunctionDeps(yfinance=_FakeYFinance()))
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(fn.execute(instrument=instrument))


def test_period_label_is_not_mapped_to_a_calendar_date() -> None:
    """A relative period label carries no date; it must not become 'today'."""
    assert _date_from_row({"period": "0m"}) is None
    assert _date_from_row({"period": "-1m"}) is None


def test_consensus_as_of_is_not_fabricated_from_request_date() -> None:
    result = _run_anr()
    today = datetime.now(timezone.utc).date().isoformat()
    summary = result.data["summary"]
    assert summary["last_updated"] != today, (
        f"consensus dated to the request day {today}; the yfinance summary has no dates"
    )
    assert summary["last_updated"] is None
    assert summary["oldest_included_rating_date"] is None


def test_target_price_as_of_is_not_fabricated_from_request_date() -> None:
    result = _run_anr()
    today = datetime.now(timezone.utc).date().isoformat()
    target = result.data["price_target"]
    assert target.get("lastUpdated") != today
    assert target.get("lastUpdated") is None
    details = {d["name"]: d for d in result.data["source_details"]}
    assert details["target_price"]["asOf"] != today
    assert details["target_price"]["asOf"] is None
    consensus_detail = result.data["source_details"][0]
    assert consensus_detail["asOf"] != today
    assert consensus_detail["asOf"] is None


def test_latest_real_rating_action_date_comes_from_dated_upgrades_rows() -> None:
    result = _run_anr()
    summary = result.data["summary"]
    assert summary["latest_rating_action_date"] == _ACTION_DAY


def test_consensus_uses_current_period_row_only() -> None:
    """The undated summary keeps the 0m (current) row as the consensus."""
    result = _run_anr()
    assert result.data["summary"]["analyst_count"] == 10 + 12 + 8 + 1 + 0
