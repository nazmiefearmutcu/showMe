"""WIRP — Bug #N6 regression.

The hardcoded FOMC date list shipped with dates that don't match the
Federal Reserve's published 2026 calendar. After this fix the FED
schedule includes only verified 2026 decision dates.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.functions.macro.wirp import WIRPFunction  # noqa: E402


# Verified against Fed calendar 2026-05-24
_VERIFIED_2026_FED = {
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-10-28",
    "2026-12-09",
}


def test_wirp_fed_dates_match_verified_calendar() -> None:
    result = asyncio.run(WIRPFunction().execute(central_bank="FED", meetings=8))
    dates = {row["date"] for row in result.data["rows"]}
    # Every shipped date must be in the verified set.
    assert dates.issubset(_VERIFIED_2026_FED), (
        f"WIRP returned unverified FOMC dates: {dates - _VERIFIED_2026_FED}"
    )


def test_wirp_drops_obsolete_2026_06_10_date() -> None:
    """That specific bogus date used to ship as the first FED row."""
    result = asyncio.run(WIRPFunction().execute(central_bank="FED", meetings=8))
    dates = {row["date"] for row in result.data["rows"]}
    assert "2026-06-10" not in dates, "2026-06-10 is not a real FOMC meeting"
    assert "2026-11-04" not in dates, "2026-11-04 is not a real FOMC meeting"


def test_wirp_probabilities_still_sum_to_one() -> None:
    result = asyncio.run(WIRPFunction().execute(central_bank="FED", meetings=4))
    for row in result.data["rows"]:
        total = row["cut_25bp"] + row["hold"] + row["hike_25bp"]
        assert abs(total - 1.0) < 1e-6, row
