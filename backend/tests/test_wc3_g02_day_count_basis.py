"""XCON-10: one year-length basis across the option path.

portfolio/greeks converted expiry dates to years with 365.25 while OMON and the
greeks service used 365. The same expiry therefore gave a different T in each
pane. Every option pane now uses the service constant DAYS_PER_YEAR (365).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from showme.engine.functions.derivative import omon
from showme.engine.functions.portfolio import greeks as book_greeks
from showme.engine.services import greeks as greeks_svc


def test_book_expiry_date_uses_the_service_year_length() -> None:
    today = date(2026, 11, 8)
    expiry = today + timedelta(days=365)
    assert book_greeks._years_until(expiry.isoformat(), today) == pytest.approx(
        365 / greeks_svc.DAYS_PER_YEAR, rel=1e-12
    )


def test_book_expiry_days_uses_the_service_year_length() -> None:
    normalized, problems = book_greeks.normalize_position(
        {"kind": "call", "strike": 100, "quantity": 1, "spot": 100, "vol": 0.2,
         "rate": 0.04, "expiry_days": 365},
        today=date(2026, 11, 8),
    )
    assert not problems
    assert normalized["T"] == pytest.approx(365 / greeks_svc.DAYS_PER_YEAR, rel=1e-12)


def test_omon_uses_the_service_year_length() -> None:
    assert omon._DAYS_PER_YEAR == greeks_svc.DAYS_PER_YEAR
