"""BTMM#1 follow-up: stale rows must not drive tilt counts, and an unavailable
BIS feed must not be replaced by a hard-coded snapshot.

1. ``hikes`` / ``cuts`` / ``holds`` previously counted every row, including
   stale legacy observations (1998 euro-area series, a 2025 Argentina cut).
   Stale rows are now excluded from the tilt counts.
2. When the BIS CBPOL loader fails, the handler used to serve a hard-coded
   five-row snapshot labelled ``local fallback``. It must now return an explicit
   ``provider_unavailable`` state with no rows and a reason.

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


def test_tilt_counts_exclude_stale_rows(monkeypatch) -> None:
    rows = [
        {"country_code": "US", "policy_rate": 4.0, "change_bp": -25.0,
         "last_move": "cut", "region": "americas", "as_of": _days_ago(3)},
        {"country_code": "AR", "policy_rate": 29.0, "change_bp": -300.0,
         "last_move": "cut", "region": "americas", "as_of": "2025-07-10"},
        {"country_code": "DE", "policy_rate": 3.0, "change_bp": 25.0,
         "last_move": "hike", "region": "europe", "as_of": "1998-12-31"},
    ]
    summary = _run_with(monkeypatch, rows).data["summary"]
    assert summary["cuts"] == 1, summary
    assert summary["hikes"] == 0, summary
    assert summary["holds"] == 0, summary


def test_bis_failure_returns_explicit_unavailable_state_not_fallback_rows(monkeypatch) -> None:
    def failing_loader(_timeout: float, _force_refresh: bool = False):
        raise RuntimeError("bis unreachable")

    monkeypatch.setattr(btmm, "_load_bis_rows", failing_loader)
    result = asyncio.run(BTMMFunction().execute())

    assert result.data["status"] == "provider_unavailable", result.data
    assert result.data["rows"] == []
    assert result.data["reason"]
    assert result.data["next_actions"]
    assert "local fallback" not in result.sources
    assert all(row.get("source") != "local fallback" for row in result.data["rows"])
    assert any("BIS CBPOL unavailable" in w for w in result.warnings)
    assert result.data["summary"]["average_policy_rate"] is None


def test_no_hard_coded_fallback_table_remains() -> None:
    assert not hasattr(btmm, "_FALLBACK_ROWS")


def test_tilt_counts_exclude_undated_rows(monkeypatch) -> None:
    """BTMM#1 follow-up: a move with no usable as_of date is not counted as a
    current hike, cut or hold, and the exclusion is reported."""
    rows = [
        {"country_code": "US", "policy_rate": 4.0, "change_bp": -25.0,
         "last_move": "cut", "region": "americas", "as_of": _days_ago(3)},
        {"country_code": "XX", "policy_rate": 5.0, "change_bp": 25.0,
         "last_move": "hike", "region": "americas", "as_of": ""},
        {"country_code": "YY", "policy_rate": 6.0, "change_bp": 0.0,
         "last_move": "hold", "region": "americas", "as_of": "2999-01-01"},
    ]
    result = _run_with(monkeypatch, rows)
    summary = result.data["summary"]
    assert summary["hikes"] == 0, summary
    assert summary["cuts"] == 1, summary
    assert summary["holds"] == 0, summary
    assert summary["undated_rows"] == 2, summary
    assert any("undated_rows_excluded" in w for w in result.warnings), result.warnings
