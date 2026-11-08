"""PORT — Comprehensive Portfolio Analytics."""

from __future__ import annotations

import asyncio
import math
import re
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_function import BaseFunction, FunctionDeps, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.portfolio.state import PortfolioState

# Mirror of ``portfolio_aggregate._STABLE_TO_USD``: only stable-USD cash may be
# summed into the USD ``totals.cash`` figure. Anything else stays in the
# per-currency map so the terminal never converts by assumption.
_STABLE_USD_CURRENCIES = {"USD", "USDT", "USDC", "DAI", "BUSD", "TUSD"}
_GROUP_BY_OPTIONS = ("account", "asset_class", "sector", "currency", "none")
_CCY_RE = re.compile(r"^[A-Z]{3}$")
_DATA_STATE_BY_PRICE_STATE = {
    "live": "live",
    "partial": "partial",
    "legacy_snapshot": "reference",
    "unavailable": "unavailable",
}


def _cash_totals(cash: Any) -> tuple[float | None, dict[str, float]]:
    """Return ``(stable_usd_cash | None, per_currency_cash)``.

    ``None`` means the book does not track cash at all — the pane renders the
    shared em-dash instead of a confident $0.00 (audit A5 PORT H).
    """
    if not isinstance(cash, dict):
        return None, {}
    per_currency: dict[str, float] = {}
    for ccy, amount in cash.items():
        if isinstance(amount, bool):
            continue
        try:
            value = float(amount)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        per_currency[str(ccy).upper()] = value
    if not per_currency:
        return None, {}
    stable = sum(v for k, v in per_currency.items() if k in _STABLE_USD_CURRENCIES)
    return stable, per_currency


def _cash_fields(cash_usd: float | None, cash_by_currency: dict[str, float],
                 cash_total_base: float | None = None) -> dict[str, Any]:
    """``cash`` is stable-USD cash in base ccy; ``cash_total_base`` adds every
    balance converted to base ccy and is ``None`` when any balance has no rate."""
    out: dict[str, Any] = {}
    if cash_usd is not None:
        out["cash"] = cash_usd
        out["cash_total_base"] = cash_total_base
    if cash_by_currency:
        out["cash_by_currency"] = cash_by_currency
    return out


async def _foreign_cash_base(deps: FunctionDeps, cash_by_currency: dict[str, float],
                             ccy: str) -> tuple[float | None, list[str]]:
    """Non-stable cash converted to ``ccy``; ``None`` plus a warning when a rate is missing.

    A balance is never dropped silently: an unconvertible one makes the total
    unknown rather than understated.
    """
    total = 0.0
    missing: list[str] = []
    for code, amount in cash_by_currency.items():
        if code in _STABLE_USD_CURRENCIES or amount == 0:
            continue
        rate = await _fx_rate(deps, code, ccy)
        if rate is None:
            missing.append(code)
        else:
            total += amount * rate
    if missing:
        return None, [
            f"cash in {', '.join(missing)} not converted to {ccy}: no FX rate; "
            "total_equity withheld"
        ]
    return total, []


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_positive(value: Any) -> float | None:
    """A usable price: finite and strictly positive, otherwise ``None``."""
    number = _finite_number(value)
    return number if number is not None and number > 0 else None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _fx_key(currency: Any) -> str:
    """Currency used for FX lookups: stable-USD tokens count as USD."""
    code = str(currency or "USD").strip().upper()
    return "USD" if code in _STABLE_USD_CURRENCIES else code


def _parse_accounts(raw: Any) -> set[str] | None:
    """``None`` means every account; otherwise the upper-cased account names."""
    if raw is None:
        return None
    items = raw if isinstance(raw, (list, tuple, set)) else str(raw).split(",")
    names = {str(item).strip().upper() for item in items if str(item).strip()}
    if not names or "ALL" in names:
        return None
    return names


def _as_of_state(raw: Any) -> str:
    """``live`` (default), ``historical`` or ``invalid`` for the As-of input."""
    text = str(raw or "").strip()
    if text.lower() in {"", "live", "today", "now"}:
        return "live"
    try:
        day = datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return "invalid"
    return "live" if day == datetime.now(timezone.utc).date() else "historical"


