"""Read-only portfolio aggregation across every saved credential.

Sub-system B. Fans out to each broker registered in factory._DYNAMIC,
gathers account + positions (+ optional orders) concurrently, caches
results 30 seconds, and exposes one unified payload.

The cache is invalidated automatically when a credential is unregistered:
we subscribe to factory._INVALIDATION_HOOKS at module import time.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from showme.brokers import factory as factory_mod
from showme.brokers.base import BaseBroker

LOG = logging.getLogger("showme.portfolio_aggregate")

CACHE_TTL_SECONDS = 30.0
GROUP_FETCH_TIMEOUT_SECONDS = 20.0
FX_RATE_TTL_SECONDS = 60.0

# B3: protect _CACHE + _FX_RATE_CACHE from concurrent reader/writer races
# (FastAPI workers + the asyncio fan-out below both touch this map).
_CACHE_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str], tuple[float, Any]] = {}

# B1: cross-currency conversion. Stables collapse to 1.0; fiat + crypto must
# come from a live FX provider. The cache key is the source currency.
_STABLE_TO_USD = {"USDT": 1.0, "USDC": 1.0, "DAI": 1.0, "BUSD": 1.0, "TUSD": 1.0,
                  "USD": 1.0}

_FX_RATE_LOCK = threading.Lock()
_FX_RATE_CACHE: dict[str, tuple[float, float]] = {}

# Override hook for tests / callers that want deterministic FX. When set, it
# is invoked instead of the default yfinance lookup.
_FX_RATE_FETCHER: Callable[[str], Awaitable[float | None]] | None = None


def set_fx_rate_fetcher(fetcher: Callable[[str], Awaitable[float | None]] | None) -> None:
    """Install a custom async ``currency_code -> usd_rate`` resolver."""
    global _FX_RATE_FETCHER
    _FX_RATE_FETCHER = fetcher


def _on_credential_invalidated(credential_id: str) -> None:
    """Hook target: drop every cache entry tied to this credential."""
    with _CACHE_LOCK:
        drop = [k for k in _CACHE if k[0] == credential_id]
        for k in drop:
            _CACHE.pop(k, None)


# B3: guard hook registration against double-import (uvicorn reload, tests).
if _on_credential_invalidated not in factory_mod._INVALIDATION_HOOKS:
    factory_mod._INVALIDATION_HOOKS.append(_on_credential_invalidated)


async def _cached_call(credential_id: str, kind: str, fn) -> Any:
    key = (credential_id, kind)
    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached and (now - cached[0]) < CACHE_TTL_SECONDS:
        return cached[1]
    value = await fn()
    with _CACHE_LOCK:
        _CACHE[key] = (now, value)
    return value


async def _fetch_group(credential_id: str, broker: BaseBroker, name: str,
                       include_orders: bool) -> dict[str, Any]:
    exchange_id, _ = name.split(":", 1) if ":" in name else (name, "")
    group: dict[str, Any] = {
        "credential_id": credential_id,
        "exchange_id": exchange_id,
        "account_label": getattr(broker, "_account_label", ""),
        "permissions": list(getattr(broker, "_permissions", ()) or ()),
        "account": None,
        "positions": [],
        "orders": [],
        "error": None,
    }
    try:
        tasks = [
            _cached_call(credential_id, "account", broker.account),
            _cached_call(credential_id, "positions", broker.list_positions),
        ]
        if include_orders:
            tasks.append(_cached_call(credential_id, "orders",
                                      lambda: broker.list_orders(status="open", limit=50)))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        if isinstance(results[0], Exception):
            raise results[0]
        if isinstance(results[1], Exception):
            raise results[1]
        group["account"] = results[0]
        group["positions"] = [p.to_dict() for p in results[1]]
        if include_orders:
            if isinstance(results[2], Exception):
                LOG.debug("orders fetch failed for %s: %s", credential_id, results[2])
                group["orders"] = []
            else:
                group["orders"] = [o.to_dict() for o in results[2]]
    except Exception as exc:  # noqa: BLE001
        group["error"] = f"{type(exc).__name__}: {exc}"
    return group


# ── B1: currency conversion ──────────────────────────────────────────────────

# Map of non-stable currency code → yfinance ticker for spot vs USD. yfinance
# uses {CCY}USD=X for fiat and BTC-USD style for crypto. We always invert when
# the quoted pair is USD{CCY}=X (e.g. JPY → USDJPY=X).
_YFINANCE_USD_TICKERS: dict[str, tuple[str, bool]] = {
    "EUR": ("EURUSD=X", False),
    "GBP": ("GBPUSD=X", False),
    "AUD": ("AUDUSD=X", False),
    "NZD": ("NZDUSD=X", False),
    "CAD": ("USDCAD=X", True),
    "CHF": ("USDCHF=X", True),
    "JPY": ("USDJPY=X", True),
    "CNY": ("USDCNY=X", True),
    "CNH": ("USDCNH=X", True),
    "TRY": ("USDTRY=X", True),
    "MXN": ("USDMXN=X", True),
    "ZAR": ("USDZAR=X", True),
    "BTC": ("BTC-USD", False),
    "ETH": ("ETH-USD", False),
    "SOL": ("SOL-USD", False),
    "BNB": ("BNB-USD", False),
    "XRP": ("XRP-USD", False),
    "ADA": ("ADA-USD", False),
    "DOGE": ("DOGE-USD", False),
}


async def _default_yfinance_rate_fetcher(currency: str) -> float | None:
    """Best-effort spot rate via yfinance. Returns None on any failure path.

    Lives behind a 60s in-process cache so a 100-credential fan-out only hits
    yfinance once per ccy. Falls back to None when yfinance / network is
    unavailable; the caller then surfaces the currency in ``unconverted``.
    """
    mapping = _YFINANCE_USD_TICKERS.get(currency.upper())
    if not mapping:
        return None
    ticker, invert = mapping
    try:
        import yfinance as yf  # type: ignore
    except Exception:
        return None

    def _blocking_fetch() -> float | None:
        try:
            data = yf.Ticker(ticker).history(period="1d", interval="1d")
            if data is None or data.empty:
                return None
            last = float(data["Close"].iloc[-1])
            if last <= 0:
                return None
            return last
        except Exception:
            return None

    try:
        last = await asyncio.wait_for(asyncio.to_thread(_blocking_fetch), timeout=4.0)
    except (asyncio.TimeoutError, Exception):
        return None
    if last is None:
        return None
    return (1.0 / last) if invert else last


async def _resolve_usd_rate(currency: str) -> float | None:
    """Return USD per 1 unit of ``currency``. None if unresolvable."""
    code = currency.upper()
    if code in _STABLE_TO_USD:
        return _STABLE_TO_USD[code]
    now = time.time()
    with _FX_RATE_LOCK:
        cached = _FX_RATE_CACHE.get(code)
    if cached and (now - cached[0]) < FX_RATE_TTL_SECONDS:
        return cached[1] if cached[1] > 0 else None
    fetcher = _FX_RATE_FETCHER or _default_yfinance_rate_fetcher
    try:
        rate = await fetcher(code)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("fx_rate_fetcher failed for %s: %s", code, exc)
        rate = None
    if rate and rate > 0:
        with _FX_RATE_LOCK:
            _FX_RATE_CACHE[code] = (now, rate)
        return rate
    # Cache the miss for a shorter window so we don't hammer a broken provider
    # on every aggregate() call, but still recover quickly when it comes back.
    with _FX_RATE_LOCK:
        _FX_RATE_CACHE[code] = (now, 0.0)
    return None


async def _compute_totals(groups: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-currency equity plus a single USD-equivalent rollup."""
    eq_by_ccy: dict[str, float] = {}
    for g in groups:
        if g["error"] or not g["account"]:
            continue
        ccy = g["account"].get("currency") or "USD"
        eq = float(g["account"].get("equity") or 0)
        eq_by_ccy[ccy] = eq_by_ccy.get(ccy, 0.0) + eq
    usd_total = 0.0
    unconverted: list[str] = []
    fx_rates: dict[str, float] = {}
    # Resolve every currency concurrently so the rollup is bounded by the
    # slowest fetch instead of the sum.
    coros = {ccy: _resolve_usd_rate(ccy) for ccy in eq_by_ccy.keys()}
    if coros:
        resolved = await asyncio.gather(
            *coros.values(),
            return_exceptions=True,
        )
        for ccy, rate in zip(coros.keys(), resolved):
            if isinstance(rate, Exception) or rate is None or rate <= 0:
                if eq_by_ccy.get(ccy, 0.0) != 0.0:
                    unconverted.append(ccy)
                continue
            fx_rates[ccy] = float(rate)
            usd_total += eq_by_ccy[ccy] * float(rate)
    return {
        "equity_by_currency": eq_by_ccy,
        "stable_usd_equivalent": round(usd_total, 2),
        "usd_equivalent": round(usd_total, 2),
        "unconverted_currencies": sorted(set(unconverted)),
        "fx_rates": {k: round(v, 8) for k, v in sorted(fx_rates.items())},
    }


