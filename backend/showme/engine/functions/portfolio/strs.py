"""STRS — Stress test against predefined and custom scenarios."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.portfolio.state import PortfolioState
from showme.engine.services import stress_scenarios as stress


@FunctionRegistry.register
class STRSFunction(BaseFunction):
    code = "STRS"
    name = "Portfolio Stress Test"
    category = "portfolio"
    description = "Apply historical and custom shock scenarios to portfolio."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = (params.get("action") or "compare").lower()
        if action == "list":
            return FunctionResult(
                code=self.code, instrument=None,
                data={"scenarios": stress.list_scenarios(),
                      "rows": stress.list_scenarios(),
                      "methodology": _methodology(),
                      "field_dictionary": _field_dictionary()},
                sources=["stress_scenarios"],
            )
        portfolio = PortfolioState()
        portfolio.import_legacy_crypto()
        if not portfolio.positions:
            # Empty-portfolio path used to return `data={}` which gave the UI
            # no `rows`/`status` to render — the pane went blank instead of
            # telling the user what to do. Return a structured empty payload
            # with next_actions so the front-end can surface an Empty card.
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "empty_portfolio",
                    "rows": [],
                    "comparisons": [],
                    "summary": {
                        "scenarios": 0,
                        "positions": 0,
                        "worst_total_pnl": 0,
                        "price_source": "n/a",
                    },
                    "methodology": _methodology(),
                    "field_dictionary": _field_dictionary(),
                    "next_actions": [
                        "Add positions in PORT or run the legacy-crypto import.",
                        "Use action=list to inspect the predefined scenario catalog without a portfolio.",
                    ],
                },
                warnings=["empty portfolio"],
                sources=["portfolio_state"],
            )
        # Build position dicts with current MV. Stress comparison should never
        # block on public quote/refdata providers; live price refresh is opt-in.
        symbols = list({p.instrument.symbol for p in portfolio.positions})
        quote_timeout = float(params.get("quote_timeout", params.get("timeout", 3)))
        refresh_prices = _truthy(params.get("refresh_prices") or params.get("live_prices"))
        prices = await self._quote_many(symbols, timeout=quote_timeout) if refresh_prices else {}
        sector_lookup: dict[str, str] = {}
        include_sectors = _truthy(params.get("include_sectors"))
        if include_sectors and self.deps.yfinance:
            await self._sectors(symbols, sector_lookup, timeout=min(quote_timeout, 2.0))
        positions_payload: list[dict[str, Any]] = []
        for p in portfolio.positions:
            px = prices.get(p.instrument.symbol) or p.avg_cost
            mv = p.quantity * px
            positions_payload.append({
                "symbol": p.instrument.symbol,
                "asset_class": p.instrument.asset_class.value,
                "market_value": mv,
                "sector": sector_lookup.get(p.instrument.symbol),
            })
        scale = float(params.get("scale", 1.0))
        sources = ["stress_scenarios", "portfolio_state"]
        if refresh_prices or include_sectors:
            sources.insert(0, "yfinance")
        # Bond funds in the GFC/COVID windows take their own measured window return.
        # Fetch it only for the windows this request runs; custom shocks use none.
        bond_symbols = sorted({
            p["symbol"] for p in positions_payload
            if stress.resolve_shock_bucket(p["symbol"], p["asset_class"]) == "BOND"
        })
        if action == "compare":
            window_keys = list(stress.MEASURED_WINDOWS)
        elif action == "custom":
            window_keys = []
        else:
            named = (params.get("scenario") or params.get("key") or "GFC_2008").upper()
            window_keys = [named] if named in stress.MEASURED_WINDOWS else []
        measured_by_key: dict[str, dict[str, float | None]] = {}
        if bond_symbols and window_keys:
            history_timeout = float(params.get("history_timeout", 8))
            measured_by_key = await self._measured_window_returns(
                bond_symbols, window_keys, timeout=history_timeout,
            )
            if any(v is not None for win in measured_by_key.values() for v in win.values()):
                sources.insert(0, "yfinance_history")
        if action == "compare":
            keys = params.get("scenarios") or list(stress.SCENARIOS)
            data = stress.compare_scenarios(
                positions_payload,
                keys,
                sector_lookup=sector_lookup,
                scale=scale,
                measured_by_key=measured_by_key,
            )
            compare_warnings = _unique_warnings(row.get("warnings", []) for row in data)
            return FunctionResult(code=self.code, instrument=None,
                                  warnings=compare_warnings,
                                  data={"comparisons": data,
                                        "rows": data,
                                        "summary": {
                                            "scenarios": len(data),
                                            "positions": len(positions_payload),
                                            "worst_total_pnl": data[0]["total_pnl"] if data else 0,
                                            "price_source": "live_quote" if refresh_prices else "portfolio_state_cost",
                                            "unpriced_positions": max(
                                                (row["unpriced_positions"] for row in data), default=0,
                                            ),
                                        },
                                        "methodology": _methodology(),
                                        "field_dictionary": _field_dictionary()},
                                  sources=sources)
        if action == "custom":
            sc = stress.custom_scenario(
                name=params.get("name", "custom"),
                description=params.get("description", "User shock"),
                horizon_days=int(params.get("horizon_days", 30)),
                asset_class_shocks=params.get("asset_class_shocks") or {},
                sector_shocks=params.get("sector_shocks") or {},
                symbol_shocks=params.get("symbol_shocks") or {},
            )
            data = stress.apply_scenario(positions_payload, sc, sector_lookup=sector_lookup, scale=scale)
            return FunctionResult(code=self.code, instrument=None,
                                  warnings=list(data.get("warnings", [])),
                                  data={**data, "rows": data.get("positions", []),
                                        "methodology": _methodology(),
                                        "field_dictionary": _field_dictionary()},
                                  sources=sources)
        # default: run named scenario
        key = (params.get("scenario") or params.get("key") or "GFC_2008").upper()
        sc = stress.get_scenario(key)
        if not sc:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=[f"unknown scenario {key}"])
        data = stress.apply_scenario(
            positions_payload, sc, sector_lookup=sector_lookup, scale=scale,
            measured=measured_by_key.get(key) if key in stress.MEASURED_WINDOWS else None,
        )
        return FunctionResult(code=self.code, instrument=None,
                              warnings=list(data.get("warnings", [])),
                              data={**data, "rows": data.get("positions", []),
                                    "methodology": _methodology(),
                                    "field_dictionary": _field_dictionary()},
                              sources=sources)

    async def _quote_many(self, symbols: list[str], timeout: float = 3.0) -> dict[str, float]:
        out: dict[str, float] = {}
        if not self.deps.yfinance:
            return out
        async def _q(sym: str) -> tuple[str, float]:
            try:
                inst = Instrument(symbol=sym, asset_class=_asset_class_for_quote(sym))
                quote = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.QUOTE,
                        instrument=inst,
                        extra={"timeout": max(0.5, timeout)},
                    )),
                    timeout=max(0.75, timeout + 0.25),
                )
                return sym, float(quote.last or 0)
            except Exception:
                return sym, 0.0
        results = await asyncio.gather(*(_q(s) for s in symbols))
        return dict(results)

    async def _measured_window_returns(
        self, symbols: list[str], keys: list[str], timeout: float = 8.0,
    ) -> dict[str, dict[str, float | None]]:
        """Measured price return of each bond fund over each named window.

        A failed or thin history yields ``None`` for that fund and window, which the
        scenario reports as unavailable. Nothing is estimated or substituted.
        """
        out: dict[str, dict[str, float | None]] = {k: {s: None for s in symbols} for k in keys}
        if not self.deps.yfinance:
            return out

        async def _one(sym: str, key: str) -> None:
            start, end = stress.MEASURED_WINDOWS[key]
            request = DataRequest(
                kind=DataKind.OHLCV,
                instrument=Instrument(symbol=sym, asset_class=AssetClass.ETF),
                start=datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
                end=datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1),
                interval="1d",
                extra={"timeout": max(0.5, timeout)},
            )
            try:
                df = await asyncio.wait_for(
                    self.deps.yfinance.fetch(request),
                    timeout=max(0.75, timeout + 0.25),
                )
                closes = [(_as_date(idx), close) for idx, close in zip(df.index, df["close"])]
                out[key][sym] = stress.measured_window_return(closes, start, end)
            except Exception:
                out[key][sym] = None

        await asyncio.gather(*(_one(s, k) for s in symbols for k in keys))
        return out

    async def _sectors(self, symbols: list[str], lookup: dict[str, str], timeout: float = 2.0) -> None:
        async def _s(sym: str) -> None:
            try:
                inst = Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
                meta = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.REFDATA,
                        instrument=inst,
                        extra={"timeout": max(0.5, timeout)},
                    )),
                    timeout=max(0.75, timeout + 0.25),
                )
                sector = getattr(meta, "sector", None)
                if sector:
                    lookup[sym] = str(sector)
            except Exception:
                pass
        await asyncio.gather(*(_s(s) for s in symbols))


def _asset_class_for_quote(symbol: str) -> AssetClass:
    upper = str(symbol or "").upper()
    if upper.endswith(("USDT", "USDC", "BTC", "ETH")):
        return AssetClass.CRYPTO
    if upper.endswith("=F"):
        return AssetClass.COMMODITY
    if len(upper) == 6 and upper.endswith(("USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD")):
        return AssetClass.FX
    return AssetClass.EQUITY


def _as_date(value: Any) -> Any:
    """Calendar date of a history index entry (pandas Timestamp or datetime)."""
    day = getattr(value, "date", None)
    return day() if callable(day) else value


def _unique_warnings(groups: Any) -> list[str]:
    seen: list[str] = []
    for group in groups:
        for warning in group or []:
            if warning not in seen:
                seen.append(warning)
    return seen


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _methodology() -> str:
    return (
        "Mark current portfolio positions to market, apply predefined or custom shocks by symbol, sector, "
        "or asset class, then compute stressed market value and P&L. Compare mode ranks scenarios by total P&L."
    )


def _field_dictionary() -> dict[str, str]:
    return {
        "total_pnl": "Portfolio dollar change under the stress scenario.",
        "total_return_pct": "Portfolio percentage return under the scenario.",
        "horizon_days": "Historical or assumed scenario horizon.",
        "shock": "Applied return shock for a position.",
        "market_value_post": "Position market value after the shock.",
        "shock_source": "How the shock was set: hand_set, measured_window, or unavailable (not estimated).",
        "unpriced_positions": "Positions left unshocked because their measured window return was unavailable.",
    }