async def _fx_rate(deps: FunctionDeps, currency: str, base: str) -> float | None:
    """Units of ``base`` per one unit of ``currency``; ``None`` when unavailable.

    The rate comes from the quote adapter (Yahoo ``EURUSD=X`` style pair). A
    missing rate is reported as ``None`` and never assumed to be 1.
    """
    src, dst = _fx_key(currency), _fx_key(base)
    if src == dst:
        return 1.0
    if deps.yfinance is None:
        return None
    try:
        from showme.engine.core.base_data_source import DataKind, DataRequest
        pair = Instrument(symbol=f"{src}{dst}", asset_class=AssetClass.FX,
                          exchange="FX", currency=dst)
        q = await deps.yfinance.fetch(DataRequest(kind=DataKind.QUOTE, instrument=pair))
        return _finite_positive(getattr(q, "last", None))
    except Exception:
        return None


def _input_error(reason: str, next_actions: list[str]) -> FunctionResult:
    return FunctionResult(
        code="PORT",
        instrument=None,
        data={"status": "input_error", "reason": reason, "positions": [], "groups": [],
              "next_actions": next_actions},
        sources=["portfolio_state"],
        metadata={"input_error": True},
    )


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


async def _supplied_rows_result(deps: FunctionDeps, rows: list[dict[str, Any]], ccy: str,
                                accounts: set[str] | None, show_zero: bool,
                                cash_base: float | None, cash_total_base: float | None,
                                cash_by_currency: dict[str, float],
                                cash_warnings: list[str], group_by: str) -> FunctionResult:
    """Value the positions passed in params when the book itself is empty.

    Same rules as the book path: each row is converted to ``ccy`` with its own
    FX rate, the account and zero-quantity filters apply, a row without a
    usable last price is unpriced (it is never marked at its cost basis), and
    the declared ``group_by`` roll-up is computed exactly as on the book path.
    """
    warnings: list[str] = list(cash_warnings)
    fx_rates: dict[str, float | None] = {}
    out_rows: list[dict[str, Any]] = []
    total_mv = 0.0
    total_cost = 0.0
    total_unrl = 0.0
    n_unpriced = 0
    by_class: dict[str, float] = {}
    for row in rows:
        qty = float(row["quantity"])
        if not show_zero and qty == 0:
            continue
        account = str(row.get("account") or "main")
        if accounts is not None and account.upper() not in accounts:
            continue
        sym = str(row.get("symbol") or "")
        currency = _fx_key(row.get("currency"))
        if currency not in fx_rates:
            fx_rates[currency] = await _fx_rate(deps, currency, ccy)
        rate = fx_rates[currency]
        avg = float(row["avg_cost"])
        last = _finite_positive(row.get("last"))
        asset_class = (_optional_text(row.get("asset_class")) or "").lower() or None
        out: dict[str, Any] = {
            **row,
            "symbol": sym,
            "account": account,
            "asset_class": asset_class,
            "sector": _optional_text(row.get("sector")),
            "currency": currency,
            "quantity": qty,
            "avg_cost": avg,
            "last": last,
            "price_source": "supplied" if last is not None else "missing",
            "quote_missing": last is None,
            "fx_rate": rate,
            "market_value": None,
            "unrealized_pnl": None,
            "weight_pct": None,
        }
        out_rows.append(out)
        if rate is None:
            n_unpriced += 1
            warnings.append(f"{sym}: no {currency}{ccy} FX rate; excluded from {ccy} totals")
            continue
        total_cost += avg * qty * rate
        if last is None:
            n_unpriced += 1
            warnings.append(f"{sym}: no last price supplied; excluded from market value and P&L")
            continue
        mv = qty * last * rate
        unrl = (last - avg) * qty * rate
        out["market_value"] = mv
        out["unrealized_pnl"] = unrl
        total_mv += mv
        total_unrl += unrl
        class_key = asset_class or "unclassified"
        by_class[class_key] = by_class.get(class_key, 0.0) + mv
    for out in out_rows:
        if out["market_value"] is not None and total_mv:
            out["weight_pct"] = out["market_value"] / total_mv * 100
    groups = _groups(out_rows, group_by, total_mv, warnings) if group_by != "none" else []
    n_rows = len(out_rows)
    if n_rows:
        warnings.append("day P&L unavailable: supplied rows carry no previous close")
    total_equity = (
        total_mv + cash_total_base
        if cash_total_base is not None and n_unpriced == 0
        else None
    )
    used_sources = ["user_positions"]
    if any(rate is not None and rate != 1.0 for rate in fx_rates.values()):
        used_sources.append("yfinance")
    return FunctionResult(
        code="PORT", instrument=None,
        data={
            "positions": out_rows,
            "ccy": ccy,
            "group_by": group_by,
            "fx_rates": dict(fx_rates),
            "groups": groups,
            "totals": {
                "market_value": total_mv,
                "cost_basis": total_cost,
                "unrealized_pnl": total_unrl,
                "n_positions": n_rows,
                "n_unpriced": n_unpriced,
                "total_equity": total_equity,
                "day_pnl": None,
                **_cash_fields(cash_base, cash_by_currency, cash_total_base),
            },
            "by_asset_class": by_class,
        },
        metadata={"data_state": "user_supplied" if n_rows else "empty"},
        sources=sorted(used_sources),
        warnings=warnings,
    )