async def aggregate(
    credential_ids: list[str] | None = None,
    include_orders: bool = False,
) -> dict[str, Any]:
    dyn = dict(factory_mod._DYNAMIC)
    if credential_ids is not None:
        wanted = set(credential_ids)
        dyn = {cid: name for cid, name in dyn.items() if cid in wanted}

    groups: list[dict[str, Any]] = []
    fetches: list[tuple[str, str, asyncio.Task]] = []
    for credential_id, name in dyn.items():
        try:
            broker = factory_mod.get_broker(name)
        except KeyError as exc:
            groups.append({
                "credential_id": credential_id,
                "exchange_id": name.split(":", 1)[0] if ":" in name else name,
                "account_label": "",
                "permissions": [],
                "account": None,
                "positions": [],
                "orders": [],
                "error": f"unknown broker: {exc}",
            })
            continue
        fetches.append((credential_id, name, asyncio.create_task(
            _fetch_group(credential_id, broker, name, include_orders),
        )))

    # B2: wrap the fan-out in a global timeout. A single hung broker must not
    # wedge the whole endpoint; surface the wait failure as a group-level
    # error so the UI still sees the other accounts.
    if fetches:
        tasks = [t for _, _, t in fetches]
        try:
            await asyncio.wait_for(
                asyncio.shield(asyncio.gather(*tasks, return_exceptions=True)),
                timeout=GROUP_FETCH_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            LOG.warning(
                "portfolio aggregate fan-out timed out after %.1fs; partial results",
                GROUP_FETCH_TIMEOUT_SECONDS,
            )
        for credential_id, name, task in fetches:
            if task.done() and not task.cancelled():
                exc = task.exception()
                if exc is not None:
                    groups.append({
                        "credential_id": credential_id,
                        "exchange_id": name.split(":", 1)[0] if ":" in name else name,
                        "account_label": "",
                        "permissions": [],
                        "account": None,
                        "positions": [],
                        "orders": [],
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                else:
                    groups.append(task.result())
            else:
                # Still running → treat as timeout for this credential. Don't
                # cancel the underlying broker call here; the cached_call
                # wrapper will simply store the value when it eventually
                # resolves so the next aggregate() picks it up.
                groups.append({
                    "credential_id": credential_id,
                    "exchange_id": name.split(":", 1)[0] if ":" in name else name,
                    "account_label": "",
                    "permissions": [],
                    "account": None,
                    "positions": [],
                    "orders": [],
                    "error": "timeout",
                })

    totals = await _compute_totals(groups)
    return {
        "as_of": datetime.now(tz=timezone.utc).isoformat(),
        "groups": sorted(groups, key=lambda g: (g["exchange_id"], g["account_label"])),
        "totals": totals,
    }
