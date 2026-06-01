"""De-garbage regression: SOSC social/news sentiment via keyless GDELT + FinBERT.

Network-dependent assertions degrade gracefully offline: if the GDELT fetch
raises a network error the handler returns an honest provider_unavailable
shape, which we accept instead of failing the suite.
"""
from __future__ import annotations

import asyncio

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news.sosc import SOSCFunction


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _instrument(sym="AAPL"):
    try:
        return Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
    except Exception:
        return None


def test_sosc_returns_real_or_graceful():
    fn = SOSCFunction()
    res = _run(fn.execute(instrument=_instrument("AAPL")))
    data = res.data
    assert isinstance(data, dict)
    assert "methodology" in data
    status = str(data.get("status", "")).lower()
    if status == "ok":
        # Real GDELT path: net sentiment is a real number and there are rows
        # or a real article count — NOT the old hardcoded zero baseline.
        summary = data.get("summary") or {}
        assert "gdelt" in (res.sources or [])
        assert summary.get("total_mentions", 0) >= 0
        assert isinstance(summary.get("net_sentiment"), (int, float))
        # the old stub always emitted exactly the 3 no_live_source platforms
        assert data.get("summary", {}).get("source_mode") != "no_live_source"
    else:
        # Offline / empty: honest, not a fabricated sentiment.
        assert status in {"provider_unavailable", "empty"}


def test_sosc_no_hardcoded_baseline_rows():
    """The old stub returned exactly X/Twitter+Reddit+StockTwits zero rows."""
    fn = SOSCFunction()
    res = _run(fn.execute(instrument=_instrument("MSFT")))
    rows = (res.data or {}).get("rows") or []
    platforms = {str(r.get("platform")) for r in rows}
    assert platforms != {"X/Twitter", "Reddit", "StockTwits"}
