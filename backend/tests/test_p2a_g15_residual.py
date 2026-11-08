"""P2a-g15 residual regression tests (ONCH seed card_schema contract).

Offline: the keyless provider client is an in-test fake, so no network is used.
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.manifest.seeds.onch_seed import onch


class _Resp:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _OnchFakeClient:
    async def get(self, url: str, headers: Any = None, timeout: Any = None, **_: Any) -> _Resp:
        if url.endswith("/v1/fees/recommended"):
            return _Resp({"fastestFee": 3, "halfHourFee": 2, "hourFee": 2,
                          "economyFee": 1, "minimumFee": 1})
        if url.endswith("/v1/fees/mempool-blocks"):
            return _Resp([{"nTx": 1000, "blockVSize": 990000.0}])
        if url.endswith("/v1/difficulty-adjustment"):
            return _Resp({"difficultyChange": 1.5, "progressPercent": 40.0, "remainingBlocks": 1200})
        if url.endswith("/v1/mining/hashrate/3d"):
            return _Resp({"currentHashrate": 9.5e20, "currentDifficulty": 1.2e14})
        if url.endswith("/blocks/tip/height"):
            return _Resp(900_000)
        if url.endswith("/api/mempool"):
            return _Resp({"count": 59_204})
        return _Resp({}, status_code=404)


def _run_onch_live(monkeypatch: Any) -> Any:
    import showme.providers._http as http_mod
    from showme.engine.functions.misc.onch import ONCHFunction

    client = _OnchFakeClient()

    async def _get_client() -> _OnchFakeClient:
        return client

    monkeypatch.setattr(http_mod, "get_client", _get_client)
    return asyncio.run(ONCHFunction().execute())


def test_onch_emitted_cards_match_seed_card_schema(monkeypatch: Any) -> None:
    """The seed's card_schema must describe exactly the cards the handler emits.

    The handler emits {key,label,value} cards; every seed slot key must be a
    card the handler really produces, and vice versa (no declared-but-absent
    slots such as data_mode or as_of).
    """
    result = _run_onch_live(monkeypatch)
    assert result.data["status"] == "ok"

    cards = result.data["cards"]
    assert all(isinstance(c.get("key"), str) and c["key"] for c in cards)
    assert [c["key"] for c in cards] == [s.key for s in onch.card_schema.slots]
    assert {c["key"]: c["label"] for c in cards} == {
        s.key: s.label for s in onch.card_schema.slots
    }
