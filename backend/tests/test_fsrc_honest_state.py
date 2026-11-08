"""FSRC — curated AUM / YTD labelling (finding FSRC#1).

AUM and YTD are curated reference values with no as-of date and no provider
refresh. Every row must say so (aum_state / ytd_state = "reference") and the
payload must carry a warning, on the live overlay path and the reference path
alike. Offline: the quote provider is an injected fake.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.quote import Quote
from showme.engine.functions.screen._funcs import FSRCFunction


class _QuoteProvider:
    name = "yfinance"

    async def fetch(self, request: object) -> Quote | None:
        symbol = str(getattr(getattr(request, "instrument", None), "symbol", ""))
        return Quote(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            last=100.0,
            close_prev=99.0,
        )


def test_live_overlay_rows_label_curated_aum_and_ytd_as_reference() -> None:
    out = asyncio.run(
        FSRCFunction(deps=FunctionDeps(yfinance=_QuoteProvider())).execute(
            query="expenseRatio <= 0.001", limit=50
        )
    )
    assert out.data["rows"], "expected matching live rows"
    for row in out.data["rows"]:
        assert row.get("aum_state") == "reference", row["symbol"]
        assert row.get("ytd_state") == "reference", row["symbol"]
    assert any("curated" in w.lower() for w in out.warnings), out.warnings


def test_reference_path_also_labels_curated_aum_and_ytd() -> None:
    out = asyncio.run(
        FSRCFunction(deps=FunctionDeps()).execute(query="expenseRatio <= 0.001")
    )
    assert out.data["rows"]
    assert all(row.get("aum_state") == "reference" for row in out.data["rows"])
    assert all(row.get("ytd_state") == "reference" for row in out.data["rows"])
    assert any("curated" in w.lower() for w in out.warnings), out.warnings


def test_field_dictionary_documents_reference_state() -> None:
    out = asyncio.run(FSRCFunction(deps=FunctionDeps()).execute(query="expenseRatio <= 0.001"))
    fields = {entry["field"]: entry["meaning"] for entry in out.data["field_dictionary"]}
    assert "aum_state" in fields and "ytd_state" in fields
    assert "curated" in fields["aum_usd"].lower()
