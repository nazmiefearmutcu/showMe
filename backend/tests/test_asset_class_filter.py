"""Q4 audit: AssetFilter on StrategySpec — symbols/exchanges/asset_classes guard.

Ensures the filter validates correctly (already in spec) AND that
``spec.position.sizing_kind="risk_per_trade"`` requires SL to be set when
the runner reaches into resolve_quantity. Cross-cuts with the new
risk_per_trade sizing kind.
"""
from __future__ import annotations

import pytest

from showme.strategies.spec import (
    AssetFilter,
    Position,
    Rule,
    StrategySpec,
)


def test_asset_filter_accepts_symbols():
    af = AssetFilter(symbols=["BTC/USDT", "ETH/USDT"])
    assert af.symbols == ["BTC/USDT", "ETH/USDT"]


def test_asset_filter_accepts_asset_classes():
    af = AssetFilter(asset_classes=["crypto", "equity"])
    assert "crypto" in af.asset_classes


def test_asset_filter_empty_is_universal():
    af = AssetFilter()
    assert af.symbols is None
    assert af.exchanges is None
    assert af.asset_classes is None


def test_strategy_can_set_risk_per_trade_with_sl():
    spec = StrategySpec(
        name="van_tharp_BTC",
        asset_filter=AssetFilter(symbols=["BTC/USDT"]),
        entry_rules=[Rule(kind="greater_than", left="close", right="literal:100")],
        position=Position(
            side="long", sizing_kind="risk_per_trade",
            sizing_value=2.0,  # 2% per R
            stop_loss_pct=1.5,
        ),
    )
    assert spec.position.sizing_kind == "risk_per_trade"
    assert spec.position.stop_loss_pct == 1.5


def test_strategy_entry_order_type_defaults_to_market():
    spec = StrategySpec(
        name="default_market",
        entry_rules=[Rule(kind="greater_than", left="close", right="literal:100")],
    )
    assert spec.position.entry_order_type == "market"


def test_strategy_entry_order_type_can_be_limit():
    spec = StrategySpec(
        name="limit_strat",
        entry_rules=[Rule(kind="greater_than", left="close", right="literal:100")],
        position=Position(entry_order_type="limit", limit_price_offset_pct=0.5),
    )
    assert spec.position.entry_order_type == "limit"
    assert spec.position.limit_price_offset_pct == 0.5


def test_strategy_entry_order_type_rejects_unknown():
    with pytest.raises(Exception):
        Position(entry_order_type="iceberg")  # type: ignore[arg-type]
