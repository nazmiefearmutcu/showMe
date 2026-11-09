"""FRH shortfall warning: a Binance ranking that succeeds but returns fewer
names than requested must not be reported as "ranking unavailable". Only the
fallback to the default list is a ranking failure. No network: URL-routed fake."""
from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.functions.screen import frh as frh_mod


class _Resp:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> Any:
        return self._body


class _Client:
    def __init__(self, ticker: list) -> None:
        self.ticker = ticker

    async def get(self, url: str, params: dict[str, Any] | None = None) -> _Resp:
        if "ticker/24hr" in url:
            return _Resp(200, self.ticker)
        if "premiumIndex" in url:
            return _Resp(200, {"lastFundingRate": "0.0001"})
        if "funding/history" in url:
            return _Resp(200, {"result": {"list": [{"fundingRate": "0.00005"}]}})
        if "okx" in url:
            return _Resp(200, {"data": [{"settFundingRate": "0.0001"}]})
        return _Resp(404, {})


def _run(ticker: list, limit: int):
    frh_mod._ranking_cache = None
    fn = frh_mod.FRHFunction()
    fn._http_client = _Client(ticker)
    return asyncio.run(fn.execute(limit=limit))


def test_short_successful_ranking_does_not_claim_ranking_unavailable():
    ticker = [{"symbol": f"COIN{i:03d}USDT", "quoteVolume": str(1_000_000 - i)} for i in range(30)]
    result = _run(ticker, limit=50)
    assert result.data["universe_basis"] == "binance_24h_quote_volume"
    assert len(result.data["rows"]) == 30
    joined = " | ".join(result.warnings).lower()
    assert "unavailable" not in joined and "default list" not in joined, result.warnings
    assert "requested 50" in joined and "30" in joined, result.warnings
