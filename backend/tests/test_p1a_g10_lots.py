"""P1a-g10 LOTS regression (LOTS#5): the manifest must describe the handler.

The handler reads the LOCAL tax-lot ledger (runtime tax_lots.sqlite). The
seed previously claimed broker-sourced lots (credential_id, broker.lots(),
market value, unrealized, term) that the handler never provides. The
manifest must now declare only what the handler does and emit the fields
it promises.
"""

from __future__ import annotations

import asyncio
import pytest

from showme.engine.functions.portfolio import lots as lots_mod
from showme.engine.services import tax_lots
from showme.manifest import REGISTRY, load_seeds

_HANDLER_PARAMS = {
    "action", "symbol", "account", "quantity", "price", "method", "year",
    "acquired_at", "long_term_threshold_days",
}


@pytest.fixture(scope="module", autouse=True)
def _seeds() -> None:
    load_seeds()


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "tax_lots.sqlite"
    monkeypatch.setattr(tax_lots, "_db_file", lambda: path)
    return path


def _run(**params):
    return asyncio.run(lots_mod.LOTSFunction().execute(instrument=None, **params))


def test_manifest_does_not_claim_broker_sourcing() -> None:
    entry = REGISTRY.get("LOTS")
    assert entry.provider_chain.primary == "internal"
    assert entry.provider_chain.fallbacks == []
    # Explicit "not a broker feed" disclaimers are honest; claims of broker
    # lots or credential-scoped broker pulls are not.
    text = (entry.intent + " " + entry.methodology).lower()
    assert "broker.lots" not in text
    assert "ccxt" not in text
    assert "credential" not in text
    assert "sourced directly from the broker" not in text


def test_manifest_inputs_match_handler_parameters() -> None:
    entry = REGISTRY.get("LOTS")
    names = {spec.name for spec in entry.inputs}
    assert "credential_id" not in names
    assert names <= _HANDLER_PARAMS, f"inputs the handler ignores: {names - _HANDLER_PARAMS}"


def test_manifest_promised_fields_are_emitted_by_handler(ledger) -> None:
    entry = REGISTRY.get("LOTS")
    must_have = set(entry.output_contract.must_have)
    assert "data_mode" not in must_have and "totals" not in must_have and "as_of" not in must_have

    empty = _run(action="list").data
    assert empty["status"] == "empty"
    assert must_have <= set(empty), must_have - set(empty)

    tax_lots.open_lot(symbol="AAPL", quantity=15, price=190.0)
    populated = _run(action="list")
    assert populated.sources == ["local_tax_lot_ledger"]
    assert must_have <= set(populated.data), must_have - set(populated.data)
    assert populated.data["lots"][0]["symbol"] == "AAPL"
    assert populated.data["lots"][0]["remaining"] == 15.0
