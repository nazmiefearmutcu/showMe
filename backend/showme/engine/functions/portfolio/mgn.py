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
                        # Only a caller-chosen type is explicit; otherwise it is inferred.
                        "inferred": not params.get("margin_type"),
                    }
                }
            }
            account = margin_engine.calc_account("paper", positions, cfg=cfg)
            at_cost = sorted({
                str(p.get("symbol") or "?") for p in positions
                if not isinstance(p, dict) or not _positive_number(p.get("last"))
            })
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
                warnings=([f"Marked at average cost (no 'last' price supplied): {', '.join(at_cost)}."]
                          if at_cost else [])
                + ([] if "cash" in params else _cash_warnings({"paper": "none"}, 0.0)),
                # MGN#1: same rule as the saved-book branch; an at-cost line makes the book degraded.
                metadata={"live": False, "positions_source": "supplied", "marked_at_cost": at_cost,
                          "degraded": bool(at_cost)},
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
        cash_overrides, cash_warnings = _request_cash(params, sorted({p.account or "main" for p in portfolio.positions}))
        result = margin_engine.calc_all_accounts(
            prices=prices,
            include_legacy=bool(params.get("include_legacy") or params.get("legacy")),
            cash_overrides=cash_overrides,
        )
        accounts = result.get("accounts", []) if isinstance(result, dict) else []
        warnings: list[str] = []
        if at_cost:
            why = "no live quote" if refresh else "refresh_prices=false"
            warnings.append(f"Marked at average cost ({why}): {', '.join(at_cost)}.")
        warnings.extend(cash_warnings)
        cash_sources = result.get("cash_sources", {}) if isinstance(result, dict) else {}
        unallocated = float(result.get("unallocated_cash_usd", 0) or 0) if isinstance(result, dict) else 0.0
        warnings.extend(_cash_warnings(cash_sources, unallocated))
        sources = ["portfolio_state", "margin_engine"] + (["yfinance"] if prices else [])
        # MGN#1: a book with any position marked at average cost is partial-live, not live.
        # `degraded` makes the pane show a data-quality badge; `live` is deliberately not
        # set to false (that reads as a model in the pane).
        return FunctionResult(code=self.code, instrument=None,
                              data={**result,
                                    "rows": [_account_row(account) for account in accounts],
                                    "marked_at_cost": at_cost,
                                    "methodology": _methodology(),
                                    "field_dictionary": _field_dictionary()},
                              sources=sources,
                              warnings=warnings,
                              metadata={"positions_source": "portfolio",
                                        "marked_at_cost": at_cost,
                                        "degraded": bool(at_cost),
                                        "cash_sources": cash_sources,
                                        "unallocated_cash_usd": unallocated})

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


def _request_cash(params: dict[str, Any], account_names: list[str]) -> tuple[dict[str, float], list[str]]:
    """MGN#5: cash stated in the request, for one account and this calculation only.

    With ``account`` it applies to that account; without it, it applies only when the book
    has one account. With several accounts and no ``account`` it is not guessed onto one.
    """
    raw = params.get("cash")
    if raw is None or str(raw).strip() == "":
        return {}, []
    try:
        amount = float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return {}, [f"Cash '{raw}' is not a number and was not applied."]
    account = str(params.get("account") or "").strip()
    if account:
        if account in account_names:
            return {account: amount}, []
        return {}, [f"Cash not applied: the book has no account named '{account}'."]
    if len(account_names) == 1:
        return {account_names[0]: amount}, []
    return {}, ["Cash not applied: the book has several accounts, so pass account=<name> to say which one holds this cash."]


def _cash_warnings(cash_sources: dict[str, str], unallocated_usd: float) -> list[str]:
    """MGN#5: say plainly when equity leaves cash out (cash is not recorded)."""
    out = [
        f"Cash not recorded for account '{name}': equity equals market value and buying "
        "power excludes cash. Pass cash=... or record it with action=upsert."
        for name, source in sorted(cash_sources.items()) if source == "none"
    ]
    if unallocated_usd:
        out.append(
            f"USD cash {unallocated_usd:,.2f} in the book is unallocated: it has several accounts "
            "and cash is not recorded per account, so no account was credited with it."
        )
    return out


def _positive_number(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _margin_type_for_positions(positions: list[dict[str, Any]]) -> str:
    # Account type only; each position is still margined under its own class rule
    # inside margin_engine.calc_account (a CRYPTO line no longer reprices equities).
    return margin_engine.infer_margin_type(positions)


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
    # MGN#4/MGN#6: a model estimate, not a broker figure; the multipliers are named constants.
    return (
        "Group positions by account, mark positions with supplied or fetched prices, then apply the "
        "account margin model to estimate initial margin, maintenance margin, excess equity, and buying power. "
        "These are model estimates, not broker margin figures. Portfolio-margin accounts use "
        f"maintenance scale {margin_engine.PORTFOLIO_MAINTENANCE_SCALE} and buying-power multiple "
        f"{margin_engine.PORTFOLIO_BUYING_POWER_MULTIPLE}."
    )


def _field_dictionary() -> dict[str, str]:
    return {
        "initial_margin": "Capital required to open or carry the positions under the selected model.",
        "maintenance_margin": "Minimum equity requirement before a margin call/liquidation risk.",
        "buying_power": "Approximate additional notional capacity after margin requirements.",
        "maintenance_cushion_pct": "Equity cushion above maintenance margin divided by equity.",
    }