def historical_var(returns: pd.Series, alpha: float = 0.05) -> float:
    """Historical VaR as a POSITIVE LOSS (audit Q3 #13).

    Returns the alpha-quantile loss: a value of 0.025 means a 2.5%
    worst-case loss at the chosen confidence. Callers that prefer the
    signed-return convention can pass ``signed=True``.
    """
    if returns.empty:
        return 0.0
    quantile = float(np.percentile(returns, alpha * 100))
    return -quantile if quantile < 0 else 0.0


def parametric_var(returns: pd.Series, alpha: float = 0.05) -> float:
    """Parametric VaR as a positive loss (audit Q3 #13)."""
    if returns.empty:
        return 0.0
    try:
        from scipy.stats import norm  # type: ignore
        z = float(norm.ppf(alpha))
    except Exception:
        # Use the same Acklam approximation as pvar._norm_ppf.
        from showme.engine.functions.portfolio.pvar import _norm_ppf
        z = float(_norm_ppf(alpha))
    mu = float(returns.mean())
    sigma = float(returns.std())
    signed = mu + sigma * z
    return -signed if signed < 0 else 0.0


def expected_tail_loss(returns: pd.Series, alpha: float = 0.05) -> float:
    """ETL/CVaR as a positive loss (audit Q3 #13)."""
    if returns.empty:
        return 0.0
    # Compute the alpha-quantile in signed-return space, then flip sign.
    threshold = float(np.percentile(returns, alpha * 100))
    tail = returns[returns <= threshold]
    if tail.empty:
        return -threshold if threshold < 0 else 0.0
    mean_tail = float(tail.mean())
    return -mean_tail if mean_tail < 0 else 0.0


