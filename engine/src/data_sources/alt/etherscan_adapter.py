"""Etherscan on-chain adapter (and L2 multi-chain via Etherscan-family APIs).

DATA PIPELINE:
    Free API key: 5 req/s, 100k req/day.
    Endpoints used: account/balance, account/txlist, gastracker/gasoracle,
    proxy/eth_getBlockByNumber, contract/getsourcecode.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from src.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)
from src.utils.throttle import throttle


class EtherscanAdapter(BaseDataSource):
    name = "etherscan"
    supported_kinds = (DataKind.OTHER,)
    rate_limit_rps = 5.0
    requires_api_key = True
    api_key_env = "ETHERSCAN_API_KEY"

    # Multi-chain support via Etherscan-family domains.
    DOMAINS = {
        "ETH":      "https://api.etherscan.io/api",
        "BSC":      "https://api.bscscan.com/api",
        "POLYGON":  "https://api.polygonscan.com/api",
        "ARB":      "https://api.arbiscan.io/api",
        "OP":       "https://api-optimistic.etherscan.io/api",
        "AVAX":     "https://api.snowtrace.io/api",
        "BASE":     "https://api.basescan.org/api",
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get(self.api_key_env, "")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15)
        return self._client

    @throttle(rps=5.0)
    async def _get(self, chain: str, **params: Any) -> dict[str, Any]:
        url = self.DOMAINS.get(chain.upper())
        if not url:
            raise DataSourceError(f"unknown chain {chain}")
        params.setdefault("apikey", self.api_key)
        client = await self._client_()
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()

    async def balance(self, address: str, chain: str = "ETH") -> float:
        data = await self._get(chain, module="account", action="balance",
                                 address=address, tag="latest")
        wei = int(data.get("result") or 0)
        return wei / 10**18

    async def gas_oracle(self, chain: str = "ETH") -> dict[str, Any]:
        return (await self._get(chain, module="gastracker", action="gasoracle")).get("result", {})

    async def txlist(self, address: str, chain: str = "ETH",
                     page: int = 1, offset: int = 25) -> list[dict[str, Any]]:
        data = await self._get(chain, module="account", action="txlist",
                                 address=address, sort="desc",
                                 page=page, offset=offset)
        return data.get("result") or []

    async def fetch(self, request: DataRequest) -> Any:
        chain = (request.extra or {}).get("chain", "ETH")
        kind = (request.extra or {}).get("op", "gas")
        if kind == "gas":
            return await self.gas_oracle(chain)
        if kind == "balance":
            addr = (request.extra or {}).get("address") or (request.symbols[0] if request.symbols else None)
            if not addr:
                raise DataSourceError("etherscan balance needs address")
            return await self.balance(addr, chain)
        if kind == "txs":
            addr = (request.extra or {}).get("address") or (request.symbols[0] if request.symbols else None)
            if not addr:
                raise DataSourceError("etherscan txs needs address")
            return await self.txlist(addr, chain)
        raise DataSourceError(f"unknown op {kind}")
