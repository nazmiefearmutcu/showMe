"""LITM#2 / LITM#3: the lookback input must bound the 8-K scan, and the monitor
must label governance items separately from legal-proceeding items.

LITM#2: ``months`` was exposed in the seed but never read, so the scan ignored
the lookback. The seed's ``severity`` filter had no heuristic behind it at all.

LITM#3: the handler keeps items 1.03, 1.04, 3.03, 5.02 and 5.03. Items 3.03,
5.02 and 5.03 are security-holder-rights and officer/charter changes, not legal
proceedings, so they are now labelled ``governance`` rather than litigation.

All tests are offline: the SEC EDGAR adapter is faked; the CACT path runs for real.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.misc._bonus import LITMFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _iso(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _frame() -> pd.DataFrame:
    # A-recent (1.03) is inside every lookback; A-old (5.02) is about 400 days
    # old, so it falls outside the 3- and 12-month windows but inside the
    # default 24-month window (about 730 days).
    return pd.DataFrame({
        "form": ["8-K", "8-K", "8-K"],
        "filingDate": [_iso(20), _iso(60), _iso(400)],
        "reportDate": [_iso(20), _iso(60), _iso(400)],
        "accessionNumber": ["A-recent", "A-mid", "A-old"],
        "primaryDocument": ["r.htm", "m.htm", "o.htm"],
        "items": ["1.03", "3.03", "5.02"],
    })


class _Edgar:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    async def fetch(self, request):
        return self._frame

    async def cik_for(self, symbol):
        return "0000320193"


def _run(**params):
    deps = FunctionDeps(sec_edgar=_Edgar(_frame()))
    return asyncio.run(LITMFunction(deps).execute(instrument=AAPL, **params))


# ----------------------------------------------------------------- LITM#2 months


def test_months_lookback_bounds_the_8k_scan() -> None:
    # 3 months keeps the 20- and 60-day filings and drops the 400-day one.
    result = _run(months=3)
    accessions = {row["accession"] for row in result.data["rows"]}
    assert "A-old" not in accessions, result.data["rows"]
    assert result.data["scanned_8k"] == 2, result.data
    assert result.data["lookback_months"] == 3
    assert result.data["window_from"] >= _iso(100), result.data["window_from"]


def test_twelve_month_lookback_drops_filings_older_than_a_year() -> None:
    result = _run(months=12)
    assert result.data["scanned_8k"] == 2, result.data
    assert "A-old" not in {row["accession"] for row in result.data["rows"]}


def test_default_lookback_is_the_seed_default_of_24_months() -> None:
    result = _run()
    assert result.data["lookback_months"] == 24
    assert result.data["scanned_8k"] == 3, result.data


# ------------------------------------------------------------ LITM#3 governance


def test_litigation_and_governance_items_are_labelled_apart() -> None:
    result = _run(months=60)
    by_code = {row["item_code"]: row for row in result.data["rows"]}

    assert by_code["1.03"]["category"] == "litigation"
    assert by_code["1.03"]["event_type"] == "litigation_item"
    assert by_code["3.03"]["category"] == "governance"
    assert by_code["5.02"]["category"] == "governance"
    assert by_code["5.02"]["event_type"] == "governance_item"
    assert "litigation_or_governance_item" not in {r["event_type"] for r in result.data["rows"]}


def test_payload_exposes_the_two_code_sets() -> None:
    result = _run(months=60)
    assert result.data["litigation_codes"] == ["1.03", "1.04"]
    assert result.data["governance_codes"] == ["3.03", "5.02", "5.03"]
    assert result.data["kept_item_codes"] == sorted(
        set(result.data["litigation_codes"]) | set(result.data["governance_codes"])
    )


# ------------------------------------------------------- LITM severity doc truth


def test_seed_severity_description_lists_every_value_the_handler_emits() -> None:
    # The handler emits 'review' on filing rows, 'none' on the empty-state rows and
    # 'unknown' when SEC item codes are unavailable; the seed text must say so.
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    description = REGISTRY.get("LITM").field_dict["severity"].description
    for value in ("review", "none", "unknown"):
        assert f"'{value}'" in description, description


def test_item_codes_unavailable_row_is_severity_unknown() -> None:
    # Pins the 'unknown' value named in the seed text against the real handler path.
    frame = pd.DataFrame({
        "form": ["8-K"],
        "filingDate": [_iso(20)],
        "reportDate": [_iso(20)],
        "accessionNumber": ["A-noitems"],
        "primaryDocument": ["r.htm"],
    })
    deps = FunctionDeps(sec_edgar=_Edgar(frame))
    result = asyncio.run(LITMFunction(deps).execute(instrument=AAPL, months=60))
    assert result.data["status"] == "provider_unavailable", result.data
    assert {row["severity"] for row in result.data["rows"]} == {"unknown"}, result.data["rows"]
