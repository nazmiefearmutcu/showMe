"""FA SEC XBRL selection — FA#1, FA#2, FA#4, FA#5.

Regression tests for the SEC EDGAR statement path of FA:

  * FA#1 — the first XBRL tag per canonical key won, so a 2010 ``Cash`` fact
    was shown as the current cash balance. The tag with the most recent
    period end must win instead.
  * FA#2 — every USD fact for a tag was kept, so 3-month 10-Q values and
    6-month YTD values were mixed into the annual table. Annual output must
    use 10-K fiscal-year facts only; quarterly output 10-Q Q1-Q3 facts only.
  * FA#4 — the ``period`` input never reached the SEC adapter.
  * FA#5 — ``filing_date`` was the latest period end, not the SEC ``filed``
    date of the fact.

All tests run offline: the SEC adapter's CIK lookup and companyfacts GET are
replaced with synthetic payloads shaped like https://data.sec.gov companyfacts.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.data_sources.equity.sec_edgar_adapter import SECEdgarAdapter  # noqa: E402
from showme.engine.functions.equity.fa import FAFunction, _compute_ratios  # noqa: E402


def _fact(
    end: str,
    val: float,
    form: str,
    fp: str,
    fy: int,
    filed: str,
    start: str | None = None,
) -> dict[str, Any]:
    fact: dict[str, Any] = {
        "end": end,
        "val": val,
        "accn": "0000000000-00-000000",
        "fy": fy,
        "fp": fp,
        "form": form,
        "filed": filed,
    }
    if start is not None:
        fact["start"] = start
    return fact


def _facts_payload() -> dict[str, Any]:
    us_gaap: dict[str, Any] = {
        # Stale first-encountered tag: only a FY2010 instant.
        "Cash": {"units": {"USD": [
            _fact("2010-09-25", 1_690_000_000, "10-K", "FY", 2010, "2010-10-27"),
        ]}},
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
            _fact("2025-09-27", 35_934_000_000, "10-K", "FY", 2025, "2025-10-31"),
            _fact("2026-09-26", 36_305_000_000, "10-K", "FY", 2026, "2026-11-03"),
            _fact("2026-03-28", 30_000_000_000, "10-Q", "Q2", 2026, "2026-05-01"),
        ]}},
        # Stale D&A tag (FY2016) alongside the current tag (FY2026).
        "DepreciationAndAmortization": {"units": {"USD": [
            _fact("2016-09-24", 8_300_000_000, "10-K", "FY", 2016, "2016-10-26", start="2015-09-27"),
        ]}},
        "DepreciationDepletionAndAmortization": {"units": {"USD": [
            _fact("2025-09-27", 11_698_000_000, "10-K", "FY", 2025, "2025-10-31", start="2024-09-29"),
            _fact("2026-09-26", 13_423_000_000, "10-K", "FY", 2026, "2026-11-03", start="2025-09-28"),
        ]}},
        "Revenues": {"units": {"USD": [
            _fact("2026-09-26", 478_834_000_000, "10-K", "FY", 2026, "2026-11-03", start="2025-09-28"),
            _fact("2025-09-27", 416_161_000_000, "10-K", "FY", 2025, "2025-10-31", start="2024-09-29"),
            # 10-K quarterly table row inside a FY 10-K (~90 days): not an annual fact.
            _fact("2018-09-29", 62_900_000_000, "10-K", "FY", 2018, "2018-11-05", start="2018-07-01"),
            # 10-Q three-month facts.
            _fact("2026-03-28", 111_184_000_000, "10-Q", "Q2", 2026, "2026-05-01", start="2025-12-28"),
            _fact("2026-06-27", 109_417_000_000, "10-Q", "Q3", 2026, "2026-08-01", start="2026-03-29"),
            # 10-Q six-month YTD fact (~181 days): neither annual nor quarterly.
            _fact("2026-03-28", 230_000_000_000, "10-Q", "Q2", 2026, "2026-05-01", start="2025-09-28"),
        ]}},
        # Only a stale FY2019 fact: must not surface as a current debt line.
        "LongTermDebt": {"units": {"USD": [
            _fact("2019-09-28", 105_000_000_000, "10-K", "FY", 2019, "2019-10-31"),
        ]}},
    }
    return {"cik": 320193, "facts": {"us-gaap": us_gaap}}


def _adapter() -> SECEdgarAdapter:
    adapter = SECEdgarAdapter()

    async def _cik(ticker: str) -> str:
        return "0000320193"

    async def _facts(cik: str) -> dict[str, Any]:
        return _facts_payload()

    adapter.cik_for = _cik  # type: ignore[method-assign]
    adapter.company_facts = _facts  # type: ignore[method-assign]
    return adapter


def _instrument() -> Instrument:
    return Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _run_fa(period: str) -> Any:
    fn = FAFunction(deps=FunctionDeps(sec_edgar=_adapter()))
    return asyncio.run(fn.execute(instrument=_instrument(), period=period))


def _row(rows: list[dict[str, Any]], line_item: str) -> dict[str, Any]:
    matches = [r for r in rows if r.get("line_item") == line_item]
    assert matches, f"{line_item} missing from {[r.get('line_item') for r in rows]}"
    return matches[0]


def test_cash_latest_is_current_not_the_fy2010_tag() -> None:
    # FA#1: "Cash" (FY2010) and CashAndCashEquivalentsAtCarryingValue share the
    # canonical key "cash"; the current tag must be the one shown.
    data = _run_fa("annual").data
    cash = _row(data["balance_sheet"], "cash")
    assert cash["latest"] == 36_305_000_000, cash
    assert "2010-09-25" not in cash


def test_depreciation_latest_is_current_not_the_fy2016_tag() -> None:
    # FA#1: the stale DepreciationAndAmortization (FY2016) must not be the
    # latest D&A; the current DepreciationDepletionAndAmortization (FY2026) is.
    data = _run_fa("annual").data
    da = _row(data["cash_flow"], "depreciationAndAmortization")
    assert da["latest"] == 13_423_000_000, da
    assert "2016-09-24" not in da


def test_annual_revenue_excludes_quarterly_and_ytd_facts() -> None:
    # FA#2: annual output must not interleave 3-month 10-Q values, 6-month
    # YTD values or the ~90-day 10-K quarterly row into the 5-year table.
    data = _run_fa("annual").data
    revenue = _row(data["income_statement"], "revenue")
    assert revenue["latest"] == 478_834_000_000, revenue
    assert "2026-03-28" not in revenue
    assert "2026-06-27" not in revenue
    assert "2018-09-29" not in revenue
    assert revenue["2026-09-26"] == 478_834_000_000


def test_quarterly_period_uses_three_month_10q_facts() -> None:
    # FA#4 (+FA#2): period=quarterly must reach the SEC adapter and select
    # the 10-Q three-month facts, not the FY 10-K or the YTD values.
    result = _run_fa("quarterly")
    data = result.data
    assert data["period"] == "quarterly"
    revenue = _row(data["income_statement"], "revenue")
    assert revenue["latest"] == 109_417_000_000, revenue
    assert revenue["2026-03-28"] == 111_184_000_000, revenue
    assert "2026-09-26" not in revenue
    assert all(v != 230_000_000_000 for k, v in revenue.items() if k != "line_item")


def test_annual_and_quarterly_differ_for_the_same_ticker() -> None:
    # FA#4: before the fix both periods returned identical payloads.
    annual = _run_fa("annual").data["income_statement"]
    quarterly = _run_fa("quarterly").data["income_statement"]
    assert annual != quarterly


def test_filing_date_is_sec_filed_date_not_period_end() -> None:
    # FA#5: the newest 10-K FY2026 fact was filed 2026-11-03 for period end
    # 2026-09-26. filing_date must be the filed date; period_end the data date.
    data = _run_fa("annual").data
    assert data["period_end"] == "2026-09-26"
    assert data["filing_date"] == "2026-11-03"
    assert data["retrieved_at"], "retrieval time must be stamped separately"


def test_stale_line_item_is_dropped_not_shown_as_current() -> None:
    # FA#1: LongTermDebt only has a FY2019 fact, years older than the newest
    # filing in the same payload. It must not appear as a current row.
    data = _run_fa("annual").data
    assert all(r.get("line_item") != "long_term_debt" for r in data["balance_sheet"])


def test_sec_adapter_rejects_unknown_period() -> None:
    adapter = _adapter()
    try:
        asyncio.run(adapter.standard_fundamentals("AAPL", period="monthly"))
    except Exception as exc:  # DataSourceError
        assert "period" in str(exc).lower()
    else:  # pragma: no cover - failure path
        raise AssertionError("unknown period must be rejected")


def test_debt_to_equity_never_falls_back_to_total_liabilities() -> None:
    # FA#6: with no long-term debt the ratio must not silently become
    # total liabilities / equity.
    ratios = _compute_ratios({"total_equity": 100.0, "total_liabilities": 300.0})
    assert "debt_to_equity" not in ratios


def test_debt_to_equity_zero_long_term_debt_is_zero_not_liabilities() -> None:
    # FA#6: a reported zero long-term debt is 0.0, not a fallback to liabilities.
    ratios = _compute_ratios({
        "total_equity": 100.0, "total_liabilities": 300.0, "long_term_debt": 0.0,
    })
    assert ratios["debt_to_equity"] == 0.0


def test_quarterly_ratio_basis_says_not_annualized() -> None:
    # FA#4 follow-on: quarterly flow ratios (ROA/ROE/margins) are single-quarter
    # values; the payload must say so instead of reading like annual ratios.
    assert "not annualized" in _run_fa("quarterly").data["ratio_basis"]
    assert "fiscal-year" in _run_fa("annual").data["ratio_basis"]
