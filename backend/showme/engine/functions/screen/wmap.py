"""MAP — World market heatmap (major equity index ETFs)."""

from __future__ import annotations

import asyncio
import math
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.quotes import fetch_quote_snapshot

# The quote service is imported at module level on purpose: every market quote
# now routes through the fast keyless provider (already TTL-cached for 15 s),
# and a module-level name keeps the fan-out monkeypatchable
# (``monkeypatch.setattr(wmap, "fetch_quote_snapshot", ...)``).


_COUNTRY_ETFS = {
    # Americas
    "US": "SPY",
    "CA": "EWC",
    "MX": "EWW",
    "BR": "EWZ",
    "AR": "ARGT",
    "CL": "ECH",
    "CO": "GXG",
    "PE": "EPU",
    # Europe
    "EU": "VGK",
    "GB": "EWU",
    "DE": "EWG",
    "FR": "EWQ",
    "IT": "EWI",
    "ES": "EWP",
    "NL": "EWN",
    "BE": "EWK",
    "AT": "EWO",
    "CH": "EWL",
    "SE": "EWD",
    "NO": "NORW",
    "DK": "EDEN",
    "FI": "EFNL",
    "IE": "EIRL",
    "PL": "EPOL",
    "GR": "GREK",
    # EMEA
    "TR": "TUR",
    "BIST": "XU100.IS",
    "ZA": "EZA",
    "EG": "EGPT",
    "SA": "KSA",
    "QA": "QAT",
    "AE": "UAE",
    "IL": "EIS",
    # Asia-Pacific
    "IN": "INDA",
    "CN": "FXI",
    "HK": "EWH",
    "KR": "EWY",
    "TW": "EWT",
    "JP": "EWJ",
    "ID": "EIDO",
    "TH": "THD",
    "PH": "EPHE",
    "VN": "VNM",
    "SG": "EWS",
    "MY": "EWM",
    "AU": "EWA",
    "NZ": "ENZL",
}

# Bounded fan-out: the keyless quote service takes ~0.3-2.5 s per symbol, so
# 8 concurrent fetches keep the screen deadline honest without hammering the
# upstream providers with all ~47 requests at once.
_MAX_CONCURRENT_QUOTES = 8


def _unavailable_row(country: str, etf: str) -> dict[str, Any]:
    """A market whose quote failed/timed out — kept in the row list on purpose.

    The pre-rewrite code cancelled pending tasks and dropped them, so the MAP
    surface silently shrank to whichever symbols finished inside the screen
    budget. Failed markets now render as an explicit ``unavailable`` row.
    """
    return {
        "country": country,
        "etf": etf,
        "last": None,
        "change_pct": None,
        "period": "1D",
        "quote_type": "unavailable",
    }


def _map_template() -> list[dict[str, Any]]:
    rows = []
    for i, (country, etf) in enumerate(_COUNTRY_ETFS.items()):
        rows.append({
            "country": country,
            "etf": etf,
            "last": round(50 + i * 1.7, 2),
            "change_pct": round(((i % 9) - 4) * 0.18, 3),
            "period": "1D",
            "quote_type": "model",
        })
    rows.sort(
        key=lambda x: x.get("change_pct") if x.get("change_pct") is not None else -999,
        reverse=True,
    )
    return rows


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


@FunctionRegistry.register
class MAPFunction(BaseFunction):
    code = "MAP"
    name = "World Market Heatmap"
    category = "screen"
    description = "MSCI single-country ETF day-change heatmap (25+ countries)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        live = _truthy(params.get("live_screen")) or _truthy(params.get("live"))
        if not live:
            return FunctionResult(code=self.code, instrument=None,
                                  data={
                                      "status": "model",
                                      "reason": "Deterministic country ETF model selected; values are not live market quotes.",
                                      "period": "1D",
                                      "rows": _map_template(),
                                  },
                                  sources=["world_market_model"])
        # Hard screen budget: symbols that miss it are cancelled but STILL
        # emitted (``unavailable`` rows), so the full market list always
        # renders and the pane can retry on its next poll.
        screen_timeout = max(4.0, min(float(params.get("screen_timeout", 10)), 12.0))
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_QUOTES)

        async def _one(country: str, etf: str) -> dict[str, Any]:
            try:
                async with semaphore:
                    snapshot = await fetch_quote_snapshot(etf)
                if not isinstance(snapshot, dict):
                    raise TypeError(f"quote snapshot for {etf} is not a mapping")
                raw_last = snapshot.get("last")
                if raw_last is None:
                    raw_last = snapshot.get("price")
                raw_prev = snapshot.get("previous_close")
                if raw_prev is None:
                    raw_prev = snapshot.get("previousClose")
                last: float | None = float(raw_last) if raw_last is not None else None
                if last is not None and not math.isfinite(last):
                    last = None
                prev: float | None = None
                if raw_prev not in (None, ""):
                    prev = float(raw_prev)
                    if not math.isfinite(prev):
                        prev = None
                # change_pct = last/prev - 1 (None when either leg is missing —
                # never a phantom -100% from a coerced 0 price).
                change_pct: float | None = (
                    (last / prev - 1.0) * 100.0 if last is not None and prev else None
                )
            except Exception:  # noqa: BLE001 — per-symbol provider failure only
                return _unavailable_row(country, etf)
            if last is None:
                return _unavailable_row(country, etf)
            return {
                "country": country,
                "etf": etf,
                "last": last,
                "change_pct": change_pct,
                "period": "1D",
                "quote_type": "live",
            }

        task_meta: dict[asyncio.Task[dict[str, Any]], tuple[str, str]] = {}
        for country, etf in _COUNTRY_ETFS.items():
            task = asyncio.create_task(_one(country, etf))
            task_meta[task] = (country, etf)
        done, pending = await asyncio.wait(list(task_meta), timeout=screen_timeout)

        rows: list[dict[str, Any]] = []
        for task in done:
            country, etf = task_meta[task]
            if task.cancelled():
                rows.append(_unavailable_row(country, etf))
                continue
            try:
                rows.append(task.result())
            except Exception:  # noqa: BLE001 — _one is defensive, but never gamble
                rows.append(_unavailable_row(country, etf))
        for task in pending:
            task.cancel()
            country, etf = task_meta[task]
            rows.append(_unavailable_row(country, etf))

        live_rows = [row for row in rows if row.get("last") is not None]
        if not live_rows:
            fallback_rows = _map_template()
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "World ETF quote provider returned no usable live rows.",
                    "period": "1D",
                    "rows": fallback_rows,
                    "next_actions": [
                        "Retry MAP after the public quote provider recovers.",
                        "Rows shown are a deterministic country ETF model, not live quotes.",
                        "Use the Live/Model control to switch to the deterministic fallback intentionally.",
                    ],
                },
                sources=["showme_quotes", "world_market_model"],
                metadata={
                    "fallback": True,
                    "degraded": True,
                    "provider_errors": ["showme_quotes world ETF quotes unavailable"],
                },
            )
        rows.sort(
            key=lambda x: x["change_pct"] if x["change_pct"] is not None else -999,
            reverse=True,
        )
        metadata: dict[str, Any] = {}
        unavailable = len(rows) - len(live_rows)
        if unavailable:
            metadata["provider_errors"] = [f"{unavailable} symbol(s) unavailable"]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={"status": "ok", "period": "1D", "rows": rows},
            sources=["showme_quotes"],
            metadata=metadata,
        )
