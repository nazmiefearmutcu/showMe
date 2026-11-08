"""EE#3 / EE#4 / EE#5 regressions (wc1-g50).

EE#3: when no provider answers, the placeholder row is returned but
``data.status`` was hard-coded ``"ok"``. It must carry the honest
``provider_unavailable`` state.

EE#4: a failing provider's error was wiped (``warnings = []``) as soon as
another provider answered, and a provider was listed in ``sources`` before its
data was confirmed. Provider errors must stay visible and only providers that
actually returned data may be listed.

EE#5: the description promises a next report date, but ``next_report`` ignored
the yfinance calendar and could disagree with the earnings-dates table. The
calendar's forward date is now the reconciled source, with a warning when the
two providers disagree.

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
    def __init__(self, rows: list[dict[str, Any]] | None = None, error: Exception | None = None) -> None:
        self._rows = rows
        self._error = error

    async def _get(self, path: str, **kwargs: Any) -> list[dict[str, Any]]:
        assert path == "/stock/earnings"
        if self._error is not None:
            raise self._error
        return self._rows or []


class _FakeYf:
    def __init__(self, payload: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self._payload = payload or {}
        self._error = error

    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        if self._error is not None:
            raise self._error
        return self._payload


class _NoYf:
    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("yfinance disabled in unit tests")


def _run(coro):
    return asyncio.run(coro)


def _future_iso(days: int = 90) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


# ── EE#3 ────────────────────────────────────────────────────────────────


def test_ee_placeholder_path_reports_provider_unavailable_status() -> None:
    deps = FunctionDeps(finnhub=_FakeFinnhub(error=RuntimeError("boom")), yfinance=_FakeYf(error=RuntimeError("boom")))
    result = _run(EEFunction(deps).execute(instrument=EQ))
    assert result.data["rows"][0]["period"] == "provider_unavailable"
    assert result.data["status"] == "provider_unavailable", result.data["status"]
    assert result.metadata.get("live") is False
    assert result.metadata.get("fallback") is True


def test_ee_no_providers_wired_reports_provider_unavailable_status() -> None:
    result = _run(EEFunction(FunctionDeps()).execute(instrument=EQ))
    assert result.data["status"] == "provider_unavailable", result.data["status"]


# ── EE#4 ────────────────────────────────────────────────────────────────


def test_ee_provider_error_survives_when_other_provider_answers() -> None:
    earnings = pd.DataFrame(
        {
            "Earnings Date": [pd.Timestamp("2026-09-30")],
            "EPS Estimate": [1.99],
            "Reported EPS": [2.10],
            "Surprise(%)": [5.53],
        }
    ).set_index("Earnings Date")
    deps = FunctionDeps(
        finnhub=_FakeFinnhub(error=RuntimeError("FINNHUB_API_KEY not set")),
        yfinance=_FakeYf({"calendar": None, "earnings_dates": earnings}),
    )
    result = _run(EEFunction(deps).execute(instrument=EQ))
    assert result.data["status"] == "ok"
    assert any("FINNHUB_API_KEY not set" in w for w in result.warnings), result.warnings
    assert result.sources == ["yfinance"], result.sources


def test_ee_source_not_listed_when_provider_returns_nothing() -> None:
    deps = FunctionDeps(finnhub=_FakeFinnhub(rows=[]), yfinance=_FakeYf({"calendar": None, "earnings_dates": None}))
    result = _run(EEFunction(deps).execute(instrument=EQ))
    # The placeholder carries no figures, so no model or provider is named as a source.
    assert result.sources == [], result.sources
    assert result.data["status"] == "provider_unavailable"
    assert result.metadata.get("data_mode") == "provider_unavailable", result.metadata


class _RawFinnhub:
    """Finnhub leg that answers with a non-list JSON object (no earnings rows)."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    async def _get(self, path: str, **kwargs: Any) -> Any:
        return self._payload


