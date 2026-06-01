"""ONCH — On-Chain Network Vitals.

Live on-chain network health for Bitcoin, sourced entirely from keyless
public APIs (mempool.space + CoinGecko). This replaces the previous stub
whose DEFAULT path returned a gated ``provider_unavailable`` placeholder
(real data was hidden behind ``live=true`` plus key-gated Etherscan /
Glassnode that are inert without an API key). The default path now
returns real, live metrics with no key required.
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument

_MEMPOOL_BASE = "https://mempool.space/api"
_COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"
_UA = {"User-Agent": "showMe research contact@example.com"}

# Hardcoded values the legacy stub leaned on / the kind of canned numbers a
# fake implementation would echo. Kept ONLY so tests can assert we never
# return them on the happy path again.
_LEGACY_HASHRATE_EH = 512.0
_LEGACY_DIFFICULTY_T = 88.4
_LEGACY_MEMPOOL_COUNT = 12000
_LEGACY_FASTEST_FEE = 8
_LEGACY_BLOCK_HEIGHT = 840000

_METHODOLOGY = (
    "ONCH fetches Bitcoin on-chain network vitals live from mempool.space "
    "(recommended fees, projected mempool blocks, difficulty adjustment, "
    "3-day mining hashrate, and the chain tip height) and combines them with "
    "companion market context from CoinGecko's global endpoint (BTC "
    "dominance, total market cap, 24h volume). No API keys are used. Hashrate "
    "is normalised to EH/s and difficulty to trillions (T). The fee histogram "
    "series carries the transaction count projected for each upcoming mempool "
    "block. On a genuine upstream outage the handler returns "
    "data_mode='not_configured' style status='provider_unavailable' with an "
    "honest warning and next_actions — it never fabricates address counts, "
    "fee curves, or a synthetic gas trend."
)

_FIELD_DICTIONARY = {
    "metric": "Name of the on-chain / market metric.",
    "value": "Live measured value formatted for display.",
    "unit": "Unit of the value (sat/vB, EH/s, T, tx, %, USD).",
    "source": "Provider the row came from (mempool / coingecko).",
    "context": "Short interpretation or provenance for the value.",
    "time_utc": "Observation time (UTC) when applicable.",
    "mempool_count": "Number of unconfirmed transactions waiting in the mempool.",
    "fastest_fee": "Recommended fee for next-block inclusion (sat/vB).",
    "hashrate": "Current Bitcoin network hashrate (EH/s, 3-day average).",
    "difficulty": "Current Bitcoin mining difficulty (in trillions, T).",
    "bucket": "Projected block index in the mempool fee histogram.",
    "count": "Transaction count projected to land in that block.",
}


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
    description = "Crypto on-chain: fees, hash rate, difficulty, mempool, market context."

    async def execute(
        self, instrument: Instrument | None = None, **params: Any
    ) -> FunctionResult:
        """Return live keyless Bitcoin on-chain network vitals (default path)."""
        timeout = float(params.get("timeout", 12))
        try:
            payload = await self._fetch_live(timeout)
        except Exception as exc:  # noqa: BLE001 - network/parse failures handled below
            return self._unavailable(instrument, exc)
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=payload,
            sources=["mempool", "coingecko"],
            metadata={"keyless": True},
        )

    # ------------------------------------------------------------------ live

    async def _fetch_live(self, timeout: float) -> dict[str, Any]:
        from showme.providers._http import get_client

        client = await get_client()

        async def _json(url: str) -> Any:
            resp = await client.get(url, headers=_UA, timeout=timeout)
            resp.raise_for_status()
            return resp.json()

        # mempool.space core (all keyless, all required for a healthy payload)
        fees, blocks, diff, hashr, tip = await asyncio.gather(
            _json(f"{_MEMPOOL_BASE}/v1/fees/recommended"),
            _json(f"{_MEMPOOL_BASE}/v1/fees/mempool-blocks"),
            _json(f"{_MEMPOOL_BASE}/v1/difficulty-adjustment"),
            _json(f"{_MEMPOOL_BASE}/v1/mining/hashrate/3d"),
            _json(f"{_MEMPOOL_BASE}/blocks/tip/height"),
        )

        if not isinstance(blocks, list):
            blocks = []
        if not isinstance(fees, dict):
            fees = {}
        if not isinstance(diff, dict):
            diff = {}
        if not isinstance(hashr, dict):
            hashr = {}

        fastest = _as_num(fees.get("fastestFee"))
        half_hour = _as_num(fees.get("halfHourFee"))
        hour = _as_num(fees.get("hourFee"))
        economy = _as_num(fees.get("economyFee"))
        minimum = _as_num(fees.get("minimumFee"))

        mempool_count = sum(int(b.get("nTx", 0) or 0) for b in blocks)
        projected_blocks = len(blocks)

        hashrate_hs = _as_num(hashr.get("currentHashrate"))
        hashrate_eh = (hashrate_hs / 1e18) if hashrate_hs is not None else None
        difficulty_raw = _as_num(hashr.get("currentDifficulty"))
        difficulty_t = (difficulty_raw / 1e12) if difficulty_raw is not None else None

        diff_change = _as_num(diff.get("difficultyChange"))
        diff_progress = _as_num(diff.get("progressPercent"))
        remaining_blocks = _as_num(diff.get("remainingBlocks"))

        tip_height = int(tip) if isinstance(tip, (int, float)) else None

        # CoinGecko global market context (best-effort, keyless)
        btc_dominance: float | None = None
        total_mcap_usd: float | None = None
        total_vol_usd: float | None = None
        try:
            cg = await _json(_COINGECKO_GLOBAL)
            gd = cg.get("data", {}) if isinstance(cg, dict) else {}
            btc_dominance = _as_num((gd.get("market_cap_percentage") or {}).get("btc"))
            total_mcap_usd = _as_num((gd.get("total_market_cap") or {}).get("usd"))
            total_vol_usd = _as_num((gd.get("total_volume") or {}).get("usd"))
        except Exception:  # noqa: BLE001 - companion metrics are optional
            pass

        def _row(metric: str, value: str, unit: str, source: str, context: str) -> dict[str, Any]:
            return {
                "metric": metric,
                "value": value,
                "unit": unit,
                "source": source,
                "context": context,
            }

        rows: list[dict[str, Any]] = [
            _row("Mempool Backlog", f"{mempool_count:,}", "tx", "mempool",
                 f"Across {projected_blocks} projected blocks"),
            _row("Fastest Fee", _fmt(fastest), "sat/vB", "mempool", "Next-block inclusion"),
            _row("Half-Hour Fee", _fmt(half_hour), "sat/vB", "mempool", "~30 min confirmation"),
            _row("Hour Fee", _fmt(hour), "sat/vB", "mempool", "~60 min confirmation"),
            _row("Economy Fee", _fmt(economy), "sat/vB", "mempool", "Low-priority inclusion"),
            _row("Minimum Fee", _fmt(minimum), "sat/vB", "mempool", "Mempool purge floor"),
            _row("Hashrate", _fmt(hashrate_eh, 1), "EH/s", "mempool", "3-day average"),
            _row("Difficulty", _fmt(difficulty_t, 2), "T", "mempool", "Current epoch"),
            _row(
                "Difficulty Change", _fmt(diff_change, 2), "%", "mempool",
                f"{_fmt(diff_progress, 1)}% through epoch, {_fmt(remaining_blocks, 0)} blocks left",
            ),
            _row(
                "Block Height",
                f"{tip_height:,}" if tip_height is not None else "—",
                "", "mempool", "Chain tip",
            ),
        ]

        if btc_dominance is not None:
            rows.append(_row("BTC Dominance", _fmt(btc_dominance, 2), "%", "coingecko",
                             "Share of total crypto market cap"))
        if total_mcap_usd is not None:
            rows.append(_row("Total Market Cap", _fmt_usd(total_mcap_usd), "USD", "coingecko",
                             "All cryptocurrencies"))
        if total_vol_usd is not None:
            rows.append(_row("24h Volume", _fmt_usd(total_vol_usd), "USD", "coingecko",
                             "All cryptocurrencies"))

        # Fee histogram: projected tx count per upcoming block (chart_grammar).
        series = [
            {"bucket": f"Block +{i + 1}", "count": int(b.get("nTx", 0) or 0)}
            for i, b in enumerate(blocks)
        ]

        cards = [
            {"label": "Chain", "value": "BTC"},
            {"label": "Mempool", "value": f"{mempool_count:,} tx"},
            {"label": "Fastest Fee", "value": f"{_fmt(fastest)} sat/vB"},
            {"label": "Hashrate",
             "value": f"{_fmt(hashrate_eh, 1)} EH/s" if hashrate_eh is not None else "—"},
            {"label": "Difficulty",
             "value": f"{_fmt(difficulty_t, 2)} T" if difficulty_t is not None else "—"},
        ]

        summary = (
            f"{mempool_count:,} txs in the mempool; next-block fee "
            f"{_fmt(fastest)} sat/vB; hashrate {_fmt(hashrate_eh, 1)} EH/s "
            f"at difficulty {_fmt(difficulty_t, 2)} T"
        )
        if tip_height is not None:
            summary += f" (tip {tip_height:,})."
        else:
            summary += "."

        return {
            "status": "ok",
            "data_mode": "delayed_reference",
            "chain": "BTC",
            "rows": rows,
            "series": series,
            "cards": cards,
            "summary": summary,
            "methodology": _METHODOLOGY,
            "field_dictionary": _FIELD_DICTIONARY,
        }

    # --------------------------------------------------------------- failure

    def _unavailable(self, instrument: Instrument | None, exc: Exception) -> FunctionResult:
        """Honest, clearly-labeled fallback on a genuine network/parse failure."""
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "provider_unavailable",
                "data_mode": "not_configured",
                "chain": "BTC",
                "rows": [],
                "series": [],
                "cards": [],
                "summary": "On-chain network vitals are temporarily unavailable.",
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICTIONARY,
                "warnings": [f"Live on-chain fetch failed: {type(exc).__name__}: {exc}"],
                "next_actions": [
                    "Retry shortly — mempool.space / CoinGecko may be rate-limiting.",
                    "Check network connectivity to the public APIs.",
                ],
            },
            sources=["mempool", "coingecko"],
            metadata={"keyless": True, "error": type(exc).__name__},
        )


def _as_num(value: Any) -> float | None:
    """Coerce to float; None for missing / non-numeric / bool."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: float | None, decimals: int = 0) -> str:
    """Format a number for display, '—' when missing."""
    if value is None:
        return "—"
    if decimals <= 0:
        return f"{value:,.0f}"
    return f"{value:,.{decimals}f}"


def _fmt_usd(value: float | None) -> str:
    """Human-readable USD with magnitude suffix."""
    if value is None:
        return "—"
    abs_v = abs(value)
    if abs_v >= 1e12:
        return f"${value / 1e12:.2f}T"
    if abs_v >= 1e9:
        return f"${value / 1e9:.2f}B"
    if abs_v >= 1e6:
        return f"${value / 1e6:.2f}M"
    return f"${value:,.0f}"
