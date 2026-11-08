"""SRCH honesty: monthly-only provider answers are not a live table.

When the only provider observations that resolve are the dated monthly OECD
10Y series, no configured tenor is live. The table must then be labelled
``reference`` (``data_mode="reference"``, status ``reference``), not ``ok``,
per the H-6 rule that a no-live-tenor result never reports ``ok``.

Providers are monkeypatched at the module seam so the suite stays hermetic.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from showme.engine.functions.screen import _funcs as screen_funcs
from showme.engine.functions.screen._funcs import SRCHFunction

MONTHLY_IDS = {
    "IRLTLT01DEM156N",
    "IRLTLT01FRM156N",
    "IRLTLT01ITM156N",
    "IRLTLT01ESM156N",
    "IRLTLT01GBM156N",
    "IRLTLT01JPM156N",
}


def _frame(value: float, date_str: str = "2026-09-01") -> pd.DataFrame:
    return pd.DataFrame({"value": [value]}, index=pd.to_datetime([date_str]))


async def _monthly_only_fred(
    series_id: str,
    *,
    client: Any = None,
    timeout: float = 8.0,
    lookback_days: int | None = None,
) -> pd.DataFrame | None:
    if series_id in MONTHLY_IDS:
        return _frame(4.4771)
    return None


async def _no_quote(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("yahoo quote disabled in test")


def test_srch_monthly_only_result_is_labelled_reference(monkeypatch) -> None:
    monkeypatch.setattr(screen_funcs, "fetch_fred_csv_series", _monthly_only_fred)
    monkeypatch.setattr(screen_funcs, "fetch_quote_snapshot", _no_quote)

    result = asyncio.run(SRCHFunction().execute(query="yield >= 0", limit=50))
    rows = {row["symbol"]: row for row in result.data["rows"]}

    assert result.metadata["live_rows"] == 0
    assert result.metadata["monthly_rows"] == 6
    assert rows["DE10Y"]["quote_type"] == "monthly"
    assert result.data["status"] == "reference"
    assert result.metadata.get("data_mode") == "reference"
    assert any("monthly-reference" in warning for warning in result.warnings)