@FunctionRegistry.register
class PORTFunction(BaseFunction):
    code = "PORT"
    name = "Portfolio Analytics"
    category = "portfolio"
    description = (
        "Local portfolio book: positions, cost basis, unrealized P&L, cash and "
        "weights, with live quote marks when a quote source answers."
    )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # Declared inputs (port_seed.py) are validated first so a bad value is
        # reported instead of silently ignored.
        raw_ccy = params.get("ccy")
        ccy = "USD" if raw_ccy in (None, "") else str(raw_ccy).strip().upper()
        if not _CCY_RE.match(ccy):
            return _input_error(f"Base currency {raw_ccy!r} is not a three-letter ISO code.",
                                ["Pick a base currency from the list (USD, EUR, GBP, TRY, JPY)."])
        raw_group = params.get("group_by")
        group_by = "asset_class" if raw_group in (None, "") else str(raw_group).strip().lower()
        if group_by not in _GROUP_BY_OPTIONS:
            return _input_error(f"Group by {raw_group!r} is not supported.",
                                [f"Use one of: {', '.join(_GROUP_BY_OPTIONS)}."])
        as_of_state = _as_of_state(params.get("as_of"))
        if as_of_state == "invalid":
            return _input_error(f"As of {params.get('as_of')!r} is not a date.",
                                ["Leave As of empty for the live book, or enter a YYYY-MM-DD date."])
        if as_of_state == "historical":
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "Historical book snapshots are not stored, so PORT cannot "
                              "reconstruct the book as of that date.",
                    "as_of": str(params.get("as_of")),
                    "positions": [],
                    "groups": [],
                    "next_actions": ["Clear As of to view the live book."],
                },
                sources=[],
                metadata={"as_of": str(params.get("as_of")), "live": False},
            )
        accounts = _parse_accounts(params.get("accounts"))
        show_zero = _truthy(params.get("show_zero"))

        portfolio: PortfolioState = params.get("_portfolio_override") or PortfolioState()
        if params.get("_portfolio_override") is None:
            portfolio.import_legacy_crypto()
        cash_usd, cash_by_currency = _cash_totals(getattr(portfolio, "cash", None))
        # Cash is tracked in USD-stable tokens; convert it to the base currency.
        cash_base: float | None = cash_usd
        cash_warnings: list[str] = []
        if cash_usd is not None and _fx_key(ccy) != "USD":
            cash_rate = await _fx_rate(self.deps, "USD", ccy)
            if cash_rate is None:
                cash_base = None
                cash_warnings.append(f"cash not converted to {ccy}: no USD{ccy} FX rate")
            else:
                cash_base = cash_usd * cash_rate
        # Non-stable balances (e.g. TRY) are converted too, so total_equity never
        # silently leaves them out; an unconvertible balance withholds the total.
        foreign_cash_base, foreign_warnings = await _foreign_cash_base(
            self.deps, cash_by_currency, ccy
        )
        cash_warnings.extend(foreign_warnings)
        cash_total_base: float | None = (
            None if cash_base is None or foreign_cash_base is None
            else cash_base + foreign_cash_base
        )
        if not portfolio.positions:
            rows = params.get("positions") or []
            if not rows:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        "status": "ready_no_positions",
                        "connected_exchanges": 0,
                        "positions": [],
                        "groups": [],
                        "ccy": ccy,
                        "totals": {
                            "market_value": 0.0,
                            "cost_basis": 0.0,
                            "n_positions": 0,
                            "unrealized_pnl": 0.0,
                            **_cash_fields(cash_base, cash_by_currency, cash_total_base),
                        },
                        "by_asset_class": {},
                        "next_actions": [
                            "Add real positions through the portfolio state surface.",
                            "Or pass positions in Params JSON with symbol, asset_class, quantity, avg_cost, and last.",
                        ],
                    },
                    sources=["portfolio_state"],
                    metadata={"empty": True, "requires_positions": True},
                    warnings=cash_warnings,
                )
            return await _supplied_rows_result(self.deps, rows, ccy, accounts, show_zero,
                                               cash_base, cash_total_base, cash_by_currency,
                                               cash_warnings, group_by)

        # The book's own filters: zero-quantity history and the account selection.
        positions = [
            pos for pos in portfolio.positions
            if (show_zero or float(pos.quantity) != 0)
            and (accounts is None or str(pos.account or "main").upper() in accounts)
        ]

        # Live marks come from the quote adapter. A position with no live quote
        # falls back to a recorded legacy snapshot price (reported as such); a
        # position with neither is reported as unpriced and is never marked at
        # its cost basis.
        used_sources = {"portfolio_state"}

        async def _quote(pos: Any) -> tuple[float | None, str, float | None]:
            if self.deps.yfinance:
                try:
                    from showme.engine.core.base_data_source import DataKind, DataRequest
                    q = await self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.QUOTE, instrument=pos.instrument
                    ))
                    last = _finite_positive(getattr(q, "last", None))
                    if last is not None:
                        return last, "yfinance", _finite_positive(getattr(q, "close_prev", None))
                except Exception:
                    pass
            legacy = _legacy_last_price(pos)
            if legacy is not None:
                return legacy, "legacy_snapshot", None
            return None, "missing", None

        # HNT-05: fetch quotes concurrently (ACCT's `_q` pattern). A
        # sequential per-position fetch easily blew the 14 s worker budget
        # on mid-sized books with a slow network.
        quotes = await asyncio.gather(*(_quote(pos) for pos in positions))
        fx_rates: dict[str, float | None] = {}
        for pos in positions:
            key = _fx_key(pos.currency)
            if key not in fx_rates:
                fx_rates[key] = await _fx_rate(self.deps, key, ccy)

        rows: list[dict[str, Any]] = []
        warnings: list[str] = list(cash_warnings)
        price_sources = {"yfinance": 0, "legacy_snapshot": 0, "missing": 0}
        priced_mv = 0.0
        priced_unrl = 0.0
        day_total = 0.0
        day_missing: list[str] = []
        total_cost = 0.0
        by_class: dict[str, float] = {}
        for pos, (last, price_source, prev_close) in zip(positions, quotes):
            sym = pos.instrument.symbol
            qty = float(pos.quantity)
            avg = float(pos.avg_cost)
            rate = fx_rates[_fx_key(pos.currency)]
            price_sources[price_source] += 1
            if price_source == "yfinance":
                used_sources.add("yfinance")
            row: dict[str, Any] = {
                "symbol": sym,
                "asset_class": pos.instrument.asset_class.value,
                "currency": pos.currency,
                "account": pos.account,
                "sector": _sector_of(pos),
                "quantity": qty,
                "avg_cost": avg,
                "last": last,
                "price_source": price_source,
                "quote_missing": last is None,
                "fx_rate": rate,
                "market_value": None,
                "unrealized_pnl": None,
                "weight_pct": None,
            }
            if rate is None:
                warnings.append(
                    f"{sym}: no {_fx_key(pos.currency)}{ccy} FX rate; excluded from {ccy} totals"
                )
            else:
                # Cost basis is qty * avg_cost, a fact of the book that needs no
                # price, so it covers every convertible position.
                total_cost += avg * qty * rate
            if last is None:
                warnings.append(f"{sym}: no live quote and no recorded price; excluded from market value and P&L")
            elif rate is not None:
                mv = qty * last * rate
                unrl = (last - avg) * qty * rate
                row["market_value"] = mv
                row["unrealized_pnl"] = unrl
                priced_mv += mv
                priced_unrl += unrl
                if prev_close is None:
                    day_missing.append(sym)
                else:
                    day = qty * (last - prev_close) * rate
                    row["day_change"] = day
                    row["day_change_pct"] = (last / prev_close - 1) * 100
                    day_total += day
                by_class[pos.instrument.asset_class.value] = (
                    by_class.get(pos.instrument.asset_class.value, 0.0) + mv
                )
                if price_source == "legacy_snapshot":
                    warnings.append(f"{sym}: no live quote; using the recorded legacy snapshot price")
            rows.append(row)
        for row in rows:
            if row["market_value"] is not None and priced_mv:
                row["weight_pct"] = row["market_value"] / priced_mv * 100

        n_rows = len(rows)
        n_unpriced = sum(1 for row in rows if row["market_value"] is None)
        # Day P&L needs a previous close for every priced position, and every
        # position must be priced: a partial sum would understate the move, so
        # it is withheld instead (the same rule as total_equity below).
        if day_missing:
            day_pnl = None
            warnings.append(
                "day P&L unavailable: no previous close for " + ", ".join(day_missing)
            )
        elif n_rows and n_unpriced == 0:
            day_pnl = day_total
        else:
            day_pnl = None
            if n_unpriced:
                warnings.append(
                    f"day P&L withheld: {n_unpriced} unpriced position(s) are excluded from the day move"
                )
        # Total equity = cash (every balance, in base ccy) + market value; it is
        # withheld while any position is unpriced, when the book does not track
        # cash, or when a cash balance has no FX rate.
        total_equity = (
            priced_mv + cash_total_base
            if cash_total_base is not None and n_unpriced == 0
            else None
        )
        realized_ytd = _realized_pnl_ytd(portfolio, warnings)
        if ccy != "USD" and realized_ytd:
            warnings.append("realized_pnl_ytd is summed as recorded; closes carry no currency")
        groups = _groups(rows, group_by, priced_mv, warnings) if group_by != "none" else []

        if n_rows and price_sources["yfinance"] == n_rows:
            price_state = "live"
        elif price_sources["yfinance"] == 0 and price_sources["missing"] == 0 and price_sources["legacy_snapshot"]:
            price_state = "legacy_snapshot"
        elif n_rows and price_sources["missing"] == n_rows:
            price_state = "unavailable"
        else:
            price_state = "partial"

        # Rates that could not be resolved are listed as None, not omitted.
        if any(rate is not None and rate != 1.0 for rate in fx_rates.values()):
            used_sources.add("yfinance")

        # VaR / ETL on (legacy) returns from state.json trade_history if available
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "positions": rows,
                "ccy": ccy,
                "as_of": datetime.now(timezone.utc).isoformat(),
                "group_by": group_by,
                "groups": groups,
                "fx_rates": dict(fx_rates),
                "totals": {
                    "market_value": priced_mv,
                    "cost_basis": total_cost,
                    "unrealized_pnl": priced_unrl,
                    "n_positions": n_rows,
                    "n_unpriced": n_unpriced,
                    "total_equity": total_equity,
                    "day_pnl": day_pnl,
                    "realized_pnl_ytd": realized_ytd,
                    **_cash_fields(cash_base, cash_by_currency, cash_total_base),
                },
                "by_asset_class": by_class,
            },
            metadata={
                "price_state": price_state,
                "price_sources": dict(price_sources),
                # Label follows the quote sources: live only when every mark came
                # from the live quote adapter; recorded snapshot prices are reference.
                "data_state": _DATA_STATE_BY_PRICE_STATE.get(price_state, "partial") if n_rows else "empty",
            },
            sources=sorted(used_sources),
            warnings=warnings,
        )