def test_ee_finnhub_object_without_rows_is_not_listed_as_a_source() -> None:
    deps = FunctionDeps(
        finnhub=_RawFinnhub({"error": "unexpected payload"}),
        yfinance=_FakeYf({"calendar": None, "earnings_dates": None}),
    )
    result = _run(EEFunction(deps).execute(instrument=EQ))
    assert "finnhub" not in result.sources, result.sources
    assert result.sources == [], result.sources
    assert result.data["status"] == "provider_unavailable"


# ── EE#5 ────────────────────────────────────────────────────────────────


def test_ee_next_report_follows_calendar_when_earnings_dates_disagree() -> None:
    cal_day = date.today() + timedelta(days=120)
    table_day = cal_day - timedelta(days=1)
    earnings = pd.DataFrame(
        {
            "Earnings Date": [pd.Timestamp(table_day)],
            "EPS Estimate": [2.92],
            "Reported EPS": [float("nan")],
            "Surprise(%)": [float("nan")],
        }
    ).set_index("Earnings Date")
    deps = FunctionDeps(
        yfinance=_FakeYf({"calendar": {"Earnings Date": [cal_day]}, "earnings_dates": earnings}),
    )
    result = _run(EEFunction(deps).execute(instrument=EQ))
    nxt = result.data["next_report"]
    assert nxt is not None
    assert nxt["date"] == cal_day.isoformat(), nxt
    assert nxt["source"] == "yfinance_calendar", nxt
    assert any("differs" in w for w in result.warnings), result.warnings


def test_ee_next_report_present_when_only_calendar_knows_the_date() -> None:
    cal_day = date.today() + timedelta(days=60)
    deps = FunctionDeps(yfinance=_FakeYf({"calendar": {"Earnings Date": [cal_day]}, "earnings_dates": None}))
    result = _run(EEFunction(deps).execute(instrument=EQ))
    nxt = result.data["next_report"]
    assert nxt is not None, "calendar date must surface as next_report"
    assert nxt["date"] == cal_day.isoformat()
    assert nxt["source"] == "yfinance_calendar"


def test_ee_past_calendar_date_is_not_a_next_report() -> None:
    past = date.today() - timedelta(days=30)
    deps = FunctionDeps(yfinance=_FakeYf({"calendar": {"Earnings Date": [past]}, "earnings_dates": None}))
    result = _run(EEFunction(deps).execute(instrument=EQ))
    assert result.data["next_report"] is None


def test_ee_finnhub_upcoming_row_keeps_source_label() -> None:
    fut = _future_iso()
    deps = FunctionDeps(finnhub=_FakeFinnhub(rows=[
        {"period": fut, "actual": None, "estimate": 2.92, "surprisePercent": None},
        {"period": "2026-09-30", "actual": 2.10, "estimate": 1.99, "surprisePercent": 5.53},
    ]))
    result = _run(EEFunction(deps).execute(instrument=EQ))
    assert result.data["next_report"]["date"] == fut
    assert result.data["next_report"]["source"] == "finnhub_earnings"


def test_ee_non_list_finnhub_payload_is_not_labelled_official_or_served_as_earnings() -> None:
    """EE#4-RQ: a bare Finnhub object contributes no rows, so it must not set
    ``live_official`` nor be passed through as ``data.earnings``."""
    earnings = pd.DataFrame(
        {
            "Earnings Date": [pd.Timestamp("2026-09-30")],
            "EPS Estimate": [1.99],
            "Reported EPS": [2.10],
            "Surprise(%)": [5.53],
        }
    ).set_index("Earnings Date")
    deps = FunctionDeps(
        finnhub=_RawFinnhub({"error": "unexpected payload"}),
        yfinance=_FakeYf({"calendar": None, "earnings_dates": earnings}),
    )
    result = _run(EEFunction(deps).execute(instrument=EQ))
    assert result.sources == ["yfinance"], result.sources
    assert result.metadata.get("data_mode") == "live_yfinance", result.metadata
    assert result.data["earnings"] == [], result.data["earnings"]
