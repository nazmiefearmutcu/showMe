"""BTMM — Bug #24 regression.

Two related defects:

1. The header ``live`` pill could never flip to ``warn`` because the BTMM
   engine never emitted a warning even when the freshest BIS observation
   was 24 days old (e.g. weekend, network outage, stale fallback). We now
   push ``data_stale_24h: ...`` into the warnings array when the freshest
   ``as_of`` in scope is more than 24 hours old.

2. The KPI ribbon "Range" min/max pulled a 2022 Croatian 0.00% policy-rate
   observation from the fallback table — completely stale. ``_summary``
   now restricts the min/max calculation to rows whose ``as_of`` is within
   the last 6 months (183 days).
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


def _iso_days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def test_btmm_emits_stale_warning_when_data_more_than_24h_old(monkeypatch) -> None:
    stale_iso = _iso_days_ago(40)

    def fake_loader(_timeout: float, _force_refresh: bool = False):
        return [
            {
                "country_code": "US",
                "country": "United States",
                "policy_rate": 3.625,
                "change_bp": -25.0,
                "last_move": "cut",
                "region": "americas",
                "as_of": stale_iso,
                "source": "BIS CBPOL",
            },
        ]

    monkeypatch.setattr(btmm, "_load_bis_rows", fake_loader)
    result = asyncio.run(BTMMFunction().execute())
    assert any("data_stale_24h" in w for w in result.warnings), (
        f"expected data_stale_24h warning; got {result.warnings}"
    )
    assert result.data["as_of"] == stale_iso
    assert result.data["stale_seconds"] is not None
    assert result.data["stale_seconds"] > 24 * 3600


def test_btmm_no_warning_when_data_is_fresh(monkeypatch) -> None:
    fresh_iso = _iso_days_ago(0)

    def fake_loader(_timeout: float, _force_refresh: bool = False):
        return [
            {
                "country_code": "US",
                "country": "United States",
                "policy_rate": 3.625,
                "as_of": fresh_iso,
                "region": "americas",
                "source": "BIS CBPOL",
            },
        ]

    monkeypatch.setattr(btmm, "_load_bis_rows", fake_loader)
    result = asyncio.run(BTMMFunction().execute())
    assert not any("data_stale_24h" in w for w in result.warnings)
    assert result.data["stale_seconds"] is not None
    assert result.data["stale_seconds"] < 24 * 3600


def test_btmm_summary_ignores_stale_2022_observation_in_range(monkeypatch) -> None:
    """The 2022 Croatian 0.00% observation must not pull min_policy_rate to 0."""
    fresh_iso = _iso_days_ago(7)

    def fake_loader(_timeout: float, _force_refresh: bool = False):
        return [
            {
                "country_code": "HR",
                "country": "Croatia",
                "policy_rate": 0.00,
                "as_of": "2022-07-01",
                "region": "europe",
                "source": "BIS CBPOL",
            },
            {
                "country_code": "US",
                "country": "United States",
                "policy_rate": 3.625,
                "as_of": fresh_iso,
                "region": "americas",
                "source": "BIS CBPOL",
            },
            {
                "country_code": "EU",
                "country": "Euro area",
                "policy_rate": 2.00,
                "as_of": fresh_iso,
                "region": "europe",
                "source": "BIS CBPOL",
            },
        ]

    monkeypatch.setattr(btmm, "_load_bis_rows", fake_loader)
    result = asyncio.run(BTMMFunction().execute())
    summary = result.data["summary"]
    # min must come from fresh rows only — 2.00 (EU), not 0.00 (HR/2022).
    assert summary["min_policy_rate"] == 2.00, summary
    assert summary["max_policy_rate"] == 3.625
    assert summary["range_window_days"] == 183


def test_btmm_summary_falls_back_to_full_set_when_all_stale(monkeypatch) -> None:
    """Edge case: nothing passes the freshness gate → use full set."""
    def fake_loader(_timeout: float, _force_refresh: bool = False):
        return [
            {"country_code": "X", "policy_rate": 1.0, "as_of": "2020-01-01"},
            {"country_code": "Y", "policy_rate": 4.0, "as_of": "2021-01-01"},
        ]

    monkeypatch.setattr(btmm, "_load_bis_rows", fake_loader)
    result = asyncio.run(BTMMFunction().execute())
    summary = result.data["summary"]
    assert summary["min_policy_rate"] == 1.0
    assert summary["max_policy_rate"] == 4.0


def test_btmm_as_of_envelope_is_max_of_rows(monkeypatch) -> None:
    fresh_iso = _iso_days_ago(0)
    older_iso = _iso_days_ago(10)

    def fake_loader(_timeout: float, _force_refresh: bool = False):
        return [
            {"country_code": "X", "policy_rate": 1.0, "as_of": older_iso, "region": "europe"},
            {"country_code": "US", "policy_rate": 3.625, "as_of": fresh_iso, "region": "americas"},
        ]

    monkeypatch.setattr(btmm, "_load_bis_rows", fake_loader)
    result = asyncio.run(BTMMFunction().execute())
    assert result.data["as_of"] == fresh_iso
