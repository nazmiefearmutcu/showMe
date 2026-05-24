"""COUN — Bug #23 regression.

Previously the US country tab showed BOTH 3.625% (live, BIS via BTMM)
AND 5.25% (static country_reference_profile) as "Policy rate" in the
same table because ``_country_rows`` blindly concatenated the BTMM row
+ reference rows + ECST indicators. We now deduplicate by ``(section,
metric)`` keeping the row with the freshest ``as_of``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.functions.macro.coun import (  # noqa: E402
    _country_rows,
    _deduplicate_country_rows,
)


def _profile_us() -> dict:
    """Mimic _country_profile_model('US')['rows'] without importing internals."""
    return {
        "rows": [
            {"section": "rates", "metric": "Policy rate", "value": 5.25, "unit": "%",
             "source_mode": "country_reference_profile"},
            {"section": "prices", "metric": "Inflation", "value": 3.1, "unit": "% y/y",
             "source_mode": "country_reference_profile"},
            {"section": "growth", "metric": "Real GDP growth", "value": 2.0, "unit": "% y/y",
             "source_mode": "country_reference_profile"},
        ],
    }


def test_country_rows_no_duplicate_policy_rate_when_btmm_supplies_one() -> None:
    profile = _profile_us()
    policy_row = {"policy_rate": 3.625, "as_of": "2026-04-28", "source": "BIS CBPOL"}
    rows = _country_rows("US", profile, policy_row, [])

    policy_rows = [r for r in rows if r.get("metric") == "Policy rate"]
    assert len(policy_rows) == 1, (
        f"Expected exactly 1 Policy rate row after dedup, got {len(policy_rows)}: "
        f"{policy_rows}"
    )
    # BTMM row wins (it has the freshest as_of).
    assert policy_rows[0]["value"] == 3.625
    assert policy_rows[0]["source_mode"] == "BIS CBPOL"


def test_country_rows_reference_wins_when_btmm_row_has_no_as_of() -> None:
    """Defensive: if BTMM row has no `as_of`, reference profile must still appear."""
    profile = _profile_us()
    # Profile rows also lack `as_of`. We expect exactly one Policy rate row;
    # the first-seen wins on ties, which is the BTMM row (inserted first).
    policy_row = {"policy_rate": 3.625, "as_of": None, "source": "BIS CBPOL"}
    rows = _country_rows("US", profile, policy_row, [])
    policy_rows = [r for r in rows if r.get("metric") == "Policy rate"]
    assert len(policy_rows) == 1
    assert policy_rows[0]["value"] == 3.625  # BTMM still wins on first-seen tiebreak


def test_country_rows_keeps_other_metrics_intact() -> None:
    profile = _profile_us()
    policy_row = {"policy_rate": 3.625, "as_of": "2026-04-28", "source": "BIS CBPOL"}
    indicators = [
        {"section": "labor", "metric": "Unemployment rate", "value": 3.9, "unit": "%",
         "as_of": "2026-04-01", "source_mode": "fred"},
    ]
    rows = _country_rows("US", profile, policy_row, indicators)
    metrics = [r.get("metric") for r in rows]
    assert "Inflation" in metrics
    assert "Real GDP growth" in metrics
    assert "Unemployment rate" in metrics


def test_dedup_picks_freshest_as_of() -> None:
    rows = [
        {"section": "rates", "metric": "Policy rate", "value": 4.0, "as_of": "2025-01-01"},
        {"section": "rates", "metric": "Policy rate", "value": 3.5, "as_of": "2026-04-28"},
        {"section": "rates", "metric": "Policy rate", "value": 3.625, "as_of": "2026-04-29"},
    ]
    out = _deduplicate_country_rows(rows)
    assert len(out) == 1
    assert out[0]["value"] == 3.625
    assert out[0]["as_of"] == "2026-04-29"
