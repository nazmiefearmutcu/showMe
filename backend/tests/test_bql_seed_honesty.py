"""BQL seed must not advertise data modes or fallbacks the function never produces.

BQL has no offline price model and no cached snapshot store: rows come only
from the yfinance OHLCV adapter (live) or are absent (provider_unavailable /
input_required). The manifest's provider chain and field dictionary are what
the catalog and UI present as provenance, so they must match that.
"""
from __future__ import annotations

from showme.manifest import REGISTRY, load_seeds
from showme.manifest.enums import DataMode


def _bql_entry():
    load_seeds()
    return REGISTRY.get("BQL")


def test_bql_seed_does_not_accept_modeled_data_mode() -> None:
    entry = _bql_entry()
    assert DataMode.MODELED not in entry.provider_chain.acceptable_modes, (
        "BQL serves no modeled rows; MODELED in acceptable_modes would present model output as provider data."
    )


def test_bql_seed_does_not_claim_cached_snapshot_fallback() -> None:
    entry = _bql_entry()
    assert DataMode.CACHED_SNAPSHOT not in entry.provider_chain.acceptable_modes
    assert "cached_snapshot" not in entry.provider_chain.fallbacks, (
        "BQL has no snapshot store; cached_snapshot is not a real fallback for this function."
    )


def test_bql_seed_fallback_is_the_yfinance_ohlcv_adapter() -> None:
    entry = _bql_entry()
    assert entry.provider_chain.fallbacks == ["yfinance"]


def test_bql_seed_close_field_is_described_as_yfinance_ohlcv() -> None:
    entry = _bql_entry()
    description = entry.field_dict["rows[].close"].description or ""
    assert "yfinance" in description.lower(), (
        "rows[].close comes from the yfinance OHLCV close; the seed must not describe it as generic provider last price."
    )
