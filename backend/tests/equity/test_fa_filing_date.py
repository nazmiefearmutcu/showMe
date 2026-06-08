"""FA filing-date provenance — P1.2.

The FA pane footer wants to surface the latest real filing/period date so a
user can see *when* the fundamentals were last reported. Previously the
payload never set ``filing_date`` (the UI showed "—").

These tests pin:
  - a stubbed SEC ``standard_fundamentals`` payload (canonical key →
    ``pd.Series`` indexed by the XBRL period ``end`` date) yields a real
    ``filing_date`` derived from the latest period end across the series;
  - the honest provider-unavailable path leaves ``filing_date`` absent /
    null (no fabricated date).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.functions.equity.fa import (  # noqa: E402
    _financial_unavailable_payload,
    _latest_filing_date,
    _normalise_fa_payload,
)


def _sec_payload() -> dict[str, pd.Series]:
    """Mimic ``SECEdgarAdapter.standard_fundamentals`` output: canonical key
    → series indexed by the XBRL period ``end`` date (datetime)."""
    idx = pd.to_datetime(["2022-12-31", "2023-12-31", "2024-12-31"])
    later = pd.to_datetime(["2023-03-31", "2024-03-31", "2025-03-31"])
    return {
        "revenue": pd.Series([90.0, 100.0, 120.0], index=idx),
        "gross_profit": pd.Series([40.0, 45.0, 55.0], index=idx),
        "operating_income": pd.Series([20.0, 22.0, 28.0], index=idx),
        "net_income": pd.Series([16.0, 18.0, 22.0], index=later),
        "total_assets": pd.Series([300.0, 320.0, 360.0], index=idx),
        "total_equity": pd.Series([150.0, 160.0, 180.0], index=idx),
    }


def test_filing_date_populated_from_latest_sec_period_end() -> None:
    payload = _normalise_fa_payload(
        "AAPL", "annual", "sec_edgar", sec_data=_sec_payload()
    )
    # Latest period end across all series is 2025-03-31 (the net_income series).
    assert payload["filing_date"] == "2025-03-31"
    assert payload["status"] == "ok"


def test_filing_date_absent_on_provider_unavailable_path() -> None:
    payload = _financial_unavailable_payload("ZZZZ", "annual", ["no source"])
    assert payload.get("filing_date") is None


def test_filing_date_handles_mixed_tz_aware_and_naive_indexes() -> None:
    """One series is tz-AWARE (UTC), another tz-naive. Comparing the two
    Timestamps directly would raise ``TypeError: Cannot compare tz-naive and
    tz-aware timestamps``; ``_latest_filing_date`` must normalize both and
    return the correct latest date without raising."""
    naive = pd.Series(
        [10.0, 20.0], index=pd.to_datetime(["2023-12-31", "2024-12-31"])
    )
    aware = pd.Series(
        [30.0, 40.0],
        index=pd.to_datetime(["2024-06-30", "2025-03-31"], utc=True),
    )
    # Latest across both is 2025-03-31 (from the tz-aware series).
    assert _latest_filing_date({"naive": naive, "aware": aware}) == "2025-03-31"
    # Order-independent: tz-aware series first must also work.
    assert _latest_filing_date({"aware": aware, "naive": naive}) == "2025-03-31"
