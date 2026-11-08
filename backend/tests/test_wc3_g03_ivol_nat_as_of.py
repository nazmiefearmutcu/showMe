"""WC3 g03 — IVOL#4-RQ: a missing lastTradeDate (pd.NaT) must not become the as-of stamp.

pd.NaT passes ``isinstance(raw, datetime)`` and is compared with ``>``, which is always
False, so a NaT row seen first used to pin the snapshot time to the string 'NaT'.
"""

from __future__ import annotations

import pandas as pd

from showme.engine.functions.derivative._stubs import _ivol_as_of


def test_nat_last_trade_date_is_skipped_before_a_valid_stamp() -> None:
    valid = pd.Timestamp("2026-11-07 15:00", tz="America/New_York")
    result = _ivol_as_of([{"lastTradeDate": pd.NaT}, {"lastTradeDate": valid}])
    assert result is not None
    assert result != "NaT"
    assert result.startswith("2026-11-07T15:00:00")


def test_nat_last_trade_date_is_skipped_after_a_valid_stamp() -> None:
    valid = pd.Timestamp("2026-11-07 15:00", tz="America/New_York")
    result = _ivol_as_of([{"lastTradeDate": valid}, {"lastTradeDate": pd.NaT}])
    assert result is not None
    assert result.startswith("2026-11-07T15:00:00")


def test_all_nat_rows_mean_the_snapshot_time_is_unknown() -> None:
    # No usable stamp: the honest answer is None (the "not supplied" basis), never 'NaT'.
    assert _ivol_as_of([{"lastTradeDate": pd.NaT}], [{"lastTradeDate": pd.NaT}]) is None
