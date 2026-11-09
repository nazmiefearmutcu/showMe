"""FORM4 net flow must not read as computed when no direction was parsed (P1a-g12 FORM4#1).

yfinance's insider_transactions frame leaves ``Transaction`` blank for every row
of AAPL, MSFT and NVDA and carries the direction in ``Text`` ("Sale at price
325.75 per share."). The mapper ignored ``Text``, every row classified as
direction 0, and the summary reported ``net_shares: 0.0`` as if it were a
computed net flow.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import form4 as form4_mod
from showme.engine.functions.equity.form4 import FORM4Function


def _aapl_frame(transaction: Any = None) -> pd.DataFrame:
    """Shape of yfinance ``Ticker.insider_transactions`` (live AAPL, 2026-11)."""
    return pd.DataFrame(
        {
            "Shares": [2399, 2399, 1392],
            "Value": [781474.0, 814748.0, 480315.0],
            "URL": [None, None, None],
            "Text": [
                "Sale at price 325.75 per share.",
                "Sale at price 339.62 per share.",
                "Sale at price 342.66 - 347.46 per share.",
            ],
            "Insider": ["NEWSTEAD JENNIFER", "NEWSTEAD JENNIFER", "PAREKH KEVAN"],
            "Position": ["Officer", "Officer", "Chief Financial Officer"],
            "Transaction": [transaction, transaction, transaction],
            "Start Date": pd.to_datetime(["2026-11-03", "2026-10-20", "2026-10-16"]),
            "Ownership": ["D", "D", "D"],
        }
    )


class _YF:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    async def fetch(self, request: Any) -> dict[str, Any]:
        return {"insider_transactions": self._frame}


def _execute(frame: pd.DataFrame) -> Any:
    deps = FunctionDeps()
    deps.yfinance = _YF(frame)
    deps.sec_edgar = None
    fn = FORM4Function(deps)
    return asyncio.run(fn.execute(instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)))


def test_yfinance_text_supplies_the_direction_when_transaction_is_blank() -> None:
    rows = form4_mod._insider_rows_from_yfinance("AAPL", {"insider_transactions": _aapl_frame(None)})
    assert [r["transaction_type"] for r in rows] == ["sell", "sell", "sell"]
    assert rows[0]["transaction"] == "Sale at price 325.75 per share."


def test_sale_text_is_a_sell_for_the_summary() -> None:
    summary = form4_mod._form4_summary_rows(
        [{"transaction": "Sale at price 325.75 per share.", "shares": 1000.0, "value": 325750.0,
          "insider": "X", "filingDate": "2026-10-01"}]
    )
    assert summary["net_shares"] == pytest.approx(-1000.0)
    assert summary["net_notional"] == pytest.approx(-325750.0)
    assert summary["seller_count"] == 1


def test_unparsed_direction_is_null_not_zero() -> None:
    rows = [{"transaction": None, "transaction_type": "", "shares": 500.0, "value": 10000.0,
             "insider": "X", "filingDate": "2026-10-01"}]
    summary = form4_mod._form4_summary_rows(rows)
    assert summary["net_shares"] is None
    assert summary["net_notional"] is None
    assert summary["unclassified_count"] == 1


def test_pure_gift_is_a_known_neutral_zero_not_unknown() -> None:
    # Known-neutral (SEC G) rows still net to a real zero, as HNT-16 pins.
    summary = form4_mod._form4_summary_rows(
        [{"acquiredDisposedCode": "G", "shares": 1000, "price": 50.0, "insider": "CEO",
          "filingDate": "2026-09-01T00:00:00+00:00"}]
    )
    assert summary["net_shares"] == 0
    assert summary["unclassified_count"] == 0


def test_grant_text_is_neutral_not_a_buy() -> None:
    summary = form4_mod._form4_summary_rows(
        [{"transaction": "Stock Award(Grant)", "shares": 800.0, "insider": "CFO",
          "filingDate": "2026-10-01"}]
    )
    assert summary["net_shares"] == 0


def test_execute_reports_the_yfinance_net_flow_from_text() -> None:
    res = _execute(_aapl_frame(None))
    assert res.data["status"] == "delayed_reference"
    assert res.data["net_shares"] == pytest.approx(-(2399 + 2399 + 1392))
    assert res.data["net_notional"] == pytest.approx(-(781474.0 + 814748.0 + 480315.0))
    assert res.data["seller_count"] == 2
    assert res.data["unclassified_count"] == 0


def test_execute_with_no_parseable_direction_returns_null_net() -> None:
    frame = _aapl_frame(None)
    frame["Text"] = ["Undisclosed holding change.", "Undisclosed holding change.", "Undisclosed holding change."]
    res = _execute(frame)
    assert res.data["net_shares"] is None
    assert res.data["net_notional"] is None
    assert res.data["unclassified_count"] == 3
