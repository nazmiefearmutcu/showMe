"""AV never shows the global podcast archive as a symbol's archive (AV#4).

When a symbol has no SEC EDGAR filer (BTC-USD and similar), the handler used
to return the global podcast episodes under that symbol. The pane then titled
them as the symbol's archive. A podcast episode is not the instrument's data,
so the symbol scope must return an honest empty state instead. The global
podcast archive stays reachable through the global scope. Network is patched.
"""
from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news.av import AVFunction

BTC = Instrument(symbol="BTCUSD", asset_class=AssetClass.EQUITY)


def test_unmapped_symbol_never_substitutes_podcast_rows(monkeypatch):
    fn = AVFunction()
    podcast_calls: list[tuple] = []

    async def _no_cik(symbol, params):
        return None

    async def _podcast_spy(self_, query, limit, params, **kwargs):
        podcast_calls.append((query, kwargs))
        return FunctionResult(
            code="AV",
            instrument=None,
            data={"status": "ok", "rows": [{"title": "Planet Money episode"}], "items": []},
            sources=["podcast_rss"],
        )

    monkeypatch.setattr(fn, "_resolve_cik", _no_cik)
    monkeypatch.setattr(fn, "_podcast_archive", lambda *a, **k: _podcast_spy(fn, *a, **k))

    result = asyncio.run(fn.execute(instrument=BTC))

    assert podcast_calls == [], "podcast archive must not stand in for a symbol"
    payload = result.data
    assert payload["rows"] == []
    assert payload["status"] == "empty"
    assert payload["symbol"] == "BTCUSD"
    assert "BTCUSD" in payload["reason"]
    assert "global" in " ".join(payload["next_actions"]).lower()
    assert result.sources == ["sec_edgar"]
