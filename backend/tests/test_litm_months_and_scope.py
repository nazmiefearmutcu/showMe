"""LITM#2 / LITM#3: the lookback input must bound the 8-K scan, and the monitor
must label governance items separately from legal-proceeding items.

LITM#2: ``months`` was exposed in the seed but never read, so the scan ignored
the lookback. The seed's ``severity`` filter had no heuristic behind it at all.
LITM reads its 8-Ks from the Awareness SEC filing index through CACT, which
covers the most recent 365 days, so a longer lookback is capped to that window
and a warning says so.

LITM#3: the handler keeps items 1.03, 1.04, 3.03, 5.02 and 5.03. Items 3.03,
5.02 and 5.03 are security-holder-rights and officer/charter changes, not legal
proceedings, so they are labelled ``governance`` rather than litigation.

All tests are offline: the Awareness client is replaced by a fake keyed by
endpoint path; the real CACT and LITM run.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.awareness import AwarenessResponse
from showme.engine.functions.calendar import _common as aw_common
from showme.engine.functions.misc._bonus import LITMFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
OK_PROVIDERS = [{"provider": "sec.edgar", "status": "ok", "last_ok_at": None, "last_error": None}]


def _iso(days_ago: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=days_ago)).isoformat()


class _Routes:
    """Awareness fake keyed by endpoint path; records each call's params."""

    def __init__(self, table: dict[str, Any]) -> None:
        self.table = table
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, path: str, params: dict[str, Any] | None = None) -> AwarenessResponse:
        self.calls.append((path, dict(params or {})))
        meta = {"generated_at": "2026-11-08T00:00:00+00:00", "providers": OK_PROVIDERS,
                "notes": [], "filters": dict(params or {})}
        return AwarenessResponse(data=self.table.get(path, []), meta=meta, url=path)


def _filing(accession: str, days_ago: int, codes: list[str]) -> dict[str, Any]:
    return {
        "id": accession, "type": "filing", "symbol": "AAPL", "company": "Apple", "date": _iso(days_ago),
        "time_of_day": None, "status": "filed",
        "fields": {
            "form": "8-K", "accession": accession, "cik": "0000320193",
            "url": f"https://www.sec.gov/Archives/{accession}.htm",
            "items": [{"code": c, "label": c} for c in codes],
            "material": True,
        },
        "sources": [{"provider": "sec.edgar", "url": None, "fetched_at": None, "basis": "native"}],
    }


def _filings() -> list[dict[str, Any]]:
    # A-recent (1.03) and A-mid (3.03) sit inside every lookback; A-year (5.02) is
    # 300 days old (inside 12 months, outside 3); A-old (5.02) is 380 days old, past
    # both the 12-month lookback and the 365-day Awareness filing window.
    return [
        _filing("A-recent", 20, ["1.03"]),
        _filing("A-mid", 60, ["3.03"]),
        _filing("A-year", 300, ["5.02"]),
        _filing("A-old", 380, ["5.02"]),
    ]


def _run(monkeypatch: pytest.MonkeyPatch, filings: list[dict[str, Any]] | None = None, **params: Any):
    routes = _Routes({"/calendar/corporate": [], "/filings": _filings() if filings is None else filings})
    monkeypatch.setattr(aw_common, "get_awareness_client", lambda: routes)
    result = asyncio.run(LITMFunction(FunctionDeps()).execute(instrument=AAPL, **params))
    return result, routes


def _filings_days(routes: _Routes) -> int:
    return int(next(params["days"] for path, params in routes.calls if path == "/filings"))


# ----------------------------------------------------------------- LITM#2 months


def test_months_lookback_bounds_the_8k_scan(monkeypatch) -> None:
    # 3 months keeps the 20- and 60-day filings and drops the older ones.
    result, routes = _run(monkeypatch, months=3)
    accessions = {row["accession"] for row in result.data["rows"]}
    assert {"A-year", "A-old"}.isdisjoint(accessions), result.data["rows"]
    assert result.data["scanned_8k"] == 2, result.data
    assert result.data["lookback_months"] == 3
    assert result.data["window_from"] >= _iso(100), result.data["window_from"]
    assert _filings_days(routes) == 91  # the lookback reaches the Awareness request
    assert not any("capped" in w for w in result.warnings), result.warnings


def test_twelve_month_lookback_drops_filings_older_than_a_year(monkeypatch) -> None:
    result, _ = _run(monkeypatch, months=12)
    assert result.data["scanned_8k"] == 3, result.data
    assert "A-old" not in {row["accession"] for row in result.data["rows"]}


def test_default_lookback_is_the_seed_default_capped_to_the_filing_window(monkeypatch) -> None:
    result, routes = _run(monkeypatch)
    assert result.data["lookback_months"] == 24
    assert result.data["coverage_days"] == 365
    assert result.data["window_from"] == _iso(365)
    assert result.data["scanned_8k"] == 3, result.data
    assert _filings_days(routes) == 365
    assert any("365 days" in w and "24-month lookback is capped" in w for w in result.warnings), result.warnings


# ------------------------------------------------------------ LITM#3 governance


def test_litigation_and_governance_items_are_labelled_apart(monkeypatch) -> None:
    result, _ = _run(monkeypatch, months=60)
    by_code = {row["item_code"]: row for row in result.data["rows"]}

    assert by_code["1.03"]["category"] == "litigation"
    assert by_code["1.03"]["event_type"] == "litigation_item"
    assert by_code["3.03"]["category"] == "governance"
    assert by_code["5.02"]["category"] == "governance"
    assert by_code["5.02"]["event_type"] == "governance_item"
    assert "litigation_or_governance_item" not in {r["event_type"] for r in result.data["rows"]}


def test_payload_exposes_the_two_code_sets(monkeypatch) -> None:
    result, _ = _run(monkeypatch, months=60)
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


def test_item_codes_unavailable_row_is_severity_unknown(monkeypatch) -> None:
    # Pins the 'unknown' value named in the seed text against the real handler path.
    result, _ = _run(monkeypatch, filings=[_filing("A-noitems", 20, [])], months=60)
    assert result.data["status"] == "provider_unavailable", result.data
    assert {row["severity"] for row in result.data["rows"]} == {"unknown"}, result.data["rows"]


# ------------------------------------------------- LITM#2 non-finite months input


@pytest.mark.parametrize("raw", ["inf", "-inf", float("inf"), float("-inf"), "nan", float("nan")])
def test_non_finite_months_do_not_crash_and_fall_back_to_default(monkeypatch, raw) -> None:
    # float('inf') is accepted by float() but int() raises OverflowError; the live
    # path must clamp or default instead of raising.
    result, _ = _run(monkeypatch, months=raw)
    assert result.data["lookback_months"] == 24, (raw, result.data["lookback_months"])
    assert result.data["scanned_8k"] == 3, (raw, result.data)
