"""De-garbage regression: SOSC reads Awareness entity sentiment (no GDELT scrape, no
hardcoded baseline rows). Offline: the awareness client is injected with a mock transport."""
from __future__ import annotations

import asyncio

import httpx

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.awareness import AwarenessClient
from showme.engine.functions.news.sosc import SOSCFunction


def _run(coro):
    return asyncio.run(coro)


def _instrument(sym="AAPL"):
    return Instrument(symbol=sym, asset_class=AssetClass.EQUITY)


def _offline_client() -> AwarenessClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    return AwarenessClient("http://aw.test", transport=httpx.MockTransport(handler), autostart=False)


def test_sosc_offline_is_honest_provider_unavailable():
    fn = SOSCFunction()
    fn._awareness = _offline_client()
    res = _run(fn.execute(instrument=_instrument("AAPL")))
    assert res.data["status"] == "provider_unavailable"
    assert res.sources == ["no_live_source"]
    assert res.data["rows"] == []
    assert "methodology" in res.data


def test_sosc_no_hardcoded_baseline_rows():
    """The old stub returned exactly X/Twitter+Reddit+StockTwits zero rows."""
    fn = SOSCFunction()
    fn._awareness = _offline_client()
    res = _run(fn.execute(instrument=_instrument("MSFT")))
    rows = (res.data or {}).get("rows") or []
    platforms = {str(r.get("platform")) for r in rows}
    assert platforms != {"X/Twitter", "Reddit", "StockTwits"}
    assert rows == []
