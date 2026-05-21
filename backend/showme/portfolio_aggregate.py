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
import time
from datetime import datetime, timezone
from typing import Any

from showme.brokers import factory as factory_mod
from showme.brokers.base import BaseBroker

LOG = logging.getLogger("showme.portfolio_aggregate")

CACHE_TTL_SECONDS = 30.0
_CACHE: dict[tuple[str, str], tuple[float, Any]] = {}

_STABLE_TO_USD = {"USDT": 1.0, "USDC": 1.0, "DAI": 1.0, "BUSD": 1.0, "TUSD": 1.0,
                  "USD": 1.0}


def _on_credential_invalidated(credential_id: str) -> None:
    """Hook target: drop every cache entry tied to this credential."""
    drop = [k for k in _CACHE if k[0] == credential_id]
    for k in drop:
        _CACHE.pop(k, None)


if _on_credential_invalidated not in factory_mod._INVALIDATION_HOOKS:
    factory_mod._INVALIDATION_HOOKS.append(_on_credential_invalidated)


async def _cached_call(credential_id: str, kind: str, fn) -> Any:
    key = (credential_id, kind)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and (now - cached[0]) < CACHE_TTL_SECONDS:
        return cached[1]
    value = await fn()
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


def _compute_totals(groups: list[dict[str, Any]]) -> dict[str, Any]:
    eq_by_ccy: dict[str, float] = {}
    for g in groups:
        if g["error"] or not g["account"]:
            continue
        ccy = g["account"].get("currency") or "USD"
        eq = float(g["account"].get("equity") or 0)
        eq_by_ccy[ccy] = eq_by_ccy.get(ccy, 0.0) + eq
    usd_total = 0.0
    for ccy, amt in eq_by_ccy.items():
        if ccy in _STABLE_TO_USD:
            usd_total += amt * _STABLE_TO_USD[ccy]
    return {
        "equity_by_currency": eq_by_ccy,
        "stable_usd_equivalent": round(usd_total, 2),
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
    fetches: list[tuple[str, asyncio.Task]] = []
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
        fetches.append((credential_id, asyncio.create_task(
            _fetch_group(credential_id, broker, name, include_orders),
        )))

    for _, task in fetches:
        groups.append(await task)

    return {
        "as_of": datetime.now(tz=timezone.utc).isoformat(),
        "groups": sorted(groups, key=lambda g: (g["exchange_id"], g["account_label"])),
        "totals": _compute_totals(groups),
    }
