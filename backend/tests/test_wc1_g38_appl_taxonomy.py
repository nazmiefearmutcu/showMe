"""APPL#1-#4 — the taxonomy payload must say what it delivered and where it came from.

* APPL#1: CIK / SIC / fiscal year end / latest filings come from SEC EDGAR
  (keyless) and are null, never invented, when the lookup fails.
* APPL#2: the GICS/NAICS/ICB crosswalk is bundled for a few symbols only; the
  payload labels whether the symbol has one.
* APPL#3: reference-template rows are never stamped ``live_yfinance``.
* APPL#4: ``sources`` lists the static crosswalk when it contributed rows, and
  an explicit ``live=false`` selects the template path.

No network: yfinance and SEC adapters are fakes.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.functions.misc._bonus import APPLFunction  # noqa: E402

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
MSFT = Instrument(symbol="MSFT", asset_class=AssetClass.EQUITY)


class _FakeYfinance:
    def __init__(self, refdata=None, boom: bool = False) -> None:
        self._refdata = refdata
        self._boom = boom

    async def fetch(self, request):  # noqa: ANN001 - fake seam
        if self._boom:
            raise RuntimeError("yahoo down")
        return self._refdata


class _FakeSec:
    def __init__(self, cik: str | None = "0000320193", boom: bool = False) -> None:
        self._cik = cik
        self._boom = boom

    async def cik_for(self, ticker: str):  # noqa: ANN001
        if self._boom:
            raise RuntimeError("sec down")
        return self._cik

    async def submissions(self, cik: str):  # noqa: ANN001
        return {
            "cik": "320193",
            "sic": "3571",
            "sicDescription": "Electronic Computers",
            "fiscalYearEnd": "0926",
            "filings": {"recent": {
                "form": ["10-Q", "8-K", "10-K"],
                "filingDate": ["2026-08-01", "2026-07-30", "2025-10-31"],
                "accessionNumber": ["0000320193-26-000100", "0000320193-26-000090", "0000320193-25-000079"],
                "primaryDocument": ["aapl-q3.htm", "aapl-8k.htm", "aapl-10k.htm"],
            }},
        }


REFDATA = SimpleNamespace(
    sector="Technology", industry="Software", country="US",
    currency="USD", exchange="NMS",
)


def _run(coro):
    return asyncio.run(coro)


def _rows_by_level(result) -> dict[str, dict]:
    return {str(r.get("level")): r for r in result.data["rows"]}


# ── APPL#1: EDGAR identifiers ───────────────────────────────────────────────


def test_appl_delivers_cik_sic_fye_and_latest_filings_from_sec() -> None:
    fn = APPLFunction(FunctionDeps(yfinance=_FakeYfinance(REFDATA), sec_edgar=_FakeSec()))
    result = _run(fn.execute(instrument=AAPL, live=True))
    assert result.data["cik"] == "0000320193"
    assert result.data["sic_code"] == "3571"
    assert result.data["sic_description"] == "Electronic Computers"
    assert result.data["fiscal_year_end"] == "0926"
    forms = [f["form"] for f in result.data["latest_filings"]]
    assert forms == ["10-Q", "8-K", "10-K"]
    assert result.data["latest_filings"][0]["document"] == "aapl-q3.htm"
    assert "sec_edgar" in result.sources


def test_appl_sec_failure_leaves_identifiers_null_with_a_warning() -> None:
    fn = APPLFunction(FunctionDeps(yfinance=_FakeYfinance(REFDATA), sec_edgar=_FakeSec(boom=True)))
    result = _run(fn.execute(instrument=AAPL, live=True))
    assert result.data["status"] == "ok"
    assert result.data["cik"] is None
    assert result.data["sic_code"] is None
    assert result.data["fiscal_year_end"] is None
    assert result.data["latest_filings"] == []
    assert "sec_edgar" not in result.sources
    assert any("sec_edgar" in w for w in result.warnings)


def test_appl_without_sec_adapter_does_not_invent_a_cik() -> None:
    fn = APPLFunction(FunctionDeps(yfinance=_FakeYfinance(REFDATA)))
    result = _run(fn.execute(instrument=AAPL, live=True))
    assert result.data["cik"] is None
    assert any("sec_edgar" in w for w in result.warnings)


# ── APPL#2: crosswalk coverage is labelled ──────────────────────────────────


def test_crosswalk_status_marks_bundled_and_unbundled_symbols() -> None:
    fn = APPLFunction(FunctionDeps(yfinance=_FakeYfinance(REFDATA)))
    aapl = _run(fn.execute(instrument=AAPL, live=True))
    msft = _run(fn.execute(instrument=MSFT, live=True))
    assert aapl.data["crosswalk_status"] == "bundled"
    assert msft.data["crosswalk_status"] == "not_bundled"
    assert not any(str(r.get("level", "")).startswith("GICS") for r in msft.data["rows"])


# ── APPL#3 / APPL#4: honest source labels ───────────────────────────────────


def test_reference_template_rows_are_not_stamped_live_yfinance() -> None:
    fn = APPLFunction(FunctionDeps())
    result = _run(fn.execute(instrument=AAPL))
    assert result.data["status"] == "provider_unavailable"
    modes = {r.get("source_mode") for r in result.data["rows"]}
    assert "live_yfinance" not in modes, modes
    assert result.data["sector"] is None


def test_live_sources_list_the_static_crosswalk_when_it_contributes_rows() -> None:
    fn = APPLFunction(FunctionDeps(yfinance=_FakeYfinance(REFDATA)))
    result = _run(fn.execute(instrument=AAPL, live=True))
    assert "yfinance" in result.sources
    assert "taxonomy_crosswalk_static" in result.sources


def test_live_sources_omit_the_crosswalk_when_none_is_bundled() -> None:
    fn = APPLFunction(FunctionDeps(yfinance=_FakeYfinance(REFDATA)))
    result = _run(fn.execute(instrument=MSFT, live=True))
    assert result.sources == ["yfinance"]


def test_explicit_live_false_selects_the_template_path() -> None:
    fn = APPLFunction(FunctionDeps(yfinance=_FakeYfinance(REFDATA)))
    result = _run(fn.execute(instrument=AAPL, live=False))
    assert result.data["status"] == "reference_only"
    assert result.metadata.get("live") is False


def test_appl_manifest_intent_does_not_promise_gics_for_every_symbol() -> None:
    from showme.manifest.seeds.appl_seed import appl

    intent = appl.intent.lower()
    assert "gics" in intent and "bundled" in intent, appl.intent
    assert "sic" in intent and "cik" in intent, appl.intent


# ── APPL#3 (review): placeholder classifications are never returned ─────────

_PLACEHOLDERS = {"Equity", "Listed Security", "Exchange", "Global", "Market",
                 "Digital Assets", "Cryptoasset", "Foreign Exchange", "Commodities"}


def test_template_path_returns_null_classifications_not_placeholders() -> None:
    fn = APPLFunction(FunctionDeps())
    result = _run(fn.execute(instrument=MSFT))
    data = result.data
    assert data["status"] == "provider_unavailable", data
    assert data["sector"] is None and data["industry"] is None
    assert data["exchange"] is None and data["country"] is None
    assert data["currency"] is None and data["exchange_name"] is None
    assert data["reason"], data
    values = {r.get("classification") for r in data["rows"]}
    assert not (values & _PLACEHOLDERS), values
    assert all(r.get("classification") is not None for r in data["rows"])


def test_explicit_reference_path_returns_null_classifications() -> None:
    fn = APPLFunction(FunctionDeps(yfinance=_FakeYfinance(REFDATA)))
    result = _run(fn.execute(instrument=MSFT, reference=True))
    assert result.data["status"] == "reference_only", result.data
    assert result.data["sector"] is None and result.data["industry"] is None
    assert result.data["reason"], result.data
    values = {r.get("classification") for r in result.data["rows"]}
    assert not (values & _PLACEHOLDERS), values


def test_template_path_after_yfinance_error_is_honest() -> None:
    fn = APPLFunction(FunctionDeps(yfinance=_FakeYfinance(boom=True)))
    result = _run(fn.execute(instrument=AAPL, live=True))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["sector"] is None and result.data["industry"] is None
    assert "live_yfinance" not in {r.get("source_mode") for r in result.data["rows"]}
