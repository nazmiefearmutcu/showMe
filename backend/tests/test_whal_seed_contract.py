"""WHAL#6 — the seed's output contract must only name fields the handler ships.

The handler (engine/functions/misc/whal.py) never emits a ``data_mode`` field;
it returns ``status``. A catalogue that requires ``data_mode`` asks the UI and
any contract check for a field that never arrives.
"""
from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.misc.whal import WHALFunction
from showme.manifest.seeds.whal_seed import whal


def test_output_contract_does_not_require_unshipped_data_mode() -> None:
    assert "data_mode" not in whal.output_contract.must_have, whal.output_contract.must_have


def test_output_contract_requires_status_the_handler_emits() -> None:
    assert "status" in whal.output_contract.must_have, whal.output_contract.must_have


def test_card_schema_has_no_unshipped_data_mode_slot() -> None:
    keys = [slot.key for slot in whal.card_schema.slots]
    assert "data_mode" not in keys, keys


def test_handler_emits_status_and_no_data_mode(monkeypatch) -> None:
    import showme.engine.functions.misc.whal as whal_mod

    async def _no_bars(*_args, **_kwargs):
        return []

    async def _no_sec(*_args, **_kwargs):
        return []

    monkeypatch.setattr(whal_mod, "_fetch_yahoo_bars", _no_bars)
    monkeypatch.setattr(whal_mod, "_fetch_sec_filing_rows", _no_sec)
    result = asyncio.run(WHALFunction(FunctionDeps()).execute(
        symbol="EURUSD", market="FX", threshold_usd=1_000_000))
    assert "status" in result.data, sorted(result.data)
    assert "data_mode" not in result.data, sorted(result.data)
