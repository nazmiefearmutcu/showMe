"""TLH — Tax-Loss Harvesting helper.

For each portfolio position with unrealized losses, propose:
  - an estimated tax saving at the user's bracket (gross per position, and
    netted against supplied realized gains when both are given),
  - a wash-sale status: blocked when the position's open date is inside the
    window (that purchase disallows the loss); otherwise NOT checked, because
    broker buy history is not read here,
  - a similar-but-not-substantially-identical replacement (sector ETF).

Position-level only: the local book has one row per symbol, not tax lots.

Yatay-yardımcı fonksiyon — broker bağlamaz; sadece öneri üretir.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.portfolio.state import PortfolioState
from showme.engine.utils.helpers import datetime_now


# Sector → similar-but-not-identical replacement ETF map. Keys use the Yahoo
# Finance sector vocabulary (what yfinance Ticker.info["sector"] returns, the
# same names eqs.py folds GICS labels onto). GICS-style names are kept as
# aliases for providers that report them.
_SECTOR_REPLACEMENT = {
    "Technology": "VGT",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Utilities": "XLU",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
    "Information Technology": "VGT",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Materials": "XLB",
}

# IRC §1211(b): net capital losses offset ordinary income up to this amount
# per year. It is a USD figure; values here are in each position's native
# currency, so the offset is only exact for USD books.
_ORDINARY_LOSS_OFFSET_LIMIT = 3000.0
# Manifest default for the minimum harvestable loss (native currency).
_DEFAULT_MIN_LOSS = 100.0


@FunctionRegistry.register
class TLHFunction(BaseFunction):
    code = "TLH"
    name = "Tax-Loss Harvesting"
    category = "portfolio"
    description = "Suggest loss lots to sell, estimate tax savings, propose wash-sale-safe swaps."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # 2026-11-07 (strict truth audit): the former non-live "model" path
        # returned an invented candidate (cost 100, price 92, qty 1). TLH now
        # only ever works on the real local portfolio.
        now = datetime_now()
        bracket = float(params.get("tax_bracket", 0.24))     # marginal income / ST cap rate
        lt_rate = float(params.get("lt_cap_rate", 0.15))     # long-term cap gains
        lt_threshold_days = int(params.get("lt_threshold_days", 365))
        raw_min = params.get("min_loss_threshold")
        min_loss = _DEFAULT_MIN_LOSS if raw_min in (None, "") else abs(float(raw_min))
        raw_wash = params.get("wash_sale_window_days")
        wash_days = 30 if raw_wash in (None, "") else max(0, int(raw_wash))
        suggest_replacement = _truthy(params.get("suggest_replacement", True))
        warnings: list[str] = []

        st_gain_raw = params.get("realized_st_gain")
        lt_gain_raw = params.get("realized_lt_gain")
        try:
            st_gain = _optional_float(st_gain_raw)
            lt_gain = _optional_float(lt_gain_raw)
        except ValueError:
            return FunctionResult(
                code=self.code, instrument=None,
                data={
                    "status": "input_error",
                    "reason": "realized_st_gain and realized_lt_gain must be numbers when given.",
                    "next_actions": ["Enter the realized short-term and long-term gains as numbers, or leave both blank."],
                    "candidates": [], "rows": [], "total_estimated_tax_savings": None, "n_loss_positions": 0,
                },
                sources=[], warnings=["Realized gains were not numeric; no savings were computed."],
            )
        gains_supplied = st_gain is not None and lt_gain is not None
        if (st_gain is None) != (lt_gain is None):
            warnings.append(
                "Only one of realized_st_gain / realized_lt_gain was given; both are needed to net, "
                "so savings are shown gross."
            )
        if params.get("credential_id"):
            warnings.append("credential_id is ignored: TLH reads the local position book, not a broker account.")
        ccy_req = str(params.get("ccy") or "native").strip()
        if ccy_req.lower() not in ("", "native"):
            warnings.append(
                f"Display currency {ccy_req} was not applied; values are in each position's native currency."
            )

        base = {
            "as_of": now.isoformat(),
            "credential_id": None,
            "data_mode": "local_portfolio",
            "paper_mode": True,
            "ccy": "native",
            "granularity": "position",
            "lot_level": False,
            "tax_bracket_used": bracket,
            "lt_cap_rate_used": lt_rate,
            "min_loss_threshold": min_loss,
            "wash_sale_window_days": wash_days,
            "wash_sale_checked": False,
            "wash_sale_rule_respected": None,
            "ordinary_loss_offset_limit": _ORDINARY_LOSS_OFFSET_LIMIT,
            "realized_gains_supplied": gains_supplied,
            "methodology": _methodology(),
            "field_dictionary": _field_dictionary(),
        }
        portfolio = PortfolioState()
        if _truthy(params.get("include_legacy") or params.get("legacy")):
            portfolio.import_legacy_crypto()
        if not portfolio.positions:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    **base,
                    "status": "empty",
                    "reason": "The local portfolio has no positions, so there are no losses to harvest.",
                    "next_actions": ["Add positions with their cost basis and open date in PORT, then re-run TLH."],
                    "candidates": [],
                    "rows": [],
                    "total_estimated_tax_savings": 0,
                    "total_harvestable_loss": 0,
                    "n_loss_positions": 0,
                },
                sources=["portfolio_state"],
                warnings=warnings,
            )

        async def _meta(sym: str, quote_timeout: float):
            try:
                inst = await asyncio.wait_for(
                    self.deps.symbol_registry.resolve(sym),
                    timeout=max(0.5, min(float(params.get("resolve_timeout", 1.5)), 2.0)),
                ) if getattr(self.deps, "symbol_registry", None) else None
                if not inst:
                    inst = Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
                if not getattr(self.deps, "yfinance", None):
                    return sym, None, None
                q = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(kind=DataKind.QUOTE, instrument=inst)),
                    timeout=quote_timeout,
                )
                sector = None
                if suggest_replacement:
                    try:
                        rd = await asyncio.wait_for(
                            self.deps.yfinance.fetch(DataRequest(kind=DataKind.REFDATA, instrument=inst)),
                            timeout=quote_timeout,
                        )
                        sector = getattr(rd, "sector", None)
                    except Exception:  # noqa: BLE001 - sector is optional
                        sector = None
                return sym, (q.last if q else None), sector
            except Exception:  # noqa: BLE001 - reported as unpriced below
                return sym, None, None

        quote_timeout = max(1.0, min(float(params.get("quote_timeout", 2.5)), 3.0))
        retry_timeout = max(quote_timeout, min(float(params.get("retry_quote_timeout", 6.0)), 8.0))
        max_positions = max(1, min(int(params.get("max_positions", 25)), 100))
        positions = portfolio.positions[:max_positions]
        meta = await asyncio.gather(*(_meta(p.instrument.symbol, quote_timeout) for p in positions))
        meta_map = {sym: (price, sector) for sym, price, sector in meta}
        # One slow quote must not silently drop a loss lot: retry the unpriced
        # symbols once with a longer timeout before reporting them as unpriced.
        missing = list(dict.fromkeys(
            p.instrument.symbol for p in positions
            if meta_map.get(p.instrument.symbol, (None, None))[0] is None
        ))
        if missing:
            retried = await asyncio.gather(*(_meta(sym, retry_timeout) for sym in missing))
            for sym, price, sector in retried:
                if price is not None:
                    meta_map[sym] = (price, sector)
        candidates: list[dict[str, Any]] = []
        unpriced: list[str] = []
        for pos in positions:
            price, sector = meta_map.get(pos.instrument.symbol, (None, None))
            if price is None:
                unpriced.append(pos.instrument.symbol)
                continue
            if pos.avg_cost <= 0:
                continue
            unrealized = (price - pos.avg_cost) * pos.quantity
            if unrealized >= 0 or -unrealized < min_loss:
                continue
            opened = pos.opened_at if pos.opened_at.tzinfo else pos.opened_at.replace(tzinfo=timezone.utc)
            held_days = max(1, (now - opened).days)
            # US rule: long-term means held MORE than one year (366+ days).
            is_long = held_days > lt_threshold_days
            tax_rate = lt_rate if is_long else bracket
            replacement = _SECTOR_REPLACEMENT.get(sector) if (sector and suggest_replacement) else None
            if replacement and replacement.upper() == pos.instrument.symbol.upper():
                replacement = None  # would be substantially identical
            # A purchase inside the window disallows the loss. The only buy
            # date available here is the position open date, so this is a
            # positive finding only; absence of a blocking buy is NOT proven.
            if held_days <= wash_days:
                wash_safe: bool | None = False
                wash_status = "blocked_open_date_in_window"
                wash_reason = (
                    f"Position was opened on {opened.strftime('%Y-%m-%d')}, inside the {wash_days}-day "
                    "window; that purchase disallows the loss (US §1091). Open date from the local book."
                )
            else:
                wash_safe = None
                wash_status = "not_checked"
                wash_reason = (
                    "Broker buy history is not checked; a repurchase of a substantially identical "
                    "security inside the window would disallow the loss."
                )
            candidates.append({
                "symbol": pos.instrument.symbol,
                "asset_class": pos.instrument.asset_class.value,
                "quantity": pos.quantity,
                "avg_cost": pos.avg_cost,
                "current_price": price,
                "unrealized_pnl": unrealized,
                "opened_at": opened.strftime("%Y-%m-%d"),
                "held_days": held_days,
                "long_term": is_long,
                "tax_rate_applied": tax_rate,
                # Gross, per position: the loss times the rate, before netting.
                "estimated_tax_savings": -unrealized * tax_rate,
                "sector": sector,
                "replacement_etf": replacement,
                "wash_sale_checked": False,
                "wash_sale_safe": wash_safe,
                "wash_sale_status": wash_status,
                "wash_sale_reason": wash_reason,
                "wash_sale_window": [
                    (now - timedelta(days=wash_days)).strftime("%Y-%m-%d"),
                    (now + timedelta(days=wash_days)).strftime("%Y-%m-%d"),
                ],
            })
        candidates.sort(key=lambda x: x["estimated_tax_savings"], reverse=True)
        # Blocked positions stay listed (the user sees the constraint) but are
        # never counted as harvestable.
        harvestable = [c for c in candidates if c["wash_sale_safe"] is not False]
        blocked = [c for c in candidates if c["wash_sale_safe"] is False]
        gross_total = sum(c["estimated_tax_savings"] for c in harvestable)
        total_harvestable_loss = sum(-c["unrealized_pnl"] for c in harvestable)
        if gains_supplied:
            st_loss = sum(-c["unrealized_pnl"] for c in harvestable if not c["long_term"])
            lt_loss = sum(-c["unrealized_pnl"] for c in harvestable if c["long_term"])
            baseline = _tax_on_net_gains(st_gain, lt_gain, bracket, lt_rate)
            after = _tax_on_net_gains(st_gain - st_loss, lt_gain - lt_loss, bracket, lt_rate)
            total_savings = baseline - after
            savings_basis = "netted_against_supplied_realized_gains"
        else:
            total_savings = gross_total
            savings_basis = "gross_upper_bound_no_gains_supplied"
            if candidates:
                warnings.append(
                    "Savings are gross: realized gains were not supplied, so losses are not netted "
                    "against gains and the $3,000 ordinary-income offset is not applied."
                )
        if blocked:
            warnings.append(
                f"{len(blocked)} position(s) blocked by a purchase inside the wash-sale window; "
                "excluded from the savings total."
            )
        unpriced_symbols = sorted(set(unpriced))
        if unpriced_symbols:
            warnings.append(f"No current quote for {', '.join(unpriced_symbols)}; those positions were not evaluated.")
        if len(portfolio.positions) > max_positions:
            warnings.append(f"Only the first {max_positions} of {len(portfolio.positions)} positions were evaluated.")
        priced = len(positions) - len(unpriced)
        base["savings_basis"] = savings_basis
        base["gross_estimated_tax_savings"] = gross_total
        if priced == 0:
            return FunctionResult(
                code=self.code, instrument=None,
                data={**base, "status": "provider_unavailable",
                      "reason": "No current quotes were available for any portfolio position.",
                      "next_actions": ["Retry when the quote provider is reachable."],
                      "candidates": [], "rows": [], "total_estimated_tax_savings": 0, "n_loss_positions": 0,
                      "total_harvestable_loss": 0,
                      "unpriced_symbols": unpriced_symbols},
                sources=["portfolio_state"], warnings=warnings,
            )
        # Any unpriced position means the result is incomplete: never "ok" with
        # zero candidates while a position could be at a loss.
        status = "partial" if unpriced_symbols else "ok"
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                **base,
                "status": status,
                "candidates": candidates,
                "rows": candidates,
                "total_estimated_tax_savings": total_savings,
                "total_harvestable_loss": total_harvestable_loss,
                "n_loss_positions": len(candidates),
                "unpriced_symbols": unpriced_symbols,
                "summary": {
                    "positions_evaluated": priced,
                    "positions_unpriced": len(unpriced_symbols),
                    "n_loss_positions": len(candidates),
                    "wash_blocked_count": len(blocked),
                    "total_estimated_tax_savings": total_savings,
                    "gross_estimated_tax_savings": gross_total,
                    "savings_basis": savings_basis,
                    "tax_bracket_used": bracket,
                },
            },
            sources=["portfolio_state", "yfinance"],
            warnings=warnings,
            metadata={"note": "Wash-sale rule (US 1091): repurchasing a substantially identical security within the window before/after the sale disallows the loss. This run only detects a purchase implied by the position open date; broker buy history is not checked. Replacement ETFs are similar-not-identical; consult a CPA before acting."},
        )


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(str(value)) from exc


def _tax_on_net_gains(st: float, lt: float, bracket: float, lt_rate: float) -> float:
    """Tax liability (negative = benefit) on signed net short- and long-term gains.

    Follows the US netting order: same-term first, then cross-term. A remaining
    net capital loss offsets ordinary income up to the annual limit; the excess
    carries forward and is not counted as a saving this year.
    """
    if st >= 0 and lt >= 0:
        return st * bracket + lt * lt_rate
    if st < 0 and lt < 0:
        net_loss = -(st + lt)
    elif st < 0:  # lt >= 0: the short-term loss offsets long-term gain first
        remainder = lt + st
        if remainder >= 0:
            return remainder * lt_rate
        net_loss = -remainder
    else:  # lt < 0, st >= 0: the long-term loss offsets short-term gain first
        remainder = st + lt
        if remainder >= 0:
            return remainder * bracket
        net_loss = -remainder
    return -min(_ORDINARY_LOSS_OFFSET_LIMIT, net_loss) * bracket


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _methodology() -> str:
    return (
        "Find positions whose current price is below cost basis by at least the minimum loss, estimate the "
        "loss if sold, and apply the short- or long-term tax rate (gross, per position). When realized short- "
        "and long-term gains are supplied, the total nets the harvested losses against them and applies the "
        "$3,000 ordinary-income offset. A position whose open date is inside the wash-sale window is blocked; "
        "other positions are NOT checked against broker buy history. Replacement ETFs are suggested by sector "
        "when available. The output is advisory and not a tax filing or trade instruction."
    )


def _field_dictionary() -> dict[str, str]:
    return {
        "unrealized_pnl": "Current price minus average cost, multiplied by quantity.",
        "estimated_tax_savings": "Gross per position: absolute unrealized loss multiplied by the applicable tax rate.",
        "total_estimated_tax_savings": "Netted against supplied realized gains when savings_basis says so; otherwise the gross sum over non-blocked positions.",
        "gross_estimated_tax_savings": "Sum of per-position gross savings over non-blocked positions, before any netting.",
        "savings_basis": "netted_against_supplied_realized_gains, or gross_upper_bound_no_gains_supplied.",
        "wash_sale_window": "Observation window: 30 days before through 30 days after sale. Not a check of buy history.",
        "wash_sale_status": "blocked_open_date_in_window when the open date is inside the window; not_checked otherwise.",
        "wash_sale_safe": "False when blocked; null when not checked (never a proof of safety).",
        "replacement_etf": "Similar sector ETF candidate, not guaranteed to be tax-safe.",
        "granularity": "position: one row per symbol in the local book, not per tax lot.",
    }
