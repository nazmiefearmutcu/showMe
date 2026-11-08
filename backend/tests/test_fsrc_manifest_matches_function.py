"""FSRC manifest must describe the served fund/ETF screener (finding FSRC#3).

The served class FSRCFunction is the Fund Screener (fund/ETF reference
universe, expenseRatio / aum / category predicates). The manifest seed used to
describe a listed-futures screener, so the registry and the B1 audit checked the
wrong product.
"""

from __future__ import annotations

from showme.manifest import REGISTRY, AssetClass, load_seeds


def _fsrc():
    load_seeds()
    return REGISTRY.get("FSRC")


def test_manifest_name_and_intent_describe_fund_screener() -> None:
    entry = _fsrc()
    assert entry.name == "Fund Screener"
    text = (entry.intent + " " + entry.methodology).lower()
    assert "fund" in text or "etf" in text
    assert "futures" not in text, "manifest still describes the futures screener"


def test_manifest_asset_classes_match_served_function() -> None:
    entry = _fsrc()
    assert AssetClass.ETF in entry.asset_classes
    assert AssetClass.FUTURE not in entry.asset_classes
    assert AssetClass.COMMODITY not in entry.asset_classes


def test_manifest_inputs_are_the_served_fund_parameters() -> None:
    names = {spec.name for spec in _fsrc().inputs}
    # The served handler reads query / universe / limit / live / reference.
    assert {"query", "limit", "live"} <= names
    assert "contract_month" not in names and "min_open_interest" not in names
