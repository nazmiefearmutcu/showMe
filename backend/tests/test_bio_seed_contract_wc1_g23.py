"""BIO#2 (wc1-g23): the BIO seed contract must describe what the endpoint returns.

The seed promised capabilities() and verify() results (allowed, via,
biometry_kind, passcode_available, ...) that the sidecar endpoint never
produces: the sidecar cannot probe or prompt LocalAuthentication, and the BIO
pane calls the Tauri bridge directly. The contract is now limited to keys the
endpoint really returns, and the semantic tests describe the endpoint.
"""
from __future__ import annotations

import asyncio
import sys

import pytest

from showme.engine.functions.misc._extras import BIOFunction
from showme.manifest.seeds.bio_seed import bio


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_endpoint_payload_has_every_manifest_must_have_key(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    result = asyncio.run(BIOFunction().execute())
    # RED before fix: must_have promised allowed/via, which the endpoint never returns.
    missing = [k for k in bio.output_contract.must_have if k not in result.data]
    assert missing == []


def test_manifest_does_not_promise_sidecar_capabilities_or_verify_keys() -> None:
    promised = {"allowed", "via", "biometry_kind", "biometry_available", "passcode_available"}
    field_keys = set(bio.field_dict)
    # RED before fix: field_dict advertised the bridge-only keys.
    assert not (promised & field_keys), sorted(promised & field_keys)
    card_keys = {slot.key for slot in (bio.card_schema.slots if bio.card_schema else [])}
    assert not (promised & card_keys), sorted(promised & card_keys)


def test_manifest_semantic_tests_do_not_claim_sidecar_capabilities_call() -> None:
    for test in bio.semantic_tests:
        text = f"{test.description} {' '.join(test.assertions)}"
        assert "result_has_biometry_kind" not in text, test.name
        assert "result_has_biometry_available_bool" not in text, test.name
