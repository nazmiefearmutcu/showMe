"""WB: a failed live fetch is an explicit provider_unavailable state, not template rows.

Before the fix, when every keyless FRED series failed the handler returned the
static reference template with source_mode sovereign_yield_model and no
data.status. The template is served only when the caller asks for it
(reference=true). All network calls are faked; nothing leaves the process.
"""
from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions._fred_csv import reset_fred_csv_cache
from showme.engine.functions.bond import wb as wb_mod


class _Down:
    async def get(self, url, timeout=None):  # noqa: ANN001
        raise RuntimeError("keyless csv unavailable")


def _run(**params):
    reset_fred_csv_cache()
    fn = wb_mod.WBFunction(FunctionDeps())
    fn._http_client = _Down()
    return asyncio.run(fn.execute(**params))


def test_total_live_outage_is_provider_unavailable_with_no_rows() -> None:
    result = _run(countries="US,DE,TR")
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.data["reason"]
    assert result.data["next_actions"]
    assert result.data["missing_countries"] == ["DE", "TR", "US"]
    assert result.sources == []
    assert result.metadata.get("live") is False


def test_total_live_outage_never_substitutes_template_values() -> None:
    result = _run(countries="US,TR")
    assert result.data["rows"] == []
    assert "sovereign_yield_model" not in result.sources
    assert all(row.get("source_mode") != "sovereign_yield_model" for row in result.data["rows"])
    assert result.warnings
