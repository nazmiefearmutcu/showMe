"""TAUC — US Treasury Auction Calendar."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class TAUCFunction(BaseFunction):
    code = "TAUC"
    name = "Treasury Auction Calendar"
    asset_classes = (AssetClass.BOND,)
    category = "bond"
    description = "Upcoming + recent Treasury auctions (Bills/Notes/Bonds/TIPS/FRN)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = (params.get("action") or "upcoming").lower()
        horizon = int(params.get("horizon_days", 30))
        security_filter = str(params.get("security_type") or params.get("type") or "").strip().lower()
        limit = params.get("limit")
        limit = int(limit) if limit else None
        # Default polarity (2026-09-11, L5): the keyless TreasuryDirect
        # adapter is the DEFAULT. An explicit falsy ``live_auctions``/``live``
        # (or ``reference=true``) opts back into the labelled template.
        reference = _truthy(params.get("reference"))
        live_param_present = (
            params.get("live_auctions") is not None or params.get("live") is not None
        )
        live_requested = (
            _truthy(params.get("live_auctions") or params.get("live"))
            if live_param_present
            else True
        )
        if reference or not live_requested:
            items = _limit_rows(_filter_security_type(_template_auctions(action, horizon), security_filter), limit)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_auction_payload(action, horizon, items, "treasury_auction_model", security_filter),
                sources=["treasury_auction_model"],
                metadata={
                    "live": False,
                    "fallback": True,
                    "degraded": True,
                    "data_mode": "modeled",
                },
            )
        if not self.deps.treasury_auctions:
            return _unavailable_result(
                self.code, action, horizon, security_filter,
                reason="TreasuryDirect adapter is not configured, so no auction rows were fetched.",
                next_actions=[
                    "Configure the treasury_auctions adapter.",
                    "Pass reference=true to see the labelled illustrative calendar model instead.",
                ],
                warnings=["no treasury_auctions adapter"],
            )
        timeout = float(params.get("auction_timeout", params.get("timeout", 6)))
        # The adapter is asked for the whole window: a row limit applied
        # upstream would truncate before the security_type filter and could
        # drop every row of the requested type. Filter first, then limit.
        try:
            if action == "recent":
                items = await asyncio.wait_for(
                    self.deps.treasury_auctions.recent(days=horizon, limit=None),
                    timeout=timeout,
                )
            else:
                items = await asyncio.wait_for(
                    self.deps.treasury_auctions.upcoming(horizon_days=horizon, limit=None),
                    timeout=timeout,
                )
        except Exception as exc:
            error = f"treasurydirect: {type(exc).__name__}: {exc}"
            return _unavailable_result(
                self.code, action, horizon, security_filter,
                reason=f"TreasuryDirect did not return auction rows ({error}).",
                next_actions=["Retry later, or pass reference=true for the labelled illustrative calendar model."],
                warnings=[error],
            )
        # Rows the adapter returned are already inside the requested window, so
        # a non-zero raw count means the feed answered and the filter removed them.
        raw_count = len(items)
        items = _limit_rows(_filter_security_type(items, security_filter), limit)
        payload = _auction_payload(action, horizon, items, "treasurydirect", security_filter)
        if not items:
            # The live feed answered but no row survives: say which of the two
            # cases happened instead of returning a bare ok with zero rows.
            window = "look-back" if action == "recent" else "upcoming"
            if raw_count:
                payload["reason"] = (
                    f"TreasuryDirect returned {raw_count} {action} auction row(s) in the {horizon}-day "
                    f"{window} window, but none match security_type={security_filter!r}."
                )
                payload["next_actions"] = ["Clear the security_type filter to see every auction in the window."]
            else:
                payload["reason"] = (
                    f"TreasuryDirect returned no {action} auction rows in the {horizon}-day "
                    f"{window} window (feed answered; rows with no usable auction date are excluded)."
                )
                payload["next_actions"] = ["Retry later, or widen the horizon."]
            payload["status"] = "empty"
        return FunctionResult(
            code=self.code, instrument=None,
            data=payload,
            sources=["treasurydirect"],
            metadata={"live": True, "data_mode": "live_official"},
        )


def _unavailable_result(
    code: str,
    action: str,
    horizon: int,
    security_filter: str,
    *,
    reason: str,
    next_actions: list[str],
    warnings: list[str],
) -> FunctionResult:
    """Honest no-data state: no rows are invented when the live feed cannot answer."""
    payload = _auction_payload(action, horizon, [], "treasurydirect_unavailable", security_filter)
    payload["status"] = "provider_unavailable"
    payload["reason"] = reason
    payload["next_actions"] = next_actions
    return FunctionResult(
        code=code, instrument=None,
        data=payload,
        sources=["treasurydirect"],
        warnings=warnings,
        metadata={"live": False, "degraded": True, "data_mode": "unavailable"},
    )


def _auction_payload(action: str, horizon: int, items: list[dict[str, Any]], source_mode: str, security_filter: str = "") -> dict[str, Any]:
    tag = "recent" if action == "recent" else "upcoming"
    by_type: dict[str, dict[str, Any]] = {}
    for it in items:
        t = it.get("security_type") or "Unknown"
        slot = by_type.setdefault(t, {"security_type": t, "count": 0, "total_offering": 0.0, "_known": 0})
        slot["count"] += 1
        raw = it.get("offering_amount")
        try:
            amt = float(raw) if raw not in (None, "") else None
        except Exception:
            amt = None
        if amt is not None:
            slot["total_offering"] += amt
            slot["_known"] += 1
    # A total is only reported when at least one offering size is known. The
    # labelled model carries no sizes, so its totals are null, never a zero.
    by_type_rows: list[dict[str, Any]] = []
    for slot in by_type.values():
        known = slot.pop("_known")
        if not known:
            slot["total_offering"] = None
        by_type_rows.append(slot)
    return {
        "rows": items,
        tag: items,
        "n": len(items),
        "by_type": by_type_rows,
        "horizon_days": horizon,
        "summary": {"action": tag, "horizon_days": horizon, "auctions": len(items), "source_mode": source_mode, "security_filter": security_filter or "all"},
        "methodology": "TAUC lists live TreasuryDirect auction rows; the auction day is competitiveAuctionCloseDate when auctionDate is null. When the feed is unavailable no rows are invented. The labelled reference model (reference=true or live_auctions=false) is illustrative, not live, and is labelled by source_mode.",
        "field_dictionary": {
            "security_type": "Bill, Note, Bond, TIPS, or FRN.",
            "term": "Auction security term.",
            "auction_date": "Calendar auction date.",
            "offering_amount": "Offering amount in USD.",
        },
    }


def _template_auctions(action: str, horizon: int | None) -> list[dict[str, Any]]:
    """Labelled calendar SHAPE only: the offering sizes are not modelled.

    Dates are offsets from today and only the rows that fall inside the
    requested window are returned, so the horizon is honoured. The offering
    amount is None: a size is never invented for a model row.
    """
    today = datetime.now(timezone.utc).date()
    sign = -1 if action == "recent" else 1
    shape = (
        ("Bill", "13-Week", 3),
        ("Bill", "26-Week", 4),
        ("Note", "2-Year", 7),
        ("Note", "5-Year", 8),
        ("Bond", "30-Year", 15),
    )
    window = horizon if horizon and horizon > 0 else max(offset for _, _, offset in shape)
    return [
        {
            "security_type": security_type,
            "term": term,
            "auction_date": (today + timedelta(days=sign * offset)).isoformat(),
            "offering_amount": None,
        }
        for security_type, term, offset in shape
        if offset <= window
    ]


def _limit_rows(rows: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    return rows[:limit] if limit else rows


def _filter_security_type(rows: list[dict[str, Any]], security_filter: str) -> list[dict[str, Any]]:
    if not security_filter:
        return rows
    return [row for row in rows if security_filter in str(row.get("security_type", "")).lower() or security_filter in str(row.get("term", "")).lower()]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