def _sector_of(pos: Any) -> str | None:
    metadata = getattr(getattr(pos, "instrument", None), "metadata", {}) or {}
    value = metadata.get("sector")
    if value in (None, ""):
        return None
    return str(value).strip() or None


def _groups(rows: list[dict[str, Any]], group_by: str, priced_total: float,
            warnings: list[str]) -> list[dict[str, Any]]:
    if group_by == "sector" and rows and all(row.get("sector") is None for row in rows):
        warnings.append("sector is not recorded on the book; every position is grouped as unclassified")
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get(group_by) or "unclassified")
        bucket = buckets.setdefault(key, {"key": key, "market_value": 0.0, "unrealized_pnl": 0.0,
                                          "n_positions": 0, "n_priced": 0})
        bucket["n_positions"] += 1
        if row["market_value"] is not None:
            bucket["market_value"] += row["market_value"]
            bucket["unrealized_pnl"] += row["unrealized_pnl"]
            bucket["n_priced"] += 1
    out = []
    for bucket in buckets.values():
        priced = bucket.pop("n_priced")
        if not priced:
            # A group with no valued position has no value: report None, not 0.
            bucket["market_value"] = None
            bucket["unrealized_pnl"] = None
            bucket["weight_pct"] = None
        else:
            bucket["weight_pct"] = bucket["market_value"] / priced_total * 100 if priced_total else None
        out.append(bucket)
    out.sort(key=lambda b: -abs(b["market_value"] or 0.0))
    return out


