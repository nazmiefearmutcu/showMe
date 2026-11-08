"""REBA — Position Rebalancer.

Given target weights ({sym: pct}), reads the portfolio and current prices and
produces a per-symbol BUY/SELL order preview:

Out: list of {symbol, action, quantity, notional, current_weight, target_weight}
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.portfolio.state import PortfolioState


@FunctionRegistry.register
class REBAFunction(BaseFunction):
    code = "REBA"
    name = "Portfolio Rebalancer"
    category = "portfolio"
    description = "Compute orders to bring current portfolio to target weights."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        targets: dict[str, float] = params.get("targets") or {}
        threshold = float(params.get("min_drift_pct", 0.005))
        cash_cap = params.get("max_notional")
        # REBA#5: honour the manifest controls the handler can execute.
        min_trade = _num_param(params.get("min_trade_size"), 100.0)
        lot_mode, lot_warnings = _lot_mode(params.get("lot_rounding"))
        notes = [*_input_notes(params), *lot_warnings]
        if not targets:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=["targets dict required: {SYM: weight_fraction}"])
        s = sum(targets.values())
        if s <= 0:
            # "QQQ:0"-style full-exit instructions must be kept (never silently
            # dropped), but an all-zero book has nothing to normalize against —
            # previously `v / s` raised ZeroDivisionError and 500'd the request.
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_error",
                    "rows": [],
                    "orders": [],
                    "liquidations": [],
                    "reason": (
                        "Target weights must sum to a positive value; "
                        "at least one symbol needs a weight above 0."
                    ),
                    "next_actions": [
                        "Provide targets like SPY:60, QQQ:0, or a positive capital.",
                    ],
                },
                sources=[],
                warnings=["REBA: target weights sum to zero — nothing to rebalance or liquidate."],
            )
        if abs(s - 1.0) > 0.01:
            # Auto-normalize
            targets = {k: v / s for k, v in targets.items()}
        if not _truthy(params.get("live_portfolio") or params.get("deep")):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_rebalance_model(targets, cash_cap),
                sources=["rebalance_model"],
                metadata={"live": False},
                warnings=[*notes, "REBA: model mode has no current holdings; no orders were sized."],
            )

        portfolio = PortfolioState()
        if _truthy(params.get("include_legacy") or params.get("legacy")):
            portfolio.import_legacy_crypto()
        # Resolve current prices for both portfolio & target symbols
        target_syms = {str(sym).upper() for sym in targets.keys()}
        portfolio_syms = {p.instrument.symbol.upper() for p in portfolio.positions}
        all_syms = set(target_syms) | portfolio_syms
        prices: dict[str, float] = {}
        asset_classes: dict[str, AssetClass] = {
            p.instrument.symbol.upper(): p.instrument.asset_class for p in portfolio.positions
        }

        async def _px(sym: str) -> tuple[str, float, AssetClass]:
            # Registry miss: infer crypto from the exchange-style suffix so the
            # yfinance adapter's BTC-USD mapping still applies (same heuristic
            # family as exec.py).
            sym_up = sym.upper()
            asset_class = (
                AssetClass.CRYPTO
                if sym_up.endswith(("USDT", "USDC", "BUSD", "-USD")) and len(sym_up) > 4
                else AssetClass.EQUITY
            )
            try:
                inst = await asyncio.wait_for(
                    self.deps.symbol_registry.resolve(sym),
                    timeout=max(0.5, min(float(params.get("resolve_timeout", 1.5)), 2.0)),
                ) if self.deps.symbol_registry else None
                if not inst:
                    inst = Instrument(symbol=sym, asset_class=asset_class)
                asset_class = inst.asset_class
                # HNT-02: crypto is no longer skipped — the yfinance adapter's
                # `_yf_symbol` maps exchange pairs (BTCUSDT) to Yahoo's
                # "BTC-USD" spot form (same as PORT), so crypto targets and
                # positions can take a live mark too.
                src = self.deps.yfinance
                if src is None:
                    return sym, 0.0, asset_class
                q = await asyncio.wait_for(
                    src.fetch(DataRequest(kind=DataKind.QUOTE, instrument=inst)),
                    timeout=max(1.0, min(float(params.get("quote_timeout", 2.5)), 3.0)),
                )
                return sym, float(q.last or 0), asset_class
            except Exception:
                return sym, 0.0, asset_class
        for sym, px, asset_class in await asyncio.gather(*(_px(s) for s in all_syms)):
            prices[sym] = px
            asset_classes.setdefault(sym, asset_class)
        # REBA#3: a held position with no live quote used to be valued at
        # average cost, so the weights mixed cost with live marks and the
        # orders were sized against a wrong total. Withhold the preview
        # instead and name the unpriced positions. Zero-quantity rows carry
        # no exposure and do not block the preview.
        unpriced_held: dict[str, float] = {}
        for p in portfolio.positions:
            sym = p.instrument.symbol.upper()
            if abs(float(p.quantity or 0)) > 0 and not prices.get(sym):
                unpriced_held[sym] = unpriced_held.get(sym, 0.0) + float(p.quantity)
        if unpriced_held:
            names = ", ".join(sorted(unpriced_held))
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "rows": [],
                    "orders": [],
                    "liquidations": [],
                    "unpriced_positions": [
                        {"symbol": s, "quantity": q} for s, q in sorted(unpriced_held.items())
                    ],
                    "reason": (
                        f"No live quote for held position(s) {names}. Weights need "
                        "live marks for every holding, so no orders were computed."
                    ),
                    "next_actions": [
                        "Retry when the quote provider is reachable.",
                        "Or run the model mode (live_portfolio=false) against the supplied capital.",
                    ],
                },
                sources=["portfolio_state", "yfinance"],
                metadata={"live": True, "unpriced": True},
                warnings=[
                    f"REBA: no live quote for {names}; orders withheld rather than "
                    "valuing these positions at average cost."
                ],
            )
        # Total equity. An empty (or all-zero) book has no basis to rebalance
        # against — the old `or 1.0` silently produced $1-notional orders.
        cur_value: dict[str, float] = {}
        for p in portfolio.positions:
            sym = p.instrument.symbol.upper()
            px = prices.get(sym) or 0.0
            cur_value[sym] = cur_value.get(sym, 0) + p.quantity * px
        # REBA#4: the NAV is invested value plus USD cash. Targets are weights
        # of this NAV, so a "CASH" target keeps cash and any other target
        # deploys it.
        cash_usd, other_cash = _cash_balances(portfolio)
        total = sum(cur_value.values()) + cash_usd
        if total <= 0:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "ready_no_positions",
                    "rows": [],
                    "orders": [],
                    "liquidations": [],
                    "reason": (
                        "live_portfolio found no positions (or only zero-value "
                        "positions) to rebalance — nothing to compute orders against."
                    ),
                    "next_actions": [
                        (
                            "Add positions to the portfolio state, or run the model mode "
                            "(live_portfolio=false) against the supplied capital."
                        ),
                    ],
                },
                sources=["portfolio_state"],
                metadata={"live": True, "empty": True},
                warnings=["REBA: live portfolio is empty — no order preview."],
            )
        # REBA#4: max_notional is not a NAV cap. Live weights and targets use the
        # real NAV, so a client-supplied capital (the UI sends a default when the
        # field is blank) cannot shrink the account the orders are sized against.
        # A cap that would have bound is named in the warnings instead.
        cap = _positive_float(cash_cap)
        if cap is not None and cap < total:
            notes.append(
                f"REBA: max_notional {cap:,.2f} is below the live NAV of {total:,.2f} and is "
                "not applied; live targets use the full NAV. max_notional only sizes the model path."
            )
        cur_weights = {s: v / total for s, v in cur_value.items()}
        cash_weight = cash_usd / total
        warnings: list[str] = list(notes)
        if other_cash:
            named = ", ".join(f"{amt:,.2f} {ccy}" for ccy, amt in sorted(other_cash.items()))
            warnings.append(
                f"REBA: non-USD cash ({named}) is excluded from the NAV; REBA has no FX conversion."
            )
        target_keys = {str(k).upper() for k in targets}
        if cash_usd > 0 and "CASH" not in target_keys:
            warnings.append(
                f"REBA: targets are applied to NAV including {cash_usd:,.2f} USD cash, so this cash "
                "is deployed. Add a CASH target to keep part of it."
            )
        # Compute order list
        orders = []
        suppressed: list[dict[str, Any]] = []
        fractional_syms: set[str] = set()
        for sym, target_w in targets.items():
            sym = sym.upper()
            if sym == "CASH":
                # A cash target is a weight to keep, not an order.
                continue
            cur_w = cur_weights.get(sym, 0)
            drift = target_w - cur_w
            if abs(drift) < threshold:
                continue
            target_notional = target_w * total
            current_notional = cur_value.get(sym, 0)
            delta_notional = target_notional - current_notional
            px = prices.get(sym) or 0
            # HNT-02: px == 0 means "no quote available" — emit the row with
            # quantity=None + an explicit flag instead of a meaningless
            # "SELL 0" (or, pre-fix, a notional/1 unit count).
            qty = None
            if px:
                ac = asset_classes.get(sym)
                if lot_mode == "whole" and ac not in _WHOLE_LOT_CLASSES:
                    fractional_syms.add(sym)
                qty = _round_lot(delta_notional / px, ac, lot_mode)
                if qty == 0:
                    suppressed.append({
                        "symbol": sym, "reason": "below_lot", "notional_delta": delta_notional,
                    })
                    continue
                delta_notional = qty * px
            if abs(delta_notional) < min_trade:
                suppressed.append({
                    "symbol": sym, "reason": "below_min", "notional_delta": delta_notional,
                })
                continue
            orders.append({
                "symbol": sym,
                "action": "BUY" if (qty if qty is not None else drift) > 0 else "SELL",
                "quantity": abs(qty) if qty is not None else None,
                "price": px if px else None,
                "price_unavailable": not px,
                "notional_delta": delta_notional,
                "current_weight_pct": cur_w * 100,
                "target_weight_pct": target_w * 100,
                "drift_pct": drift * 100,
            })
        # Sells to fund buys; reverse-sort by |drift|
        orders.sort(key=lambda x: -abs(x["drift_pct"]))
        # Also flag positions to liquidate (in portfolio but not in targets)
        liquidations = []
        for sym in cur_weights:
            if sym not in (k.upper() for k in targets):
                # HNT-02: the old `prices.get(sym) or 1` divided the dollar
                # value by 1 and produced absurd unit counts (16250 "BTC").
                # No quote → quantity=None + "price unavailable" marker.
                px = prices.get(sym) or 0
                qty = cur_value[sym] / px if px else None
                liquidations.append({
                    "symbol": sym, "action": "SELL", "quantity": qty,
                    "price": px if px else None,
                    "price_unavailable": not px,
                    "notional_delta": -cur_value[sym],
                    "current_weight_pct": cur_weights[sym] * 100,
                    "target_weight_pct": 0,
                    "drift_pct": -cur_weights[sym] * 100,
                })
        if fractional_syms:
            warnings.append(
                "REBA: lot_rounding=whole applies to equities and ETFs; kept fractional for "
                + ", ".join(sorted(fractional_syms)) + "."
            )
        # Funding check: buys must be covered by USD cash plus sell proceeds.
        buys = sum(o["notional_delta"] for o in orders if o["notional_delta"] > 0)
        proceeds = -sum(o["notional_delta"] for o in orders + liquidations if o["notional_delta"] < 0)
        shortfall = buys - proceeds - max(cash_usd, 0.0)
        if shortfall > 1.0:
            warnings.append(
                f"REBA: buy orders need {shortfall:,.2f} more than USD cash plus sell proceeds."
            )
        current_weights = {k: v * 100 for k, v in cur_weights.items()}
        if cash_usd:
            current_weights["CASH"] = cash_weight * 100
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "total_value": total,
                "cash_usd": cash_usd,
                "cash_weight_pct": cash_weight * 100,
                "current_weights_pct": current_weights,
                "target_weights_pct": {k: v * 100 for k, v in targets.items()},
                "orders": orders,
                "liquidations": liquidations,
                "rows": orders + liquidations,
                "suppressed": suppressed,
                "summary": {
                    "n_orders": len(orders),
                    "n_liquidations": len(liquidations),
                    "n_suppressed": len(suppressed),
                    "gross_notional": sum(abs(o["notional_delta"]) for o in orders + liquidations),
                },
                "min_trade_size": min_trade,
                "lot_rounding": lot_mode,
                "execution": "preview_only",
                "methodology": _methodology(),
                "field_dictionary": _field_dictionary(),
            },
            sources=["portfolio_state", "yfinance"],
            warnings=warnings,
        )


_WHOLE_LOT_CLASSES = {AssetClass.EQUITY, AssetClass.ETF}
_LOT_MODES = ("whole", "fractional")


def _num_param(value: Any, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _lot_mode(value: Any) -> tuple[str, list[str]]:
    mode = str(value or "whole").strip().lower()
    if mode in _LOT_MODES:
        return mode, []
    return "whole", [
        f"REBA: lot_rounding '{value}' is not supported; using whole-share rounding "
        "for equities and ETFs."
    ]


def _round_lot(qty: float, asset_class: Any, mode: str) -> float:
    """Whole mode floors the size toward zero for whole-share instruments.
    Other asset classes (crypto, FX, ...) stay fractional."""
    if mode == "fractional" or asset_class not in _WHOLE_LOT_CLASSES:
        return qty
    return math.copysign(math.floor(abs(qty)), qty)


def _input_notes(params: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    paper = params.get("paper_mode")
    if paper not in (None, "") and not _truthy(paper):
        notes.append(
            "REBA: paper_mode=false has no effect; REBA only previews and never submits "
            "orders. Hand-off to EMSX is an explicit user step."
        )
    if str(params.get("credential_id") or "").strip():
        notes.append(
            "REBA: credential_id is accepted but not applied yet; live weights come from "
            "the local portfolio book."
        )
    return notes


def _cash_balances(portfolio: Any) -> tuple[float, dict[str, float]]:
    """USD cash for the NAV, plus any non-USD balances (not valued here)."""
    raw = getattr(portfolio, "cash", None) or {}
    usd = 0.0
    other: dict[str, float] = {}
    for ccy, amount in raw.items():
        try:
            value = float(amount)
        except (TypeError, ValueError):
            continue
        code = str(ccy).strip().upper()
        if code == "USD":
            usd += value
        elif value:
            other[code] = value
    return usd, other


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _rebalance_model(targets: dict[str, float], cash_cap: Any) -> dict[str, Any]:
    """Model mode: no current holdings are known, so no drift and no orders.

    REBA#5 / data policy: the old path invented current weights (target - 0.04),
    prices (100 + 25*idx) and a 100000 capital default. It now reports the
    normalized targets, and dollar targets only when the caller supplied the
    capital (max_notional). Returns an explicit needs_input state.
    """
    target_weights_pct = {k.upper(): v * 100 for k, v in targets.items()}
    capital = _positive_float(cash_cap)
    data: dict[str, Any] = {
        "status": "needs_input",
        "target_weights_pct": target_weights_pct,
        "orders": [],
        "liquidations": [],
        "rows": [],
        "suppressed": [],
        "summary": {
            "n_orders": 0,
            "n_liquidations": 0,
            "n_suppressed": 0,
            "gross_notional": 0.0,
        },
        "execution": "preview_only",
        "methodology": _methodology(),
        "field_dictionary": _field_dictionary(),
        "reason": (
            "Model mode has no current holdings, so drift and orders cannot be computed. "
            "Orders need the live portfolio book."
        ),
        "next_actions": [
            "Run with live_portfolio=true to size orders against the portfolio book.",
        ],
    }
    if capital is not None:
        data["total_value"] = capital
        data["target_notional"] = {
            k.upper(): v * capital for k, v in targets.items() if k.upper() != "CASH"
        }
        data["target_notional_note"] = "Target allocation of the supplied capital, not an order."
    else:
        data["next_actions"].append("Supply max_notional (capital) to see target dollar allocations.")
    return data


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _methodology() -> str:
    return (
        "Normalize target weights (a CASH target keeps cash), estimate current weights from position market "
        "values plus USD cash, then propose BUY/SELL deltas where target minus current weight exceeds the drift "
        "threshold. Trades below min_trade_size are suppressed; live whole-share lots are floored for equities "
        "and ETFs. Output is a preview, not an executed order."
    )


def _field_dictionary() -> dict[str, str]:
    return {
        "current_weight_pct": "Current portfolio weight for the symbol.",
        "target_weight_pct": "Desired portfolio weight after rebalance.",
        "drift_pct": "Target weight minus current weight.",
        "notional_delta": "Dollar buy/sell amount required to move toward target.",
        "quantity": "Estimated units based on the displayed price; null with price_unavailable=true when no live quote resolved.",
        "cash_usd": "USD cash balance included in total_value (the NAV the targets apply to).",
        "cash_weight_pct": "USD cash as a percent of total_value.",
    }
