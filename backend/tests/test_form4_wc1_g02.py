"""FORM4 review findings FORM4#2..#8 (wc1-g02).

Each block pins one finding. Network is patched: yfinance and SEC are fakes.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import form4 as form4_mod
from showme.engine.functions.equity.form4 import FORM4Function


# ─── FORM4#3: SEC transaction codes must map to the right direction ──────


def test_form4_3_sec_exercise_codes_x_and_m_are_neutral_not_sales() -> None:
    # X / M = exercise of a derivative: acquires common stock, no market sale.
    assert form4_mod._infer_direction({"acquiredDisposedCode": "X"}) == 0
    assert form4_mod._infer_direction({"acquiredDisposedCode": "M"}) == 0


def test_form4_3_sec_grant_and_expiration_codes_are_neutral_not_buys() -> None:
    # A = grant/award (no open-market purchase); E = expiration of a short position.
    assert form4_mod._infer_direction({"acquiredDisposedCode": "A"}) == 0
    assert form4_mod._infer_direction({"acquiredDisposedCode": "E"}) == 0


def test_form4_3_sec_open_market_codes_keep_their_sign() -> None:
    assert form4_mod._infer_direction({"acquiredDisposedCode": "P"}) == 1
    assert form4_mod._infer_direction({"acquiredDisposedCode": "S"}) == -1


def test_form4_3_normalized_types_do_not_call_exercise_a_sell() -> None:
    assert form4_mod._normalize_transaction_type("x") == "option_exercise"
    assert form4_mod._normalize_transaction_type("m") == "option_exercise"
    assert form4_mod._normalize_transaction_type("a") == "grant"
    assert form4_mod._normalize_transaction_type("s") == "sell"


def test_form4_3_exercise_row_moves_no_net_shares() -> None:
    summary = form4_mod._form4_summary_rows(
        [{"acquiredDisposedCode": "X", "shares": 1000.0, "insider": "CEO",
          "filingDate": "2026-10-01"}]
    )
    assert summary["net_shares"] == 0
    assert "seller_count" not in summary
