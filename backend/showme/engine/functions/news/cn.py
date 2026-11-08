"""CN — Company News (sourced stories for one symbol from Awareness).

News only: no price, market or exchange rows are ever returned. Symbols are
normalised to the awareness entity id (BTCUSDT and BTC-USD become BTC, BRK.B
becomes BRK-B, BIST suffix ``.IS`` is kept).
"""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.awareness import AwarenessClient, AwarenessUnavailable
from showme.engine.functions.news.awareness_news import (
    bounded_int,
    client_for,
    fetch_news,
    filters_echo,
    input_required_result,
    ok_result,
    story_detail,
    text_param,
    unavailable_result,
)

# Quote currencies and crypto quote assets stripped from pair symbols.
_QUOTES = ("USDT", "USDC", "FDUSD", "BUSD", "USD", "EUR", "TRY", "BTC", "ETH")


def normalise_symbol(raw: Any) -> str:
    """Awareness entity symbol for a user-entered or routed symbol."""
    text = str(raw or "").strip().upper().replace("/", "-")
    if not text or text.endswith(".IS"):
        return text
    if "-" in text:
        base, quote = text.rsplit("-", 1)
        if base and quote in _QUOTES:
            return base
        return text
    if "." in text:
        return text.replace(".", "-")
    for quote in _QUOTES:
        if text.endswith(quote) and len(text) - len(quote) >= 2:
            return text[: -len(quote)]
    return text


@FunctionRegistry.register
class CNFunction(BaseFunction):
    code = "CN"
    name = "Company News"
    asset_classes = (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.ETF)
    category = "news"
    description = (
        "Sourced headlines for one company, ETF or crypto asset from the Awareness news service, "
        "one row per story at quality standard or better, with publisher tier and sentiment."
    )

    _awareness: AwarenessClient | None = None  # test seam; None uses the process client

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        client = client_for(self._awareness)
        story_id = text_param(params.get("story_id"))
        symbol = normalise_symbol(params.get("symbol") or (instrument.symbol if instrument else ""))
        if not symbol and not story_id:
            return input_required_result(
                self.code,
                instrument,
                "CN needs a symbol such as AAPL, BRK.B, THYAO.IS or BTC.",
                "Pick a symbol and retry.",
            )
        try:
            if story_id:
                story, responses = await story_detail(client, story_id)
                data: dict[str, Any] = {
                    "status": "ok" if story else "empty",
                    "symbol": symbol,
                    "story": story,
                    "rows": [],
                    "count": 0,
                    "next_cursor": None,
                    "filters": {"story_id": story_id},
                    "hidden_note": None if story else "story not found in the Awareness service",
                }
                return ok_result(self.code, instrument, data, responses)

            hours = bounded_int(params.get("hours"), 168, 1, 720)
            limit = bounded_int(params.get("limit"), 50, 1, 200)
            response, rows = await fetch_news(
                client,
                {"symbols": [symbol], "hours": hours, "limit": limit, "min_quality": "standard"},
            )
        except AwarenessUnavailable as exc:
            return unavailable_result(self.code, instrument, exc.reason)

        data = {
            "status": "ok" if rows else "empty",
            "symbol": symbol,
            "rows": rows,
            "count": len(rows),
            "next_cursor": response.meta.get("next_cursor"),
            "filters": filters_echo(symbol=symbol, hours=hours, limit=limit),
            "hidden_note": None,
        }
        if not rows:
            data["next_actions"] = ["Widen the hours window or check the symbol spelling."]
        return ok_result(self.code, instrument, data, [response])
