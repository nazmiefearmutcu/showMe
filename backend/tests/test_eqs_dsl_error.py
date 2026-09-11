"""Bundle C / C3 regression: EQS returns a dict envelope on DSL parse failure.

Previously the DSL-error branch returned a raw pandas DataFrame as ``data``
which broke every UI consumer (they all expect ``{rows, status, ...}``).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.functions.equity.eqs import EQSFunction  # noqa: E402


async def test_dsl_parse_error_returns_dict_envelope_not_dataframe() -> None:
    fn = EQSFunction()
    # Garbage that the recursive-descent parser cannot consume.
    result = await fn.execute(instrument=None, query="???? @@ broken", live_screen=False)
    data = result.data
    assert isinstance(data, dict), (
        f"Expected dict envelope, got {type(data).__name__}"
    )
    assert data["status"] == "dsl_parse_error"
    assert "error" in data
    assert data["rows"] == []
    # ``warnings`` should also be populated.
    assert any("DSL parse error" in w for w in result.warnings)


async def test_dsl_parse_error_preserves_query_and_scanned_count() -> None:
    fn = EQSFunction()
    result = await fn.execute(instrument=None, query="@@ totally broken", live_screen=False)
    assert result.data["query"] == "@@ totally broken"
    assert isinstance(result.data["scanned"], int)
    assert result.data["scanned"] > 0  # the stub universe was built first


async def test_valid_dsl_still_returns_filtered_rows() -> None:
    """Sanity: success path unchanged."""
    fn = EQSFunction()
    result = await fn.execute(
        instrument=None,
        query="marketCap > 1000000000",
        live_screen=False,
    )
    # Success path returns a DataFrame as ``data`` (legacy contract is fine here).
    import pandas as pd
    assert isinstance(result.data, pd.DataFrame)
    assert len(result.data) > 0


# ---------------------------------------------------------------------------
# F6 — zero-match honesty and live-fallback labelling
# ---------------------------------------------------------------------------


async def test_zero_match_returns_empty_rows_not_head3() -> None:
    """F6 C-fix: a query matching nothing must NOT return df.head(3) as matches.

    Previously `filtered.empty -> filtered = df.head(3)` shipped non-matching
    rows and metadata.matched=3, so the pane showed "MATCHED 3" for a query
    that matched nothing.
    """
    fn = EQSFunction()
    result = await fn.execute(
        instrument=None,
        query='symbol = "ZZZZ"',
        live_screen=False,
    )
    data = result.data
    assert isinstance(data, dict)
    assert data["status"] == "no_matches"
    assert data["rows"] == []
    assert result.metadata["matched"] == 0
    # No fabricated rows may surface anywhere on the envelope.
    assert result.metadata.get("matched") == 0


async def test_live_screen_without_provider_is_unavailable_not_template() -> None:
    """F6 C-fix: live_screen=True must never serve template rows as yfinance."""
    fn = EQSFunction()
    result = await fn.execute(
        instrument=None,
        query="marketCap > 0",
        live_screen=True,
        universe="AAPL,MSFT,NVDA",
    )
    data = result.data
    assert isinstance(data, dict)
    assert data["status"] == "provider_unavailable"
    assert data["rows"] == []
    assert "yfinance" not in result.sources
    assert result.metadata.get("fallback") is True
    assert result.metadata.get("live") is False


async def test_live_screen_provider_failure_is_unavailable_not_template() -> None:
    """A firing-but-failing yfinance adapter is still an honest outage."""

    class _BoomYF:
        async def fetch(self, request):
            raise RuntimeError("yfinance down")

    fn = EQSFunction(deps=_deps_with_yfinance(_BoomYF()))
    result = await fn.execute(
        instrument=None,
        query="marketCap > 0",
        live_screen=True,
        universe="AAPL,MSFT,NVDA",
    )
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert "yfinance" not in result.sources


async def test_live_screen_with_provider_returns_yfinance_rows_and_metadata() -> None:
    """Live rows keep the yfinance attribution and universe truth in metadata."""
    from types import SimpleNamespace

    class _FakeYF:
        async def fetch(self, request):
            raw = {
                "trailingPE": 24.0,
                "priceToBook": 6.0,
                "priceToSalesTrailing12Months": 5.0,
                "dividendYield": 0.01,
                "beta": 1.2,
                "sector": "Technology",
                "industry": "Software",
                "marketCap": 1.0e11,
                "country": "US",
            }
            return SimpleNamespace(
                sector="Technology",
                industry="Software",
                market_cap=1.0e11,
                country="US",
                extras={"raw": raw},
            )

    fn = EQSFunction(deps=_deps_with_yfinance(_FakeYF()))
    result = await fn.execute(
        instrument=None,
        query="marketCap > 1000000000",
        live_screen=True,
        universe="AAPL,MSFT,NVDA",
    )
    import pandas as pd

    assert isinstance(result.data, pd.DataFrame)
    assert len(result.data) > 0
    assert "yfinance" in result.sources
    assert result.metadata.get("live") is True
    assert result.metadata.get("template") is False
    assert result.metadata.get("data_mode") == "delayed_reference"
    assert result.metadata.get("universe") == "custom (3 symbols)"
    assert result.metadata.get("universe_size") == 3


async def test_template_mode_is_labelled_as_model() -> None:
    """Explicit template mode keeps its rows but is labelled a model."""
    fn = EQSFunction()
    result = await fn.execute(
        instrument=None,
        query="marketCap > 0",
        live_screen=False,
    )
    assert result.metadata.get("template") is True
    assert result.metadata.get("data_mode") == "modeled"
    assert result.metadata.get("live") is False
    assert result.sources == ["equity_screener_model"]
    assert any("model" in w.lower() for w in result.warnings)


def _deps_with_yfinance(adapter):
    from showme.engine.core.base_function import FunctionDeps

    return FunctionDeps(yfinance=adapter)
