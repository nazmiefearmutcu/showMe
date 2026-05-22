"""StrategySpec pydantic validation tests."""
from __future__ import annotations

import json
import pytest

from showme.strategies.spec import (
    AssetFilter, IndicatorRef, Position, Rule, StrategySpec,
)


def _minimal_spec() -> StrategySpec:
    return StrategySpec(
        name="t",
        indicators=[IndicatorRef(alias="rsi14", id="rsi", params={"period": 14})],
        entry_rules=[Rule(kind="crosses_below", left="rsi14", right="literal:30")],
        exit_rules=[Rule(kind="crosses_above", left="rsi14", right="literal:70")],
    )


def test_spec_roundtrip():
    s = _minimal_spec()
    s2 = StrategySpec.from_json(s.to_json())
    assert s2.name == s.name
    assert s2.indicators[0].alias == "rsi14"
    assert s2.entry_rules[0].kind == "crosses_below"


def test_alias_uniqueness():
    with pytest.raises(Exception):
        StrategySpec(
            name="t",
            indicators=[
                IndicatorRef(alias="r", id="rsi"),
                IndicatorRef(alias="r", id="ema"),
            ],
        )


def test_validate_unknown_indicator():
    s = _minimal_spec()
    with pytest.raises(ValueError, match="unknown indicator"):
        s.validate_against_catalog({"ema"})  # rsi not in catalog


def test_validate_unknown_operand():
    s = StrategySpec(
        name="t",
        indicators=[IndicatorRef(alias="r", id="rsi")],
        entry_rules=[Rule(kind="crosses_below", left="bogus", right="literal:30")],
    )
    with pytest.raises(ValueError, match="unknown operand"):
        s.validate_against_catalog({"rsi"})


def test_validate_price_field_allowed():
    s = StrategySpec(
        name="t",
        indicators=[IndicatorRef(alias="sma200", id="sma", params={"period": 200})],
        entry_rules=[Rule(kind="greater_than", left="close", right="sma200")],
    )
    s.validate_against_catalog({"sma"})  # should not raise


def test_validate_bad_literal():
    s = StrategySpec(
        name="t",
        indicators=[IndicatorRef(alias="r", id="rsi")],
        entry_rules=[Rule(kind="greater_than", left="r", right="literal:abc")],
    )
    with pytest.raises(ValueError, match="invalid literal"):
        s.validate_against_catalog({"rsi"})


def test_equals_approximately_requires_tolerance():
    s = StrategySpec(
        name="t",
        indicators=[IndicatorRef(alias="r", id="rsi")],
        entry_rules=[Rule(kind="equals_approximately", left="r", right="literal:50")],
    )
    with pytest.raises(ValueError, match="tolerance"):
        s.validate_against_catalog({"rsi"})
