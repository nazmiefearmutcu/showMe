"""MGN — Cross-account margin / buying power."""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.services import margin_engine


@FunctionRegistry.register
class MGNFunction(BaseFunction):
    code = "MGN"
    name = "Cross-Account Margin"
    category = "portfolio"
    description = "Margin requirements + buying power per account."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = (params.get("action") or "calc").lower()
        if action == "list":
            return FunctionResult(code=self.code, instrument=None,
                                  data={"accounts": margin_engine.list_accounts()})
        if action == "upsert":
            # HNT-08: a missing `name` used to raise KeyError and surface as
            # a raw exception envelope; EXEC's _missing_fields contract
            # (exec.py) returns a clean input_error instead.
            name = str(params.get("name") or "").strip()
            if not name:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        "status": "input_error",
                        "reason": "MGN upsert requires a non-empty 'name'.",
                        "missing_fields": ["name"],
                        "rows": [],
                    },
                    sources=["margin_engine"],
                    metadata={"error": True, "status": "input_error"},
                )
            info = margin_engine.upsert_account(
                name=name,
                margin_type=params.get("margin_type", "reg_t"),
                cash=float(params.get("cash", 0)),
                currency=params.get("currency", "USD"),
                overrides=params.get("overrides") or {},
            )
            return FunctionResult(code=self.code, instrument=None,
                                  data={"account": name, **info})
        if action == "delete":
            name = str(params.get("name") or "").strip()
            if not name:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        "status": "input_error",
                        "reason": "MGN delete requires a non-empty 'name'.",
                        "missing_fields": ["name"],
                        "rows": [],
                    },
                    sources=["margin_engine"],
                    metadata={"error": True, "status": "input_error"},
                )
            ok = margin_engine.delete_account(name)
            return FunctionResult(code=self.code, instrument=None,
                                  data={"deleted": ok, "name": name})
        # default: calc
        # 2026-11-07 (strict truth audit): no more illustrative SAMPLE book
        # (0.25 BTC @ 65,000 with 10,000 cash). Margin is computed for the
        # positions the caller supplies, otherwise for the saved portfolio
        # marked to live quotes; an empty book is an honest empty state.
        supplied_positions = params.get("positions")
        if supplied_positions:
            positions = supplied_positions
            cfg = {
                "accounts": {
                    "paper": {
                        "margin_type": params.get("margin_type") or _margin_type_for_positions(positions),
                        "cash": float(params.get("cash", 0) or 0),
                        "currency": params.get("currency", "USD"),
                        "overrides": params.get("overrides") or {},
                    }
                }
            }
            account = margin_engine.calc_account("paper", positions, cfg=cfg)
            total = {
                "equity": account["equity"],
                "initial_margin": account["initial_margin"],
                "maintenance_margin": account["maintenance_margin"],
                "buying_power": account["buying_power"],
                "excess_initial": account["excess_initial"],
                "maintenance_cushion_pct": account["maintenance_cushion_pct"],
            }
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "accounts": [account],
                    "rows": [_account_row(account)],
                    "total": total,
                    "methodology": _methodology(),
                    "field_dictionary": _field_dictionary(),
                },
                sources=["margin_engine"],
                metadata={"live": False, "positions_source": "supplied"},
            )

        from showme.engine.portfolio.state import PortfolioState
        portfolio = PortfolioState()
        if not portfolio.positions:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "empty",
                    "reason": "The local portfolio has no positions, so there is no margin to compute.",
                    "next_actions": [
                        "Add positions in PORT, or pass positions=[...] with quantity, avg_cost and last.",
                    ],
                    "accounts": [],
                    "rows": [],
                    "methodology": _methodology(),
                    "field_dictionary": _field_dictionary(),
                },
                sources=["portfolio_state"],
            )
        refresh = params.get("refresh_prices", params.get("live_prices", True))
        refresh = refresh if isinstance(refresh, bool) else str(refresh).strip().lower() in {"1", "true", "yes", "on"}
        symbols = [p.instrument.symbol for p in portfolio.positions]
        prices = await self._quote_many(symbols) if refresh else {}
        at_cost = sorted({s for s in symbols if s not in prices})
        result = margin_engine.calc_all_accounts(
            prices=prices,
            include_legacy=bool(params.get("include_legacy") or params.get("legacy")),
        )
        accounts = result.get("accounts", []) if isinstance(result, dict) else []
        warnings: list[str] = []
        if at_cost:
            why = "no live quote" if refresh else "refresh_prices=false"
            warnings.append(f"Marked at average cost ({why}): {', '.join(at_cost)}.")
        sources = ["portfolio_state", "margin_engine"] + (["yfinance"] if prices else [])
        return FunctionResult(code=self.code, instrument=None,
                              data={**result,
                                    "rows": [_account_row(account) for account in accounts],
                                    "marked_at_cost": at_cost,
                                    "methodology": _methodology(),
                                    "field_dictionary": _field_dictionary()},
                              sources=sources,
                              warnings=warnings)

    async def _quote_many(self, symbols: list[str]) -> dict[str, float]:
        """Live last prices; symbols without a positive quote are left out."""
        if not self.deps.yfinance or not symbols:
            return {}

        async def _q(sym: str) -> tuple[str, float | None]:
            try:
                inst = Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
                if self.deps.symbol_registry:
                    r = await self.deps.symbol_registry.resolve(sym)
                    if r:
                        inst = r
                quote = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.QUOTE, instrument=inst))
                last = float(quote.last) if quote is not None and quote.last else None
                return sym, last if last and last > 0 else None
            except Exception:  # noqa: BLE001 - reported as marked-at-cost
                return sym, None
        results = await asyncio.gather(*(_q(s) for s in symbols))
        return {sym: px for sym, px in results if px is not None}


def _margin_type_for_positions(positions: list[dict[str, Any]]) -> str:
    classes = {str(p.get("asset_class") or "").upper() for p in positions}
    if classes & {"FX"}:
        return "fx"
    if classes & {"COMMODITY", "DERIVATIVE"}:
        return "futures"
    if classes & {"CRYPTO"}:
        return "crypto_futures"
    return "reg_t"


def _account_row(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "account": account.get("account"),
        "margin_type": account.get("margin_type"),
        "cash": account.get("cash"),
        "market_value": account.get("market_value"),
        "equity": account.get("equity"),
        "initial_margin": account.get("initial_margin"),
        "maintenance_margin": account.get("maintenance_margin"),
        "buying_power": account.get("buying_power"),
        "maintenance_cushion_pct": account.get("maintenance_cushion_pct"),
        "positions": len(account.get("positions") or []),
    }


def _methodology() -> str:
    return (
        "Group positions by account, mark positions with supplied or fetched prices, then apply the "
        "account margin model to estimate initial margin, maintenance margin, excess equity, and buying power."
    )


def _field_dictionary() -> dict[str, str]:
    return {
        "initial_margin": "Capital required to open or carry the positions under the selected model.",
        "maintenance_margin": "Minimum equity requirement before a margin call/liquidation risk.",
        "buying_power": "Approximate additional notional capacity after margin requirements.",
        "maintenance_cushion_pct": "Equity cushion above maintenance margin divided by equity.",
    }