def _realized_pnl_ytd(portfolio: PortfolioState, warnings: list[str]) -> float:
    """Realized P&L from closes dated in the current UTC year.

    Only dated close records count. Realized P&L still sitting on open
    positions carries no date, so it is excluded and said so in a warning.
    """
    year = str(datetime.now(timezone.utc).year)
    total = 0.0
    for record in getattr(portfolio, "closed_positions", None) or []:
        if not isinstance(record, dict):
            continue
        if str(record.get("closed_at") or "")[:4] != year:
            continue
        value = _finite_number(record.get("realized_pnl"))
        if value is not None:
            total += value
    undated = [
        pos.instrument.symbol
        for pos in portfolio.positions
        if (_finite_number(getattr(pos, "realized_pnl", 0)) or 0.0) != 0.0
    ]
    if undated:
        warnings.append(
            "realized P&L on open positions has no close date and is excluded from "
            "realized_pnl_ytd: " + ", ".join(undated)
        )
    return total


def _legacy_last_price(pos: Any) -> float | None:
    """The recorded ``current_price`` from the legacy book, or ``None``.

    This is a snapshot taken when the book was written, not a live quote; the
    caller labels it ``legacy_snapshot``. There is deliberately no fallback to
    ``avg_cost``: a missing price must stay missing.
    """
    metadata = getattr(getattr(pos, "instrument", None), "metadata", {}) or {}
    return _finite_positive(metadata.get("current_price"))
