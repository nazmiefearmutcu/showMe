"""FRH#2: a requested universe larger than the 25-symbol default list must never
silently shrink. When the Binance volume ranking is unavailable the handler
returns the default list, so the shortfall is reported as a warning and the
seed's limit description must not claim a ranking that did not run.
No network: the HTTP client is a URL-routed fake."""
from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.functions.screen import frh as frh_mod
from showme.manifest.seeds.frh_seed import frh


class _Resp:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> Any:
        return self._body


class _Client:
    def __init__(self, ticker: list | None) -> None:
        self.ticker = ticker

    async def get(self, url: str, params: dict[str, Any] | None = None) -> _Resp:
        if "ticker/24hr" in url:
            return _Resp(200, self.ticker) if self.ticker is not None else _Resp(503, {})
        if "premiumIndex" in url:
            return _Resp(200, {"lastFundingRate": "0.0001"})
        if "bybit" in url:
            return _Resp(200, {"result": {"list": [{"fundingRate": "0.00005"}]}})
        if "okx" in url:
            return _Resp(200, {"data": [{"settFundingRate": "0.0001"}]})
        return _Resp(404, {})


def _run(client: _Client, **params: Any):
    fn = frh_mod.FRHFunction()
    fn._http_client = client
    return asyncio.run(fn.execute(**params))


def test_ranking_unavailable_for_large_universe_warns_about_shortfall(monkeypatch):
    monkeypatch.setattr(frh_mod, "_ranking_cache", None)
    result = _run(_Client(ticker=None), limit=50)
    assert result.data["universe_basis"] == "default_list"
    assert len(result.data["rows"]) == len(frh_mod._DEFAULT_SYMBOLS) < 50
    joined = " | ".join(result.warnings).lower()
    assert "requested 50" in joined, result.warnings
    assert "ranking" in joined and "unavailable" in joined, result.warnings
    assert result.data.get("universe_requested") == 50
    assert result.data.get("universe_returned") == len(frh_mod._DEFAULT_SYMBOLS)


def test_successful_ranking_has_no_shortfall_warning(monkeypatch):
    monkeypatch.setattr(frh_mod, "_ranking_cache", None)
    ticker = [{"symbol": f"COIN{i:03d}USDT", "quoteVolume": str(1_000_000 - i)} for i in range(80)]
    result = _run(_Client(ticker=ticker), limit=50)
    assert result.data["universe_basis"] == "binance_24h_quote_volume"
    assert len(result.data["rows"]) == 50
    assert not any("requested" in w.lower() for w in result.warnings), result.warnings


def test_default_size_request_has_no_shortfall_warning(monkeypatch):
    monkeypatch.setattr(frh_mod, "_ranking_cache", None)
    result = _run(_Client(ticker=None), limit=10)
    assert result.data["universe_basis"] == "default_list"
    assert len(result.data["rows"]) == 10
    assert not any("requested" in w.lower() for w in result.warnings), result.warnings


def test_seed_limit_description_does_not_promise_ranking_unconditionally():
    limit_spec = next(spec for spec in frh.inputs if spec.name == "limit")
    text = limit_spec.description.lower()
    assert "above 25" not in text or "unavailable" in text, text
    assert "fall" in text or "unavailable" in text, text
