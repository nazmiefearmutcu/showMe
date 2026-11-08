"""Regression tests for ECFC#2: the seed described a different implementation
(FRED release dates, a modeled fallback, a pinned vintage) and declared inputs
the handler never read. The seed must describe the IMF DataMapper path, declare
only inputs that take effect, and the payload must say what the vintage and as_of
fields do and do not identify.

No network: the IMF DataMapper client is faked.
"""

from __future__ import annotations

import asyncio

from showme.manifest.enums import DataMode
from showme.engine.functions.macro.ecfc import ECFCFunction
from showme.manifest.seeds.ecfc_seed import ecfc as ecfc_manifest


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _FakeImf:
    async def get(self, url, **kwargs):  # noqa: ARG002
        indicator, country = url.rstrip("/").split("/")[-2:]
        series = {str(2026 + i): round(2.0 + i * 0.2, 3) for i in range(6)}
        return _Resp({"values": {indicator: {country: series}}})


def test_seed_declares_only_inputs_the_handler_reads() -> None:
    declared = {i.name for i in ecfc_manifest.inputs}
    # The handler reads country, indicators and years. A declared input it never
    # reads (vintage, provider_mode) would be a control that does nothing.
    assert declared == {"country", "indicators", "years"}


def test_seed_methodology_describes_the_imf_datamapper_path() -> None:
    text = ecfc_manifest.methodology
    assert "DataMapper" in text
    assert "FRED" not in text
    assert "modeled fallback" not in text.lower()
    assert "source_mode=.modeled" not in text


def test_seed_provider_chain_is_the_imf_path() -> None:
    chain = ecfc_manifest.provider_chain
    assert chain.primary == "imf"
    assert "fred" not in chain.primary and not any("fred" in f for f in chain.fallbacks)
    assert set(chain.acceptable_modes) <= {DataMode.LIVE_OFFICIAL, DataMode.PROVIDER_UNAVAILABLE}


def test_seed_field_dictionary_does_not_claim_fred_or_modeled_rows() -> None:
    assert "fred" not in ecfc_manifest.field_dict["vintage"].description.lower()
    described = ecfc_manifest.field_dict["rows[].source_mode"].description
    assert "imf_oecd" not in described and "cached_snapshot" not in described
    assert "modeled" not in described.replace("no modeled rows", "")
    assert "as_of" in ecfc_manifest.field_dict


def test_payload_states_what_vintage_and_as_of_identify() -> None:
    fn = ECFCFunction()
    fn._http_client = _FakeImf()
    data = asyncio.run(fn.execute(country="USA", years=3, indicators=["NGDP_RPCH"])).data
    assert data["status"] == "ok"
    # The DataMapper exposes no WEO edition or release date; the payload must say so
    # rather than imply a pinned batch.
    assert "vintage_basis" in data and "edition" in data["vintage_basis"]
    assert "as_of_basis" in data and "retrieved" in data["as_of_basis"]
