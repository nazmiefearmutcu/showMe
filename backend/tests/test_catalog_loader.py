"""CatalogEntry / Catalog / load_catalog unit tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from showme.brokers.catalog.loader import (
    Catalog,
    CatalogEntry,
    CatalogError,
    load_catalog,
)


CATALOG_YAML = """
# header
- id: binance
  display_name: Binance
  aliases: [binance.com]
  asset_classes: [spot, futures]
  regions: [global]
  adapter: ccxt
  ccxt_id: binance
  requires: [api_key, api_secret]
  optional: []
  capabilities:
    fetch_balance: true
    fetch_positions: true
    fetch_open_orders: true
    create_order: true
    cancel_order: true

- id: okx
  display_name: OKX
  aliases: []
  asset_classes: [spot, futures, swap]
  regions: [global]
  adapter: ccxt
  ccxt_id: okx
  requires: [api_key, api_secret, passphrase]
  optional: []
  capabilities:
    fetch_balance: true
    fetch_positions: true
    fetch_open_orders: true
    create_order: true
    cancel_order: true
"""


def test_load_catalog_parses_entries(tmp_path: Path) -> None:
    f = tmp_path / "ex.yml"
    f.write_text(CATALOG_YAML)
    cat = load_catalog(f)
    assert isinstance(cat, Catalog)
    assert len(cat.entries) == 2
    binance = cat.by_id("binance")
    assert isinstance(binance, CatalogEntry)
    assert binance.adapter == "ccxt"
    assert binance.requires == ("api_key", "api_secret")
    assert binance.capabilities["fetch_balance"] is True


def test_by_id_unknown_raises(tmp_path: Path) -> None:
    f = tmp_path / "ex.yml"
    f.write_text(CATALOG_YAML)
    cat = load_catalog(f)
    with pytest.raises(KeyError):
        cat.by_id("does-not-exist")


def test_okx_requires_passphrase(tmp_path: Path) -> None:
    f = tmp_path / "ex.yml"
    f.write_text(CATALOG_YAML)
    cat = load_catalog(f)
    okx = cat.by_id("okx")
    assert "passphrase" in okx.requires


def test_search_by_display_name(tmp_path: Path) -> None:
    f = tmp_path / "ex.yml"
    f.write_text(CATALOG_YAML)
    cat = load_catalog(f)
    hits = cat.search("binan")
    assert [e.id for e in hits] == ["binance"]


def test_filter_by_region(tmp_path: Path) -> None:
    f = tmp_path / "ex.yml"
    f.write_text(CATALOG_YAML)
    cat = load_catalog(f)
    hits = cat.filter(regions=("global",))
    assert {e.id for e in hits} == {"binance", "okx"}


def test_missing_required_field_raises(tmp_path: Path) -> None:
    bad = "\n".join(["- id: foo", "  display_name: Foo"])  # missing adapter
    f = tmp_path / "bad.yml"
    f.write_text(bad)
    with pytest.raises(CatalogError):
        load_catalog(f)
