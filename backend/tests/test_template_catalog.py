"""Template catalog loader + roundtrip tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from showme.templates.loader import (
    TemplateCatalog, TemplateCatalogError, TemplateEntry, load_template_catalog,
)


YAML = """
- id: rsi-mr
  name: "RSI MR"
  family: momentum
  uses_indicators: [rsi]
  recommended_timeframe: "1h"
  natural_language_explanation: "NL"
  math: "M"
  spec_template:
    name: "X"
    timeframe: "1h"
    indicators: [{alias: r14, id: rsi, params: {period: 14}}]
    entry_rules: [{kind: crosses_below, left: r14, right: "literal:30"}]
    exit_rules: [{kind: crosses_above, left: r14, right: "literal:70"}]

- id: macd-c
  name: "MACD C"
  family: momentum
  uses_indicators: [macd]
  spec_template:
    name: "Y"
    indicators: [{alias: m, id: macd}]
"""


def test_load_parses(tmp_path: Path):
    f = tmp_path / "t.yml"; f.write_text(YAML)
    cat = load_template_catalog(f)
    assert isinstance(cat, TemplateCatalog)
    assert len(cat.entries) == 2
    e = cat.by_id("rsi-mr")
    assert isinstance(e, TemplateEntry)
    assert e.uses_indicators == ("rsi",)


def test_by_id_missing(tmp_path: Path):
    f = tmp_path / "t.yml"; f.write_text(YAML)
    cat = load_template_catalog(f)
    with pytest.raises(KeyError):
        cat.by_id("missing")


def test_search(tmp_path: Path):
    f = tmp_path / "t.yml"; f.write_text(YAML)
    cat = load_template_catalog(f)
    hits = cat.search("momentum")
    assert {e.id for e in hits} == {"rsi-mr", "macd-c"}


def test_filter_by_indicator(tmp_path: Path):
    f = tmp_path / "t.yml"; f.write_text(YAML)
    cat = load_template_catalog(f)
    hits = cat.filter(indicator="macd")
    assert {e.id for e in hits} == {"macd-c"}


def test_missing_required_raises(tmp_path: Path):
    f = tmp_path / "bad.yml"
    f.write_text("- id: foo\n  name: F\n")  # missing uses_indicators + spec_template
    with pytest.raises(TemplateCatalogError):
        load_template_catalog(f)


def test_real_catalog_loads_12_entries():
    p = Path(__file__).resolve().parents[1] / "showme" / "templates" / "catalog" / "templates.yml"
    cat = load_template_catalog(p)
    assert len(cat.entries) >= 12
    for required_id in ["rsi-mean-revert", "macd-cross", "ema-crossover",
                        "golden-cross", "bb-squeeze-breakout", "stoch-oversold",
                        "adx-trend-filter", "vwap-pullback", "ichimoku-cloud-break",
                        "parabolic-trail", "atr-volatility-breakout", "williams-r-reverse"]:
        e = cat.by_id(required_id)
        assert len(e.uses_indicators) >= 1
        assert e.spec_template


def test_spec_template_validates_through_strategy_spec():
    """Each shipped template's spec_template should be a valid StrategySpec body."""
    from showme.strategies.spec import StrategySpec
    p = Path(__file__).resolve().parents[1] / "showme" / "templates" / "catalog" / "templates.yml"
    cat = load_template_catalog(p)
    for e in cat.entries:
        # StrategySpec validation tolerates extra fields; just verify pydantic accepts it.
        spec = StrategySpec(**e.spec_template)
        assert spec.name
