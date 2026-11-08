"""Regression test for ECFC#3: the seed and the handler declared different default
indicator sets, so the pane's advertised defaults did not match what was fetched.

No network: the IMF DataMapper client is faked.
"""

from __future__ import annotations

import asyncio

from showme.engine.functions.macro.ecfc import _DEFAULT_INDICATORS, ECFCFunction
from showme.manifest.seeds.ecfc_seed import ecfc as ecfc_manifest


class _FakeImf:
    def __init__(self) -> None:
        self.indicators: list[str] = []

    async def get(self, url, **kwargs):  # noqa: ARG002
        indicator, country = url.rstrip("/").split("/")[-2:]
        self.indicators.append(indicator)
        series = {str(2026 + i): round(1.0 + i * 0.1, 3) for i in range(6)}
        return _Resp({"values": {indicator: {country: series}}})


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_seed_default_indicators_match_the_handler_default() -> None:
    assert list(ecfc_manifest.defaults["indicators"]) == list(_DEFAULT_INDICATORS)


def test_seed_indicator_options_cover_the_handler_default() -> None:
    option_codes = {str(o) for o in next(i for i in ecfc_manifest.inputs if i.name == "indicators").options}
    assert set(_DEFAULT_INDICATORS) <= option_codes


def test_default_request_fetches_exactly_the_advertised_indicators() -> None:
    fake = _FakeImf()
    fn = ECFCFunction()
    fn._http_client = fake
    result = asyncio.run(fn.execute(country="USA"))
    assert result.metadata["indicators"] == list(ecfc_manifest.defaults["indicators"])
    assert sorted(fake.indicators) == sorted(ecfc_manifest.defaults["indicators"])
