"""wc3-g15 GEX#4 follow-up: an expiry whose 16:00 ET close has passed is excluded.

The time-to-expiry clamp returned 1e-9 years for an expired expiry, so a contract
that no longer has a term was priced as if it expired at once (about 1600x its
gamma at a one-year term). Such a contract is now excluded and counted under
``excluded["expiry"]``, never priced at a substitute term.

Offline: pure computation, no provider calls.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import pytest  # noqa: E402

from showme.engine.services.gamma_exposure import chain_gex, time_to_expiry_years  # noqa: E402


def test_expired_expiry_has_no_time_to_expiry() -> None:
    # 2026-11-08 16:00 EST (21:00 UTC) has passed by 2026-11-09 01:00 UTC.
    now = datetime(2026, 11, 9, 1, 0, tzinfo=timezone.utc)
    assert time_to_expiry_years("2026-11-08", now) is None


def test_chain_excludes_an_expired_contract_and_prices_only_live_terms() -> None:
    live_call = {"strike": 100.0, "openInterest": 500, "impliedVolatility": 0.2, "expiry": "2099-12-31"}
    expired_call = {"strike": 100.0, "openInterest": 500, "impliedVolatility": 0.2, "expiry": "2020-01-03"}
    with_expired = chain_gex(spot=100.0, calls=[live_call, expired_call], puts=[])
    live_only = chain_gex(spot=100.0, calls=[live_call], puts=[])
    assert with_expired["excluded"]["expiry"] == 1, with_expired["excluded"]
    assert with_expired["contracts_used"] == 1, with_expired["contracts_used"]
    assert with_expired["net_gex"] == pytest.approx(live_only["net_gex"], rel=1e-9), (
        with_expired["net_gex"], live_only["net_gex"],
    )
