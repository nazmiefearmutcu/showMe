"""ACCT — Multi-account portfolio aggregator.

Hesap (account) bazlı pozisyon dağılımı + per-account PORT view.
Hesaplar: 'main', 'paper', 'ibkr', 'alpaca', 'oanda', 'binance' vb.
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.portfolio.state import PortfolioState


@FunctionRegistry.register
class ACCTFunction(BaseFunction):
    code = "ACCT"
    name = "Multi-Account Aggregation"
    category = "portfolio"
    description = "Per-account position roll-up + cross-account exposure totals."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        portfolio = PortfolioState()
        portfolio.import_legacy_crypto()
        if not portfolio.positions:
            positions = params.get("positions") or []
            if not positions:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        "status": "ready_no_positions",
                        "accounts": [],
                        "cross": {"total_mv": 0.0, "by_asset_class": {}, "by_symbol": {}},
                        "rows": [],
                        "next_actions": [
                            "Add real positions through the portfolio state surface.",
                            "Or pass positions in Params JSON with symbol, asset_class, quantity, avg_cost, last, and account.",
                        ],
                    },
                    sources=["portfolio_state"],
                    metadata={"empty": True, "requires_positions": True},
                )
            # BUG-HUNT S01: previously user-supplied `positions` were
            # blindly cast through float(); a non-numeric quantity or
            # avg_cost bubbled as a 500 with no actionable error. Validate
            # each row + collect skipped entries into a warning so the
            # user can fix their Params JSON.
            accounts: dict[str, dict[str, Any]] = {}
            skipped: list[dict[str, Any]] = []
            if not isinstance(positions, list):
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        "status": "input_error",
                        "reason": "positions must be a JSON array of position objects.",
                        "rows": [],
                        "next_actions": [
                            "Pass positions=[{symbol, asset_class, quantity, avg_cost, last, account}, ...].",
                        ],
                    },
                    sources=[],
                )
            for idx, p in enumerate(positions):
                if not isinstance(p, dict) or not p.get("symbol"):
                    skipped.append({"index": idx, "reason": "missing dict or symbol"})
                    continue
                try:
                    qty = float(p.get("quantity", 0))
                    price = float(p.get("last", p.get("avg_cost", 0)))
                except (TypeError, ValueError):
                    skipped.append({"index": idx, "symbol": p.get("symbol"),
                                    "reason": "quantity/last/avg_cost not numeric"})
                    continue
                acct = p.get("account", "paper")
                mv = qty * price
                slot = accounts.setdefault(acct, {"account": acct, "positions": [],
                                                   "total_mv": 0.0, "n_positions": 0,
                                                   "by_asset_class": {}})
                slot["positions"].append({**p, "market_value": mv})
                slot["total_mv"] += mv
                slot["n_positions"] += 1
                ac = p.get("asset_class", "OTHER")
                slot["by_asset_class"][ac] = slot["by_asset_class"].get(ac, 0) + mv
            cross = {"total_mv": sum(a["total_mv"] for a in accounts.values()),
                     "by_asset_class": {}, "by_symbol": {}}
            for slot in accounts.values():
                for ac, mv in slot["by_asset_class"].items():
                    cross["by_asset_class"][ac] = cross["by_asset_class"].get(ac, 0) + mv
                for p in slot["positions"]:
                    cross["by_symbol"][p["symbol"]] = cross["by_symbol"].get(p["symbol"], 0) + p["market_value"]
            metadata: dict[str, Any] = {}
            if skipped:
                metadata["provider_errors"] = [
                    f"ACCT: skipped {len(skipped)} invalid position row(s)"
                ]
                metadata["skipped_positions"] = skipped
            return FunctionResult(code=self.code, instrument=None,
                                  data={"accounts": list(accounts.values()),
                                        "rows": [_account_row(slot) for slot in accounts.values()],
                                        "cross": cross,
                                        "methodology": _methodology(),
                                        "field_dictionary": _field_dictionary()},
                                  sources=["user_positions"],
                                  metadata=metadata)
        # Resolve last prices per symbol (single fetch each).
        symbols = {p.instrument.symbol: p for p in portfolio.positions}
        mark_timeout = _mark_timeout(params)
        async def _q(sym: str) -> tuple[str, float | None, str | None]:
            pos = symbols[sym]
            try:
                # HNT-16: crypto positions are quoted live too — the yfinance
                # adapter maps exchange pairs (BTCUSDT) to Yahoo's "BTC-USD"
                # spot form (the PORT pattern), so account totals agree with
                # the PORT pane instead of mixing live marks with stale
                # avg_cost. The position's own instrument is authoritative
                # for the asset class; the registry refines equities only.
                inst = pos.instrument
                if inst.asset_class != AssetClass.CRYPTO and self.deps.symbol_registry:
                    resolved = await self.deps.symbol_registry.resolve(sym)
                    if resolved:
                        inst = resolved
                if not self.deps.yfinance:
                    return sym, None, "no live quote provider is configured"
                quote = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(kind=DataKind.QUOTE, instrument=inst)),
                    timeout=mark_timeout,
                )
                last = getattr(quote, "last", None)
                if last is None or not float(last) > 0:
                    return sym, None, "quote returned no usable last price"
                return sym, float(last), None
            except asyncio.TimeoutError:
                return sym, None, f"quote timed out after {mark_timeout:g}s"
            except Exception as exc:
                return sym, None, f"quote failed ({type(exc).__name__})"
        # ACCT#1: a failed or timed-out quote is NOT marked at avg_cost. The
        # position stays visible with last / market_value / unrealized_pnl set
        # to None, a warning names the symbol, and totals exclude it.
        results = await asyncio.gather(*(_q(s) for s in symbols.keys()))
        prices: dict[str, float | None] = {sym: px for sym, px, _ in results}
        price_errors: dict[str, str] = {sym: err for sym, _, err in results if err}
        # Group by account
        by_account: dict[str, dict[str, Any]] = {}
        for p in portfolio.positions:
            acct = p.account or "main"
            slot = by_account.setdefault(acct, {
                "account": acct, "positions": [], "total_mv": 0.0,
                "total_unrealized_pnl": 0.0, "n_positions": 0,
                "unpriced_positions": 0,
                "by_asset_class": {},
            })
            sym = p.instrument.symbol
            px = prices.get(sym)
            priced = px is not None
            mv = p.quantity * px if priced else None
            unrl = (px - p.avg_cost) * p.quantity if priced else None
            ac = p.instrument.asset_class.value
            slot["positions"].append({
                "symbol": sym, "asset_class": ac,
                "quantity": p.quantity, "avg_cost": p.avg_cost,
                "last": px, "market_value": mv, "unrealized_pnl": unrl,
                "currency": p.currency,
                "priced": priced,
                "quote_error": price_errors.get(sym) if not priced else None,
            })
            slot["n_positions"] += 1
            if not priced:
                slot["unpriced_positions"] += 1
                continue
            slot["total_mv"] += mv
            slot["total_unrealized_pnl"] += unrl
            slot["by_asset_class"][ac] = slot["by_asset_class"].get(ac, 0) + mv
        # Cross-account exposure (priced positions only)
        cross = {"by_asset_class": {}, "by_symbol": {}, "total_mv": 0.0,
                 "unpriced_symbols": sorted(sym for sym, err in price_errors.items() if err)}
        for slot in by_account.values():
            for ac, mv in slot["by_asset_class"].items():
                cross["by_asset_class"][ac] = cross["by_asset_class"].get(ac, 0) + mv
            for pos in slot["positions"]:
                if not pos["priced"]:
                    continue
                cross["by_symbol"][pos["symbol"]] = (
                    cross["by_symbol"].get(pos["symbol"], 0) + pos["market_value"]
                )
            cross["total_mv"] += slot["total_mv"]
        unpriced_total = sum(slot["unpriced_positions"] for slot in by_account.values())
        metadata: dict[str, Any] = {"mark_timeout_s": mark_timeout}
        warnings: list[str] = []
        for sym in cross["unpriced_symbols"]:
            warnings.append(
                f"ACCT: no live mark for {sym} ({price_errors[sym]}); its market value and "
                "unrealized P&L are unavailable and it is excluded from totals. It is not valued at cost."
            )
        if price_errors:
            metadata["provider_errors"] = [f"ACCT: {sym}: {err}" for sym, err in sorted(price_errors.items())]
            metadata["stale_marks"] = sorted(price_errors)
        return FunctionResult(
            code=self.code, instrument=None,
            data={"status": "partial" if unpriced_total else "ok",
                  "accounts": list(by_account.values()),
                  "rows": [_account_row(slot) for slot in by_account.values()],
                  "cross": cross,
                  "summary": {
                      "accounts": len(by_account),
                      "positions": sum(slot["n_positions"] for slot in by_account.values()),
                      "total_market_value": cross["total_mv"],
                      "unpriced_positions": unpriced_total,
                      "total_market_value_complete": unpriced_total == 0,
                  },
                  "methodology": _methodology(),
                  "field_dictionary": _field_dictionary()},
            sources=["yfinance"],
            warnings=warnings,
            metadata=metadata,
        )


# ACCT#1: the router injects quote_timeout=3 for every routed call, which is
# shorter than a yfinance fast_info round trip under load and made every slow
# mark fall back to cost. Portfolio marks get a floor of 8 s, capped at 12 s
# (the function timeout is 14 s).
MARK_TIMEOUT_FLOOR_S = 8.0
MARK_TIMEOUT_CEIL_S = 12.0


def _mark_timeout(params: dict[str, Any]) -> float:
    raw = params.get("mark_timeout", params.get("quote_timeout"))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = MARK_TIMEOUT_FLOOR_S
    return min(max(value, MARK_TIMEOUT_FLOOR_S), MARK_TIMEOUT_CEIL_S)


def _account_row(slot: dict[str, Any]) -> dict[str, Any]:
    return {
        "account": slot.get("account"),
        "positions": slot.get("n_positions"),
        "market_value": slot.get("total_mv"),
        "unrealized_pnl": slot.get("total_unrealized_pnl"),
        "unpriced_positions": slot.get("unpriced_positions", 0),
        "top_asset_class": _top_key(slot.get("by_asset_class") or {}),
    }


def _top_key(values: dict[str, float]) -> str | None:
    if not values:
        return None
    return max(values.items(), key=lambda item: abs(float(item[1] or 0)))[0]


def _methodology() -> str:
    return (
        "Group saved or supplied positions by account, mark each position with the latest available price, "
        "then aggregate market value, unrealized P&L, asset-class exposure, and symbol exposure across accounts."
    )


def _field_dictionary() -> dict[str, str]:
    return {
        "market_value": (
            "Position quantity multiplied by the live last price. Null when no live mark is available; "
            "such positions are never valued at average cost and are excluded from totals."
        ),
        "unrealized_pnl": "(live last price - average cost) * quantity. Null when unpriced.",
        "unpriced_positions": "Positions with no live mark, excluded from market value totals.",
        "top_asset_class": "Largest asset-class exposure for the account.",
        "cross": "Cross-account aggregate exposure by asset class and symbol.",
    }
