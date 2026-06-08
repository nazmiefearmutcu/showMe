"""WEI — world equity index coverage + honesty contract.

P1: the curated world-index set must be comprehensive (>= 25 symbols),
balanced across every region, and every symbol must carry meta
(name + region). P2: the non-live / fallback path must label its rows
``market_state == "model"`` and carry an ``as_of`` timestamp so the UI
can mark the data as model-not-live.
"""

from __future__ import annotations

import asyncio

from showme.engine.functions.screen._funcs import (
    WEIFunction,
    _WORLD_INDEX_META,
    _world_index_symbols,
    _world_index_template,
)

_REGIONS = {"americas", "europe", "asia", "mea"}


def test_world_index_symbol_set_is_comprehensive_and_balanced() -> None:
    symbols = _world_index_symbols()
    # Comprehensive: a real macro monitor, not a token handful.
    assert len(symbols) >= 25, f"expected >= 25 indices, got {len(symbols)}"
    # No duplicates.
    assert len(symbols) == len(set(symbols)), "duplicate symbols in world-index set"
    # Every region represented.
    regions = {_WORLD_INDEX_META[s]["region"] for s in symbols}
    assert _REGIONS <= regions, f"missing regions: {_REGIONS - regions}"


def test_every_world_index_symbol_has_name_and_region_meta() -> None:
    for sym in _world_index_symbols():
        meta = _WORLD_INDEX_META.get(sym)
        assert meta is not None, f"{sym} missing from _WORLD_INDEX_META"
        assert meta.get("name"), f"{sym} meta has no name"
        assert meta.get("region") in _REGIONS, f"{sym} meta region invalid: {meta.get('region')}"


def test_each_region_has_multiple_indices() -> None:
    counts = {region: 0 for region in _REGIONS}
    for sym in _world_index_symbols():
        counts[_WORLD_INDEX_META[sym]["region"]] += 1
    for region, n in counts.items():
        assert n >= 2, f"region {region} only has {n} index(es)"


def test_template_derives_from_symbol_set_and_is_labelled_model() -> None:
    template = _world_index_template()
    template_symbols = {row["symbol"] for row in template}
    assert template_symbols == set(_world_index_symbols()), (
        "template must cover exactly the curated world-index set"
    )
    for row in template:
        assert row.get("market_state") == "model", (
            f"{row['symbol']} fallback row not labelled model"
        )
        assert row.get("name"), f"{row['symbol']} template row missing name"
        assert row.get("region") in _REGIONS, f"{row['symbol']} template region invalid"


def test_non_live_payload_is_model_with_as_of() -> None:
    # No yfinance dep wired ⇒ deterministic template path.
    out = asyncio.run(WEIFunction().execute())
    rows = out.data["rows"]
    assert rows, "non-live WEI returned no rows"
    assert all(r.get("market_state") == "model" for r in rows)
    # Honesty: a real data freshness stamp must be present.
    assert out.data.get("as_of"), "non-live WEI payload missing as_of timestamp"
    assert out.data.get("source_mode") == "world_index_template"
