"""IndicatorCatalog loader unit tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from showme.indicators.catalog.loader import (
    IndicatorCatalog, IndicatorCatalogError, IndicatorEntry,
    load_indicator_catalog,
)

YAML = """
- id: rsi
  display_name: RSI
  family: momentum
  short_description: "Aşırı alım/satım"
  long_description: "Wilder 1978"
  formula: "100 - 100/(1+RS)"
  parameters:
    - name: period
      type: int
      default: 14
      min: 2
      max: 100
      effect: "düşür → hızlı sinyal"
  confidence: 9
  confidence_rationale: "range piyasada güvenilir"
  suggested_strategy:
    name: "RSI mean-revert"
    summary: "Temel"
    rules: ["entry: <30", "exit: >70"]
  references: ["Wilder 1978"]

- id: macd
  display_name: MACD
  family: momentum
  confidence: 9
"""


def test_load_parses(tmp_path: Path):
    f = tmp_path / "ind.yml"
    f.write_text(YAML)
    cat = load_indicator_catalog(f)
    assert isinstance(cat, IndicatorCatalog)
    assert len(cat.entries) == 2
    rsi = cat.by_id("rsi")
    assert isinstance(rsi, IndicatorEntry)
    assert rsi.family == "momentum"
    assert rsi.confidence == 9
    assert len(rsi.parameters) == 1
    assert rsi.parameters[0].name == "period"


def test_by_id_missing_raises(tmp_path: Path):
    f = tmp_path / "ind.yml"
    f.write_text(YAML)
    cat = load_indicator_catalog(f)
    with pytest.raises(KeyError):
        cat.by_id("missing")


def test_search_by_family(tmp_path: Path):
    f = tmp_path / "ind.yml"
    f.write_text(YAML)
    cat = load_indicator_catalog(f)
    hits = cat.search("momentum")
    assert {e.id for e in hits} == {"rsi", "macd"}


def test_filter_by_family(tmp_path: Path):
    f = tmp_path / "ind.yml"
    f.write_text(YAML)
    cat = load_indicator_catalog(f)
    hits = cat.filter(family="momentum")
    assert {e.id for e in hits} == {"rsi", "macd"}


def test_missing_required_raises(tmp_path: Path):
    f = tmp_path / "bad.yml"
    f.write_text("- id: foo\n  display_name: Foo\n  family: x\n")  # missing confidence
    with pytest.raises(IndicatorCatalogError):
        load_indicator_catalog(f)


def test_confidence_out_of_range_raises(tmp_path: Path):
    f = tmp_path / "bad.yml"
    f.write_text("- id: foo\n  display_name: Foo\n  family: x\n  confidence: 15\n")
    with pytest.raises(IndicatorCatalogError):
        load_indicator_catalog(f)


def test_real_catalog_loads_15_entries():
    """Smoke against the bundled indicators.yml — must have at least 15."""
    p = Path(__file__).resolve().parents[1] / "showme" / "indicators" / "catalog" / "indicators.yml"
    cat = load_indicator_catalog(p)
    assert len(cat.entries) >= 15
    for required_id in ["rsi", "macd", "ema", "sma", "bollinger_bands", "stochastic",
                        "atr", "adx", "cci", "obv", "williams_r", "vwap",
                        "ichimoku", "parabolic_sar", "kdj"]:
        # Should not raise
        e = cat.by_id(required_id)
        assert e.confidence >= 1 and e.confidence <= 10
