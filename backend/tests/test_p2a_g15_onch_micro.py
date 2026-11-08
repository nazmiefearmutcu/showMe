"""P2a-g15 regression tests for ONCH (On-Chain Metrics) and MICRO (Market Microstructure).

All network access is replaced by in-test fakes so the suite runs offline.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.instrument import AssetClass, Instrument

# --------------------------------------------------------------------------
# Shared fakes
# --------------------------------------------------------------------------


class _Resp:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _depth_payload(levels: int = 20) -> dict[str, Any]:
    bids = [[f"{100.0 - i * 0.5:.2f}", f"{1.0 + i * 0.1:.4f}"] for i in range(levels)]
    asks = [[f"{100.5 + i * 0.5:.2f}", f"{1.5 + i * 0.1:.4f}"] for i in range(levels)]
    return {"lastUpdateId": 1, "bids": bids, "asks": asks}


def _kline_rows(n: int = 200) -> list[list[Any]]:
    """Binance kline rows: [openTime, o, h, l, close, volume, closeTime, quoteVol,
    trades, takerBuyBase, takerBuyQuote, ignore]."""
    rows: list[list[Any]] = []
    price = 100.0
    for i in range(n):
        drift = 0.001 if i % 3 else -0.002
        price = price * (1.0 + drift)
        vol = 1.0 + (i % 7) * 0.3
        taker_buy = vol * (0.6 if i % 2 else 0.4)
        rows.append(
            [i, f"{price:.4f}", f"{price:.4f}", f"{price:.4f}", f"{price:.4f}",
             f"{vol:.5f}", i, "0", 10, f"{taker_buy:.5f}", "0", "0"]
        )
    return rows


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient; routes by URL and records send times."""

    depth_delay = 0.0
    sent_at: list[datetime] = []
    received_at: list[datetime] = []
    depth_levels = 20
    klines: list[list[Any]] | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, url: str, params: dict[str, Any] | None = None, **_: Any) -> _Resp:
        now = datetime.now(timezone.utc)
        if "depth" in url:
            self.__class__.sent_at.append(now)
            if self.__class__.depth_delay:
                await asyncio.sleep(self.__class__.depth_delay)
            self.__class__.received_at.append(datetime.now(timezone.utc))
            return _Resp(_depth_payload(self.__class__.depth_levels))
        rows = self.__class__.klines if self.__class__.klines is not None else _kline_rows()
        return _Resp(rows)


def _reset_fake(depth_delay: float = 0.0) -> None:
    _FakeAsyncClient.depth_delay = depth_delay
    _FakeAsyncClient.sent_at = []
    _FakeAsyncClient.received_at = []
    _FakeAsyncClient.depth_levels = 20
    _FakeAsyncClient.klines = None


def _patch_micro_http(monkeypatch: Any) -> None:
    from showme.engine.functions.screen import micro as micro_mod

    monkeypatch.setattr(micro_mod.httpx, "AsyncClient", _FakeAsyncClient)


def _btc() -> Instrument:
    return Instrument(symbol="BTCUSDT", asset_class=AssetClass.CRYPTO)


# --------------------------------------------------------------------------
# MICRO#2 — as_of must be the request/snapshot time, not the response time
# --------------------------------------------------------------------------


def test_micro_as_of_is_request_time_not_response_time(monkeypatch: Any) -> None:
    from showme.engine.functions.screen.micro import MICROFunction

    _patch_micro_http(monkeypatch)
    _reset_fake(depth_delay=0.3)

    result = asyncio.run(MICROFunction(deps=None).execute(instrument=_btc(), depth_levels=20))
    data = result.data
    assert data["status"] == "ok"

    as_of = datetime.fromisoformat(data["as_of"])
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    sent = _FakeAsyncClient.sent_at[0]
    received = _FakeAsyncClient.received_at[0]

    # The response arrived ~0.3 s after the request was sent; as_of must be
    # the send time (snapshot is taken no earlier than the request), not the
    # moment the handler finished parsing the response.
    assert (received - sent).total_seconds() >= 0.25
    assert abs((as_of - sent).total_seconds()) < 0.05, (
        f"as_of {as_of.isoformat()} should match request send {sent.isoformat()}, "
        f"not response parse time"
    )
    assert "request" in data["field_dictionary"]["as_of"].lower()
