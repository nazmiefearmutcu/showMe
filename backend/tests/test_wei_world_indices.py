"""WEI — world equity index coverage + honesty contract.

P1: the curated world-index set must be comprehensive (>= 30 symbols),
balanced across every region, and every symbol must carry meta
(name + region). P1b: a live fetch that only resolves part of the
universe must still return EVERY symbol — unresolved ones as explicit
``last=None`` rows, never silently dropped. P2: the non-live / fallback
path must label its rows ``market_state == "model"`` and carry an
``as_of`` timestamp so the UI can mark the data as model-not-live.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.quote import Quote
from showme.engine.functions.screen._funcs import (
    WEIFunction,
    _WORLD_INDEX_BASELINE,
    _WORLD_INDEX_META,
    _complete_world_index_rows,
    _world_index_symbols,
    _world_index_template,
)

_REGIONS = {"americas", "europe", "asia", "mea"}

# Tickers that were probed live from this machine (Yahoo chart) and must
# stay in the universe: the Asia + Europe + MEA expansion that fixed the
# "world is missing its eastern half" complaint.
_VERIFIED_GLOBAL_TICKERS = {
    "^N225", "^HSI", "000001.SS", "399001.SZ", "^KS11", "^TWII", "^AXJO",
    "^NZ50", "^STI", "^KLSE", "^JKSE", "^SET", "PSEI.PS",
    "XU100.IS", "WIG20.WA", "^BFX", "OBX.OL",
}


class _PartialProvider:
    """yfinance-shaped provider that only resolves a subset of symbols."""

    def __init__(self, resolves: set[str]):
        self.resolves = resolves
        self.calls = 0

    async def fetch(self, request: object) -> Quote | None:
        self.calls += 1
        symbol = str(getattr(getattr(request, "instrument", None), "symbol", ""))
        if symbol not in self.resolves:
            return None
        return Quote(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            last=100.0,
            close_prev=99.0,
        )


def test_world_index_symbol_set_is_comprehensive_and_balanced() -> None:
    symbols = _world_index_symbols()
    # Comprehensive: a real macro monitor, not a token handful.
    assert len(symbols) >= 30, f"expected >= 30 indices, got {len(symbols)}"
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


def test_verified_global_tickers_are_configured() -> None:
    # The eastern hemisphere must actually be on the board: Nikkei, Hang
    # Seng, Shanghai/Shenzhen, KOSPI, TAIEX, ASX, NZX, STI, KLCI, Jakarta,
    # Thailand, Philippines + Warsaw/Brussels/Oslo + BIST.
    missing = _VERIFIED_GLOBAL_TICKERS - set(_world_index_symbols())
    assert not missing, f"verified global indices missing from universe: {missing}"


def test_each_region_has_multiple_indices() -> None:
    counts = {region: 0 for region in _REGIONS}
    for sym in _world_index_symbols():
        counts[_WORLD_INDEX_META[sym]["region"]] += 1
    for region, n in counts.items():
        assert n >= 2, f"region {region} only has {n} index(es)"


def test_every_symbol_has_a_baseline_so_template_never_defaults() -> None:
    # Guards META/BASELINE drift: a symbol added to META without a baseline
    # would silently render a wrong-magnitude ~1000.0 model level.
    missing = set(_world_index_symbols()) - set(_WORLD_INDEX_BASELINE.keys())
    assert not missing, f"symbols missing from _WORLD_INDEX_BASELINE: {missing}"


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


def test_partial_live_fetch_never_drops_unresolved_symbols() -> None:
    """A live poll that resolves only some symbols still returns the WHOLE
    universe; unresolved rows carry ``last=None`` and are labelled
    ``market_state="unavailable"`` (no silent drops, no model padding)."""
    provider = _PartialProvider({"^GSPC", "^N225"})
    out = asyncio.run(WEIFunction(deps=FunctionDeps(yfinance=provider)).execute())
    assert provider.calls >= len(_world_index_symbols()) - 4, (
        "every configured symbol must be requested each cycle"
    )
    rows = out.data["rows"]
    assert {row["symbol"] for row in rows} == set(_world_index_symbols())
    by_symbol = {row["symbol"]: row for row in rows}
    assert by_symbol["^GSPC"]["last"] == 100.0
    assert by_symbol["^GSPC"]["market_state"] == "live"
    unresolved = [row for row in rows if row["symbol"] not in {"^GSPC", "^N225"}]
    assert unresolved, "test needs unresolved rows"
    for row in unresolved:
        assert row["last"] is None
        assert row["change_pct"] is None
        assert row["market_state"] == "unavailable"
        assert row["name"] and row["region"]
    assert out.data["status"] == "ok"
    assert out.data["resolved"] == 2
    assert out.data["unresolved"] == len(rows) - 2
    assert any("unavailable" in w for w in out.warnings)


def test_complete_world_index_rows_keeps_meta_order_and_labels() -> None:
    merged = _complete_world_index_rows([{"symbol": "^HSI", "last": 19000.0}])
    assert [row["symbol"] for row in merged] == _world_index_symbols()
    hsi = next(row for row in merged if row["symbol"] == "^HSI")
    assert hsi["region"] == "asia" and hsi["name"] == "Hang Seng"
    dropped = next(row for row in merged if row["symbol"] == "^GSPC")
    assert dropped["last"] is None and dropped["market_state"] == "unavailable"


def test_non_live_payload_is_model_with_as_of() -> None:
    # Explicit live=False opts into the labelled deterministic template; the
    # default path (L9) attempts live quotes first and degrades to a
    # provider_unavailable envelope carrying the same labelled template.
    out = asyncio.run(WEIFunction().execute(live=False))
    rows = out.data["rows"]
    assert rows, "non-live WEI returned no rows"
    assert all(r.get("market_state") == "model" for r in rows)
    # Honesty: a real data freshness stamp must be present.
    assert out.data.get("as_of"), "non-live WEI payload missing as_of timestamp"
    assert out.data.get("source_mode") == "world_index_template"
    assert out.data.get("status") == "ok"
    assert out.metadata.get("live") is False
    assert out.metadata.get("fallback") is True
