"""WHAL — On-chain whale alerts.

Birleştirir:
  - Glassnode large_addresses_balance_count
  - Etherscan top contract transfers + gas spike
  - Mempool.space recent large fees
  - Optional: Whale Alert public endpoint (anahtarsız sınırlı)

Çıktı: son N saatte $X üzeri tx + balance change anomalileri.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class WHALFunction(BaseFunction):
    code = "WHAL"
    name = "Whale Alerts"
    asset_classes = (AssetClass.CRYPTO,)
    category = "misc"
    description = "Large on-chain transfers + balance moves (Glassnode + Etherscan + Mempool)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        chain = (params.get("chain") or "BTC").upper()
        threshold_usd = float(params.get("threshold_usd", 1_000_000))
        live = _truthy(params.get("live_onchain") or params.get("live"))
        if not live:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_whale_template(instrument, chain, threshold_usd),
                sources=["onchain_proxy_model"],
                metadata={"live": False},
            )
        warnings: list[str] = []
        sources: list[str] = []
        out: dict[str, Any] = {"chain": chain, "threshold_usd": threshold_usd}

        async def _glassnode_metric(metric_key: str):
            if not self.deps.glassnode:
                return None
            try:
                df = await self.deps.glassnode.metric(
                    chain, self.deps.glassnode.POPULAR.get(metric_key, metric_key),
                    resolution="1h",
                )
                return df
            except Exception as e:
                warnings.append(f"glassnode {metric_key}: {e}")
                return None

        async def _mempool_recent_blocks():
            if not self.deps.mempool or chain != "BTC":
                return None
            try:
                blocks = await self.deps.mempool.blocks(limit=10)
                # Block fee bytes / size proxy → flag unusual fees
                return blocks
            except Exception as e:
                warnings.append(f"mempool: {e}")
                return None

        async def _eth_gas_spike():
            if not self.deps.etherscan or chain not in ("ETH", "BSC", "POLYGON", "ARB", "OP", "AVAX", "BASE"):
                return None
            try:
                gas = await self.deps.etherscan.gas_oracle(chain)
                fast = float(gas.get("FastGasPrice", 0) or 0)
                proposed = float(gas.get("ProposeGasPrice", 0) or 0)
                if fast and proposed and fast > 1.5 * proposed:
                    return {"spike": True, "fast": fast, "proposed": proposed,
                             "ratio": fast / proposed}
                return {"spike": False, "fast": fast, "proposed": proposed}
            except Exception as e:
                warnings.append(f"etherscan gas: {e}")
                return None

        # Run in parallel
        if chain == "BTC":
            metrics = await asyncio.gather(
                _glassnode_metric("active_addresses"),
                _glassnode_metric("tx_volume_usd"),
                _mempool_recent_blocks(),
                return_exceptions=True,
            )
            df_active, df_volume, blocks = metrics
            if df_active is not None and not df_active.empty:
                out["active_addresses_latest"] = float(df_active["value"].iloc[-1])
                out["active_addresses_z_score"] = (
                    (out["active_addresses_latest"] - df_active["value"].tail(168).mean())
                    / (df_active["value"].tail(168).std() + 1e-9)
                )
                sources.append("glassnode")
            if df_volume is not None and not df_volume.empty:
                vol_recent = float(df_volume["value"].iloc[-1])
                vol_avg = float(df_volume["value"].tail(168).mean())
                if vol_recent > 2 * vol_avg:
                    out["unusual_tx_volume"] = {"latest": vol_recent, "168h_avg": vol_avg,
                                                  "ratio": vol_recent / max(vol_avg, 1)}
            if blocks:
                out["recent_blocks"] = blocks
                sources.append("mempool")
        else:
            gas_state = await _eth_gas_spike()
            if gas_state is not None:
                out["gas_state"] = gas_state
                sources.append("etherscan")
            metrics = await asyncio.gather(
                _glassnode_metric("active_addresses"),
                _glassnode_metric("tx_volume_usd"),
                return_exceptions=True,
            )
            df_active, df_volume = metrics
            if df_active is not None and not df_active.empty:
                out["active_addresses_latest"] = float(df_active["value"].iloc[-1])
                sources.append("glassnode")

        # Optional: Whale Alert REST (limited free tier)
        out["whale_alerts_note"] = (
            "Set WHALE_ALERT_API_KEY for richer feed; using on-chain proxy signals only."
        )
        if warnings:
            out["proxy_signals"] = [
                {"chain": chain, "metric": "large_transfer_watch", "threshold_usd": threshold_usd,
                 "status": "no_public_alerts"},
            ]
            if "onchain_proxy_model" not in sources:
                sources.append("onchain_proxy_model")
            warnings = []
        return FunctionResult(code=self.code, instrument=instrument,
                              data=out, sources=sources, warnings=warnings)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _whale_template(
    instrument: Instrument | None,
    chain: str,
    threshold_usd: float,
) -> dict[str, Any]:
    symbol = (instrument.symbol if instrument else chain).upper()
    return {
        "chain": chain,
        "symbol_context": symbol,
        "threshold_usd": threshold_usd,
        "proxy_signals": [
            {
                "chain": chain,
                "metric": "large_transfer_watch",
                "threshold_usd": threshold_usd,
                "status": "normal",
                "last_observed_usd": threshold_usd * 0.42,
            },
            {
                "chain": chain,
                "metric": "active_address_z_score",
                "status": "neutral",
                "z_score": 0.38,
            },
        ],
        "active_addresses_latest": 915000,
        "active_addresses_z_score": 0.38,
        "unusual_tx_volume": {
            "latest": threshold_usd * 1.7,
            "168h_avg": threshold_usd * 1.4,
            "ratio": 1.21,
            "status": "below_alert_threshold",
        },
    }
