"""WB#3: the handler honours ``region`` and the seed declares what the handler reads.

Was: ``region=em`` returned US (the handler never read the parameter), and the
seed exposed ``live_bonds`` (default False) while the handler and the pane use
``reference`` (live by default). All tests run offline with a fake FRED client.
"""
from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions._fred_csv import reset_fred_csv_cache
from showme.engine.functions.bond import wb as wb_mod
from showme.manifest.seeds.wb_seed import wb

DM = {"US", "DE", "JP", "GB", "CA", "FR", "IT", "ES", "AU"}
EM = {"TR", "BR", "MX", "ZA", "IN", "CN", "RU", "ID"}


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _AllSeriesClient:
    """Every FRED series answers with one observation (no network)."""

    async def get(self, url, timeout=None):  # noqa: ANN001
        return _Resp("observation_date,value\n2026-11-05,4.84\n")


def _run(**params):
    reset_fred_csv_cache()
    fn = wb_mod.WBFunction(FunctionDeps())
    fn._http_client = _AllSeriesClient()
    return asyncio.run(fn.execute(**params))


def _countries(result) -> set[str]:
    return {row["country"] for row in result.data["rows"]}


def test_region_em_returns_only_emerging_countries() -> None:
    result = _run(region="em")
    assert _countries(result) == EM


def test_region_dm_returns_only_developed_countries() -> None:
    result = _run(region="dm")
    assert _countries(result) == DM


def test_region_all_keeps_the_full_roster() -> None:
    result = _run(region="all")
    assert _countries(result) == DM | EM


def test_region_combines_with_explicit_countries() -> None:
    result = _run(region="em", countries="US,TR")
    assert _countries(result) == {"TR"}


def test_unknown_region_is_an_input_error_not_a_silent_all() -> None:
    result = _run(region="bogus")
    assert result.data["status"] == "input_error"
    assert result.data["rows"] == []


def test_seed_declares_the_reference_flag_the_handler_and_pane_use() -> None:
    manifest = wb
    names = {spec.name for spec in manifest.inputs}
    assert "reference" in names
    assert "live_bonds" not in names
    assert manifest.defaults["reference"] is False
    assert "live_bonds" not in manifest.methodology
    assert "live_bonds" not in " ".join(t.description for t in manifest.semantic_tests)


def test_seed_region_options_match_the_handler_buckets() -> None:
    region = next(spec for spec in wb.inputs if spec.name == "region")
    assert set(region.options) == {"all", "dm", "em"}
