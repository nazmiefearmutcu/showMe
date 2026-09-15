"""SECF security-master expansion pins (S&P 500-scale bundled universe).

The master is generated once at dev time by
``scripts/generate_security_master.py`` and committed to the repo tree; SECF
loads it with a memoized loader and falls back to its curated rows when the
file is missing.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.screen import _funcs
from showme.engine.functions.screen._funcs import SECFFunction, _security_reference_rows

_REQUIRED_SYMBOLS = {
    # pinned curated identifiers
    "AAPL", "MSFT", "NVDA", "JPM", "SPY", "TLT", "BTCUSDT", "ETHUSDT",
    "EURUSD", "GC=F", "CL=F", "US10Y", "^GSPC",
    # ETFs
    "QQQ", "IWM", "DIA", "GLD", "SLV", "XLE", "XLF", "XLK", "XLV", "XLI",
    "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
    # crypto majors
    "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
    "LINKUSDT", "LTCUSDT", "DOTUSDT", "UNIUSDT",
    # FX majors
    "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP",
    "EURJPY",
    # commodities
    "SI=F", "NG=F", "HG=F",
    # indices
    "^NDX", "^DJI", "^RUT", "^VIX", "^TNX",
}


class _FakeQuoteProvider:
    """Counts provider fan-out; every symbol resolves to no quote."""

    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, request: Any) -> Any:
        self.calls += 1
        return None


def test_secf_master_file_is_committed_and_sp500_scale() -> None:
    assert _funcs._SECURITY_MASTER_PATH.exists(), "bundled security_master.json missing"
    payload = json.loads(_funcs._SECURITY_MASTER_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload.get("rows"), list)
    assert len(payload["rows"]) >= 400


def test_secf_master_contains_required_symbols_and_tags() -> None:
    rows = _security_reference_rows()
    assert len(rows) >= 400
    by_symbol = {str(row["symbol"]): row for row in rows}
    assert _REQUIRED_SYMBOLS <= set(by_symbol)
    for symbol in ("AAPL", "MSFT", "NVDA", "ORCL", "CRM", "XLK", "QQQ"):
        row = by_symbol[symbol]
        assert row["name"] and row["exchange"] and row["asset_class"]
        assert isinstance(row["tags"], list) and row["tags"]
    tech_tags = " ".join(by_symbol["ORCL"]["tags"]).lower()
    assert "technology" in tech_tags
    # ETFs/crypto/FX keep their asset classes distinct.
    assert by_symbol["QQQ"]["asset_class"] == "ETF"
    assert by_symbol["SOLUSDT"]["asset_class"] == "CRYPTO"
    assert by_symbol["USDJPY"]["asset_class"] == "FX"
    assert by_symbol["^VIX"]["asset_class"] == "INDEX"


def test_secf_scanned_reports_master_size() -> None:
    master_size = len(_security_reference_rows())
    out = asyncio.run(
        SECFFunction().execute(query="technology", reference=True, limit=50)
    )
    assert out.data["scanned"] == master_size >= 400
    assert out.data["matched"] >= 50
    assert out.metadata["scanned"] == master_size


def test_secf_tech_query_matches_many_rows() -> None:
    out = asyncio.run(SECFFunction().execute(query="tech", reference=True, limit=50))
    assert out.data["matched"] >= 20
    assert len(out.data["rows"]) >= 20
    assert all(row.get("match") for row in out.data["rows"])


def test_secf_apple_query_includes_aapl() -> None:
    out = asyncio.run(SECFFunction().execute(query="apple", reference=True))
    symbols = {row["symbol"] for row in out.data["rows"]}
    assert "AAPL" in symbols


def test_secf_live_enrichment_capped_to_returned_page() -> None:
    provider = _FakeQuoteProvider()
    out = asyncio.run(
        SECFFunction(FunctionDeps(yfinance=provider)).execute(query="tech", limit=25)
    )
    assert out.data["scanned"] >= 400
    assert len(out.data["rows"]) == 25
    # One quote fetch per RETURNED row — never one per scanned row.
    assert provider.calls == len(out.data["rows"]) == 25
    # No quotes came back, so the page stays unlabelled rather than faking live.
    assert all("last" not in row for row in out.data["rows"])


def test_secf_reference_mode_never_calls_provider() -> None:
    provider = _FakeQuoteProvider()
    out = asyncio.run(
        SECFFunction(FunctionDeps(yfinance=provider)).execute(
            query="tech", reference=True, limit=25
        )
    )
    assert provider.calls == 0
    assert out.sources == ["showme_security_master_reference"]


def test_secf_falls_back_to_curated_rows_when_master_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(_funcs, "_SECURITY_MASTER_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(_funcs, "_SECURITY_MASTER_CACHE", None)
    rows = _security_reference_rows()
    assert len(rows) == len(_funcs._SECURITY_FALLBACK_ROWS) == 13
    out = asyncio.run(SECFFunction().execute(query="technology", reference=True))
    assert out.data["scanned"] == 13
