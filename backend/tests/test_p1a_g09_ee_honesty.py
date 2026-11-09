"""EE#1 / EE#2 regressions.

EE#1: the provider returns the not-yet-reported quarter first (actual null,
consensus only). The pane took rows[0] as the last reported quarter, so the
"Last actual" KPI showed a dash and "Last estimate" showed the upcoming
consensus. The backend now separates the upcoming report into
``next_report`` and keeps ``rows`` to what has been reported or is unknown.

EE#2: ``reference=true`` used to serve invented FY-quarter EPS figures with a
surprise % that did not match actual/estimate and ``synthetic: False``. It must
now return an explicit empty state with no figures.

All tests are offline: the Finnhub and yfinance legs are fakes.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.functions.equity.ee import EEFunction  # noqa: E402

EQ = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _FakeFinnhub:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def _get(self, path: str, **kwargs: Any) -> list[dict[str, Any]]:
        assert path == "/stock/earnings"
        return self._rows


class _NoYf:
    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("yfinance disabled in unit tests")


def _run(coro):
    return asyncio.run(coro)


def _future_iso(days: int = 90) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def test_upcoming_unreported_quarter_is_not_reported_as_last_actual() -> None:
    fut = _future_iso()
    deps = FunctionDeps()
    deps.finnhub = _FakeFinnhub([
        {"period": fut, "actual": None, "estimate": 2.92, "surprisePercent": None},
        {"period": "2026-09-30", "actual": 2.10, "estimate": 1.99, "surprisePercent": 5.53},
        {"period": "2026-06-30", "actual": 1.65, "estimate": 1.60, "surprisePercent": 3.13},
    ])
    deps.yfinance = _NoYf()
    result = _run(EEFunction(deps).execute(instrument=EQ))
    rows = result.data["rows"]

    # The reported rows must lead; the upcoming quarter is not a reported row.
    assert rows[0]["actual"] == 2.10, rows
    assert all(r["period"] != fut for r in rows), rows
    # The upcoming report is still surfaced, separately, with its date.
    assert result.data["next_report"] is not None
    assert result.data["next_report"]["date"] == fut
    assert result.data["next_report"]["estimate"] == 2.92


def test_upcoming_row_does_not_consume_history_window() -> None:
    fut = _future_iso()
    deps = FunctionDeps()
    deps.finnhub = _FakeFinnhub(
        [{"period": fut, "actual": None, "estimate": 2.92, "surprisePercent": None}]
        + [
            {"period": f"2026-{m:02d}-28", "actual": 1.0 + m / 100, "estimate": 0.9,
             "surprisePercent": 1.0}
            for m in (9, 6, 3, 12)
        ]
    )
    deps.yfinance = _NoYf()
    result = _run(EEFunction(deps).execute(instrument=EQ, history=4))
    assert len(result.data["rows"]) == 4
    assert all(r["actual"] is not None for r in result.data["rows"])


def test_reference_mode_serves_no_fabricated_figures() -> None:
    result = _run(EEFunction(FunctionDeps()).execute(instrument=EQ, reference=True))
    data = result.data
    assert data["rows"] == []
    assert data["status"] != "ok"
    assert result.metadata.get("live") is False
    # Explicit empty state: no figures, no provider source, and no data mode
    # other than "empty" is claimed. (A bare "synthetic is not False" check
    # passes whenever the key is absent, so it proved nothing.)
    assert data["status"] == "empty"
    assert data["reason"] == "reference_mode_has_no_figures"
    assert result.metadata.get("data_mode") == "empty"
    assert result.sources == []
    assert result.warnings, "reference mode must say why there are no figures"


def test_reference_mode_has_no_invented_surprise_values() -> None:
    result = _run(EEFunction(FunctionDeps()).execute(instrument=EQ, reference=True))
    for key in ("rows", "earnings", "earnings_dates"):
        for row in result.data.get(key) or []:
            assert row.get("actual") is None
            assert row.get("estimate") is None
            assert row.get("surprisePercent") is None
