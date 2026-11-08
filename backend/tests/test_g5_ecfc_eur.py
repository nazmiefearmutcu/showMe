"""ECFC — EUR must reach the IMF DataMapper euro-area key ``EURO``.

The pane and seed offer ``EUR``. The IMF DataMapper has no ``EUR`` key (the
euro area is ``EURO``); a request for ``/EUR`` returns the all-country dataset
without the requested key, so every indicator came back "no series for EUR"
and the pane showed an empty provider_unavailable state although the data
existed under ``EURO``. The fake client below reproduces that IMF behaviour
offline (no network).
"""

from __future__ import annotations

import asyncio

from showme.engine.functions.macro.ecfc import ECFCFunction, _normalize_country


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _ImfFake:
    """Serves a series only under the ``EURO`` key, like the real DataMapper."""

    def __init__(self):
        self.urls: list[str] = []

    async def get(self, url, **kwargs):
        self.urls.append(url)
        indicator, country = url.rstrip("/").split("/")[-2:]
        series = {str(2025 + i): round(1.5 + i * 0.1, 3) for i in range(8)}
        if country == "EURO":
            return _Resp({"values": {indicator: {"EURO": series}}})
        # Unknown key: IMF answers 200 with the whole dataset, no requested key.
        return _Resp({"values": {indicator: {"SDN": series}}})


def test_eur_is_fetched_under_imf_euro_key_and_returns_rows() -> None:
    fake = _ImfFake()
    fn = ECFCFunction()
    fn._http_client = fake
    result = asyncio.run(
        fn.execute(country="EUR", years=3, indicators=["NGDP_RPCH", "PCPIPCH"])
    )
    assert fake.urls, "ECFC must query the IMF DataMapper"
    assert all(url.endswith("/EURO") for url in fake.urls), fake.urls
    assert result.data["status"] == "ok", result.data.get("reason")
    assert result.data["rows"], "EUR must return forecast rows, not an empty stub"
    assert {row["country"] for row in result.data["rows"]} == {"EURO"}


def test_eur_aliases_normalise_to_imf_euro_key() -> None:
    assert _normalize_country("EUR") == "EURO"
    assert _normalize_country("eur") == "EURO"
    assert _normalize_country("EU") == "EURO"
    assert _normalize_country("EZ") == "EURO"
    # Existing mappings are untouched.
    assert _normalize_country("US") == "USA"
    assert _normalize_country("EURO") == "EURO"
