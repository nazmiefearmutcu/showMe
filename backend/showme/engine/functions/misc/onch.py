"""ONCH — Crypto On-Chain Metrics.

Plan §5 alt-data tablosu: Glassnode + Mempool.space + Etherscan birleşik.
Bitcoin için: mempool fees + hashrate + Glassnode active_addresses + price.
ETH için: Etherscan gas + Glassnode metrics.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class ONCHFunction(BaseFunction):
    code = "ONCH"
    name = "On-Chain Metrics"
    asset_classes = (
        AssetClass.CRYPTO,
        AssetClass.EQUITY,
        AssetClass.ETF,
        AssetClass.FX,
        AssetClass.COMMODITY,
        AssetClass.INDEX,
    )
    category = "misc"
    description = "Crypto on-chain: fees, hash rate, active addresses, gas, mempool."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        asset_class = (
            instrument.asset_class.value
            if instrument is not None
            else str(params.get("asset_class") or "CRYPTO").upper()
        )
        base = (
            (instrument.metadata or {}).get("base") or instrument.symbol
            if instrument is not None
            else str(params.get("symbol") or "BTCUSDT")
        )
        chain = (params.get("chain") or
                  ("ETH" if base.upper() in ("ETH", "USDT", "USDC", "DAI", "WETH") else
                   "BTC"))
        sources: list[str] = []
        provider_errors: list[str] = []
        out: dict[str, Any] = {"chain": chain, "asset": base.upper()}
        timeout = float(params.get("timeout", 8))
        live = _truthy(params.get("live_onchain") or params.get("live"))

        if not live or asset_class != "CRYPTO":
            out.update(_onchain_unavailable(chain, base.upper(), asset_class))
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=out,
                sources=["onchain_provider"],
                metadata={"asset_class": asset_class},
            )

        if chain == "BTC" and self.deps.mempool:
            try:
                fees, mp, blocks, hashrate = await asyncio.gather(
                    asyncio.wait_for(self.deps.mempool.fees(), timeout=timeout),
                    asyncio.wait_for(self.deps.mempool.mempool_stats(), timeout=timeout),
                    asyncio.wait_for(self.deps.mempool.blocks(limit=5), timeout=timeout),
                    asyncio.wait_for(self.deps.mempool.hashrate(), timeout=timeout),
                    return_exceptions=True,
                )
                if not isinstance(fees, Exception):
                    out["mempool_fees"] = fees
                else:
                    provider_errors.append(f"mempool.fees: {fees}")
                if not isinstance(mp, Exception):
                    out["mempool_stats"] = mp
                else:
                    provider_errors.append(f"mempool.stats: {mp}")
                if not isinstance(blocks, Exception):
                    out["recent_blocks"] = blocks
                else:
                    provider_errors.append(f"mempool.blocks: {blocks}")
                if not isinstance(hashrate, Exception):
                    out["hashrate"] = hashrate
                else:
                    provider_errors.append(f"mempool.hashrate: {hashrate}")
                if any(key in out for key in ("mempool_fees", "mempool_stats", "recent_blocks")):
                    sources.append("mempool")
            except Exception as e:
                provider_errors.append(f"mempool: {e}")

        if chain == "ETH" and self.deps.etherscan:
            try:
                out["gas"] = await asyncio.wait_for(self.deps.etherscan.gas_oracle("ETH"), timeout=timeout)
                sources.append("etherscan")
            except Exception as e:
                provider_errors.append(f"etherscan: {e}")

        if self.deps.glassnode:
            try:
                metrics = (params.get("metrics") or
                           ["active_addresses", "tx_count", "price", "mvrv"])
                async def _one(m):
                    try:
                        df = await asyncio.wait_for(
                            self.deps.glassnode.metric(
                                base,
                                self.deps.glassnode.POPULAR.get(m, m),
                                resolution="24h",
                            ),
                            timeout=timeout,
                        )
                        if df.empty:
                            return m, None
                        return m, {
                            "latest": float(df["value"].iloc[-1]) if "value" in df.columns else None,
                            "samples": int(len(df)),
                        }
                    except Exception as e:
                        provider_errors.append(f"glassnode.{m}: {e}")
                        return m, None
                results = await asyncio.gather(*(_one(m) for m in metrics))
                out["glassnode"] = {k: v for k, v in results if v is not None}
                if out["glassnode"]:
                    sources.append("glassnode")
            except Exception as e:
                provider_errors.append(f"glassnode: {e}")

        if len(out) <= 2:
            out.update(_onchain_unavailable(chain, base.upper(), asset_class))

        rows, history = _shape_onchain_rows(out, chain)
        out.update({
            "rows": rows,
            "history": history,
            "cards": [
                {"label": "Chain", "value": chain},
                {"label": "Metrics", "value": len(rows)},
                {"label": "Blocks", "value": len(history)},
            ],
            "methodology": (
                "ONCH normalizes crypto-native provider payloads into metric rows. BTC uses mempool.space "
                "fees, mempool statistics, recent blocks, and mining hash-rate endpoints. Glassnode/Etherscan "
                "metrics are included only when credentials are available; missing vendors are reported as "
                "provider errors rather than replaced with fake active-address values."
            ),
            "field_dictionary": {
                "metric": "Human-readable on-chain metric.",
                "value": "Latest normalized value.",
                "unit": "Metric unit.",
                "source_mode": "Provider endpoint used for the row.",
                "date": "Observation timestamp/date when available.",
            },
        })
        return FunctionResult(code=self.code, instrument=instrument,
                              data=out, sources=sources or ["onchain_provider"],
                              metadata={"provider_errors": provider_errors} if provider_errors else {})


def _truthy(value: Any) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on", "live"}


def _onchain_unavailable(chain: str, asset: str, asset_class: str = "CRYPTO") -> dict[str, Any]:
    if asset_class != "CRYPTO":
        return {
            "status": "unsupported_asset",
            "reason": f"ONCH is crypto-native; {asset_class} does not have on-chain metrics.",
            "rows": [],
            "next_actions": ["Use BTCUSDT or ETHUSDT, or open a non-on-chain market function for this asset."],
        }
    return {
        "status": "provider_unavailable",
        "reason": f"{asset} {chain} on-chain providers returned no usable metrics.",
        "rows": [],
        "next_actions": [
            "For BTC, keep live=true and allow mempool.space access.",
            "For ETH and Glassnode metrics, configure ETHERSCAN_API_KEY or GLASSNODE_API_KEY.",
        ],
    }


def _shape_onchain_rows(out: dict[str, Any], chain: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    fees = out.get("mempool_fees") if isinstance(out.get("mempool_fees"), dict) else {}
    for key, label in (
        ("fastestFee", "Fastest fee"),
        ("halfHourFee", "Half-hour fee"),
        ("hourFee", "Hour fee"),
        ("economyFee", "Economy fee"),
    ):
        value = fees.get(key)
        if value is not None:
            rows.append({"chain": chain, "metric": label, "value": value, "unit": "sat/vB", "source_mode": "mempool_fees"})
    stats = out.get("mempool_stats") if isinstance(out.get("mempool_stats"), dict) else {}
    for key, label, unit in (
        ("count", "Mempool transactions", "tx"),
        ("vsize", "Mempool virtual size", "vbytes"),
        ("total_fee", "Mempool total fees", "sats"),
    ):
        value = stats.get(key)
        if value is not None:
            rows.append({"chain": chain, "metric": label, "value": value, "unit": unit, "source_mode": "mempool_stats"})
    hashrate = out.get("hashrate") if isinstance(out.get("hashrate"), dict) else {}
    current_hashrate = _find_numeric(hashrate, ("currentHashrate", "current_hashrate", "hashrate", "avgHashrate"))
    if current_hashrate is not None:
        rows.append({"chain": chain, "metric": "Hash rate", "value": current_hashrate, "unit": "H/s", "source_mode": "mempool_hashrate"})
    gas = out.get("gas") if isinstance(out.get("gas"), dict) else {}
    for key, label in (("SafeGasPrice", "Safe gas"), ("ProposeGasPrice", "Propose gas"), ("FastGasPrice", "Fast gas"), ("safeGasPrice", "Safe gas"), ("proposeGasPrice", "Propose gas"), ("fastGasPrice", "Fast gas")):
        value = gas.get(key)
        if value is not None:
            rows.append({"chain": chain, "metric": label, "value": _to_float(value), "unit": "gwei", "source_mode": "etherscan_gas"})
    glassnode = out.get("glassnode") if isinstance(out.get("glassnode"), dict) else {}
    for metric, item in glassnode.items():
        if isinstance(item, dict) and item.get("latest") is not None:
            rows.append({"chain": chain, "metric": metric, "value": item.get("latest"), "unit": "value", "samples": item.get("samples"), "source_mode": "glassnode"})
    history = []
    for block in out.get("recent_blocks") or []:
        if not isinstance(block, dict):
            continue
        ts = block.get("timestamp")
        date = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat() if ts else None
        history.append({
            "date": date or str(block.get("height")),
            "height": block.get("height"),
            "tx_count": block.get("tx_count"),
            "value": block.get("tx_count"),
            "size": block.get("size"),
            "source_mode": "mempool_blocks",
        })
    return rows, history


def _find_numeric(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _to_float(payload.get(key))
        if value is not None:
            return value
    return None


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
