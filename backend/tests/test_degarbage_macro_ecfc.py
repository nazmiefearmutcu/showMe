"""De-garbage test for ECFC (Economic Forecasts).

ECFC must return REAL IMF World Economic Outlook forecasts pulled from the
keyless IMF DataMapper API — not the old hardcoded
"provider_unavailable / empty rows" stub and not identical per-country
constants. The live-network assertion degrades gracefully offline: if the
fetch raises a network error we assert the honest provider_unavailable
shape instead.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from showme.engine.functions.macro.ecfc import ECFCFunction


def _make_handler(http_client=None) -> ECFCFunction:
    fn = ECFCFunction()
    # _http_client is the test-injection seam honoured by ECFCFunction._client().
    if http_client is not None:
        fn._http_client = http_client
    return fn


# ---------------------------------------------------------------------------
# Offline-deterministic tests via a fake httpx-style client
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """Returns a distinct IMF-DataMapper-shaped series per indicator."""

    def __init__(self):
        self.calls: list[str] = []

    async def get(self, url):
        self.calls.append(url)
        # url ends with /{indicator}/{country}
        parts = url.rstrip("/").split("/")
        indicator, country = parts[-2], parts[-1]
        # distinct, non-constant per-indicator forward series
        base = {"NGDP_RPCH": 1.8, "PCPIPCH": 2.6, "LUR": 4.1,
                "GGXCNL_NGDP": -5.2, "GGXWDG_NGDP": 121.0}.get(indicator, 3.3)
        series = {str(2024 + i): round(base + i * 0.37, 3) for i in range(8)}
        return _FakeResp({"values": {indicator: {country: series}}})


def test_ecfc_returns_real_imf_rows_offline_fake():
    handler = _make_handler(http_client=_FakeClient())
    result = asyncio.run(handler.execute(country="USA", years=5))
    data = result.data

    assert data["status"] == "ok"
    assert data["source_mode"] == "imf_weo"
    assert "imf" in result.sources
    assert data["methodology"]
    assert isinstance(data["field_dictionary"], dict) and data["field_dictionary"]

    rows = data["rows"]
    assert rows, "expected real forecast rows"
    # Real, non-constant values: not the old empty stub, not identical constants.
    vals = [r["forecast_value"] for r in rows]
    assert len(set(vals)) > 1, "rows must carry varied real values, not one constant"
    # The old garbage stub returned the SAME 2.0 / 2.8 / 4.1 for every country.
    gdp_vals = [r["forecast_value"] for r in rows if r["indicator"] == "NGDP_RPCH"]
    assert gdp_vals and gdp_vals != [2.0] * len(gdp_vals)

    for r in rows:
        assert {"country", "indicator", "metric", "year",
                "forecast_value", "unit", "source_mode"}.issubset(r)
        assert r["source_mode"] == "imf_weo"
        assert isinstance(r["year"], int)
        assert isinstance(r["forecast_value"], float)


def test_ecfc_years_cap_per_indicator():
    handler = _make_handler(http_client=_FakeClient())
    result = asyncio.run(handler.execute(country="USA", years=3,
                                         indicators=["NGDP_RPCH", "PCPIPCH"]))
    rows = result.data["rows"]
    for ind in ("NGDP_RPCH", "PCPIPCH"):
        n = sum(1 for r in rows if r["indicator"] == ind)
        assert 1 <= n <= 3, f"{ind} should yield <= 3 forecast years, got {n}"
    # cards: one per metric (unique labels)
    labels = [c["label"] for c in result.data["cards"]]
    assert len(labels) == len(set(labels))


def test_ecfc_provider_unavailable_on_network_error():
    class _BoomClient:
        async def get(self, url):
            raise httpx.ConnectError("boom")

    handler = _make_handler(http_client=_BoomClient())
    result = asyncio.run(handler.execute(country="USA"))
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert data["rows"] == []
    assert data["methodology"]
    assert result.warnings


# ---------------------------------------------------------------------------
# Live network test — skips/degrades cleanly when offline
# ---------------------------------------------------------------------------

def test_ecfc_live_imf_datamapper():
    handler = _make_handler()  # uses shared keyless client -> real IMF endpoint
    try:
        result = asyncio.run(handler.execute(country="USA", years=4,
                                             indicators=["NGDP_RPCH", "PCPIPCH"]))
    except Exception as exc:  # pragma: no cover - network dependent
        pytest.skip(f"network unavailable: {exc}")

    data = result.data
    if data["status"] != "ok":
        # Honest provider_unavailable shape on a real outage.
        assert data["status"] == "provider_unavailable"
        assert data["rows"] == []
        assert data["methodology"]
        return

    rows = data["rows"]
    assert rows, "live IMF DataMapper should return forecast rows"
    assert "imf" in result.sources
    assert data["source_mode"] == "imf_weo"
    # Real forecast values are floats and not the old fabricated constants.
    for r in rows:
        assert isinstance(r["forecast_value"], float)
        assert r["indicator"] in ("NGDP_RPCH", "PCPIPCH")
    assert len({r["forecast_value"] for r in rows}) > 1
