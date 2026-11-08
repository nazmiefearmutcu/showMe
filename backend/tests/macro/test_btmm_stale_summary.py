"""BTMM#1 regression: stale or legacy policy-rate rows must not drive the summary.

The table dated every row, but the summary mixed freshness methods: the
average_policy_rate averaged all rows (including 1998 legacy euro-area national
series and a 2025 Argentina row), while min/max applied the 183-day gate and
largest_last_move was picked from every row. Those stale numbers are now
excluded from the average, range and largest move, and each row carries an
explicit freshness flag.

All tests are offline: the BIS loader is replaced by a fake.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import showme.engine.functions.macro.btmm as btmm  # noqa: E402
from showme.engine.functions.macro.btmm import BTMMFunction  # noqa: E402


def _days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _run_with(monkeypatch, rows):
    monkeypatch.setattr(btmm, "_load_bis_rows", lambda _t, _f=False: rows)
    return asyncio.run(BTMMFunction().execute(country="ALL", region="all", limit=80))


def _mixed_rows():
    return [
        {"country_code": "US", "country": "United States", "policy_rate": 4.0,
         "change_bp": -25.0, "last_move": "cut", "region": "americas",
         "central_bank": "Federal Reserve", "as_of": _days_ago(3)},
        {"country_code": "EU", "country": "Euro area", "policy_rate": 2.0,
         "change_bp": 0.0, "last_move": "hold", "region": "europe",
         "central_bank": "European Central Bank", "as_of": _days_ago(3)},
        # Legacy national euro-area series, last observed in 1998.
        {"country_code": "DE", "country": "Germany", "policy_rate": 3.0,
         "change_bp": 0.0, "last_move": "hold", "region": "europe",
         "central_bank": "Deutsche Bundesbank", "as_of": "1998-12-31"},
        # Stale 2025 observation with a large move that must not be "largest".
        {"country_code": "AR", "country": "Argentina", "policy_rate": 29.0,
         "change_bp": -300.0, "last_move": "cut", "region": "americas",
         "central_bank": "Banco Central de la República Argentina",
         "as_of": "2025-07-10"},
    ]


def test_average_policy_rate_excludes_stale_rows(monkeypatch) -> None:
    result = _run_with(monkeypatch, _mixed_rows())
    summary = result.data["summary"]
    # Fresh rows only: (4.0 + 2.0) / 2. Including DE 3.0 and AR 29.0 would be wrong.
    assert summary["average_policy_rate"] == 3.0, summary


def test_largest_move_is_drawn_from_fresh_rows_only(monkeypatch) -> None:
    result = _run_with(monkeypatch, _mixed_rows())
    largest = result.data["summary"]["largest_last_move"]
    assert largest is not None
    assert largest["country_code"] == "US", largest
    assert largest["as_of"] == _days_ago(3)


def test_rows_carry_explicit_freshness_flag(monkeypatch) -> None:
    result = _run_with(monkeypatch, _mixed_rows())
    by_code = {row["country_code"]: row for row in result.data["rows"]}
    assert by_code["US"]["freshness"] == "fresh"
    assert by_code["DE"]["freshness"] == "stale"
    assert by_code["AR"]["freshness"] == "stale"


def test_stale_exclusion_is_reported_as_a_warning(monkeypatch) -> None:
    result = _run_with(monkeypatch, _mixed_rows())
    assert any("stale_rows_excluded" in w for w in result.warnings), result.warnings
    assert result.data["summary"]["stale_rows"] == 2
    assert result.data["summary"]["fresh_rows"] == 2


def test_all_stale_yields_no_average_range_or_largest_move(monkeypatch) -> None:
    rows = [
        {"country_code": "X", "policy_rate": 1.0, "change_bp": -50.0, "as_of": "2020-01-01"},
        {"country_code": "Y", "policy_rate": 4.0, "change_bp": 25.0, "as_of": "2021-01-01"},
    ]
    result = _run_with(monkeypatch, rows)
    summary = result.data["summary"]
    assert summary["average_policy_rate"] is None
    assert summary["min_policy_rate"] is None
    assert summary["max_policy_rate"] is None
    assert summary["largest_last_move"] is None
