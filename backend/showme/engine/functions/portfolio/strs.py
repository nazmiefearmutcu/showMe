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
                        "Add positions in PORT.",
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
        # Sector shocks are on by default (STRS#2): the pane sends no include_sectors,
        # and with the lookup off no sector shock ever reached a position.
        raw_include = params.get("include_sectors")
        include_sectors = True if raw_include is None else _truthy(raw_include)
        sector_failures: dict[str, str] = {}
        if include_sectors and self.deps.yfinance:
            await self._sectors(symbols, sector_lookup, timeout=min(quote_timeout, 2.0),
                                failures=sector_failures)
        positions_payload: list[dict[str, Any]] = []
        # STRS#6: state which basis each position was valued on. A live-mode position
        # with no quote falls back to average cost and is flagged, never silent.
        price_basis: dict[str, str] = {}
        for p in portfolio.positions:
            sym = p.instrument.symbol
            if not refresh_prices:
                price_basis[sym] = "portfolio_state_cost"
            elif prices.get(sym):
                price_basis[sym] = "live_quote"
            else:
                price_basis[sym] = "avg_cost_fallback"
            px = prices.get(sym) or p.avg_cost
            mv = p.quantity * px
            positions_payload.append({
                "symbol": sym,
                "asset_class": p.instrument.asset_class.value,
                "market_value": mv,
                "sector": sector_lookup.get(sym),
            })
        price_source = _price_source(price_basis, refresh_prices)
        price_warnings = [
            *_price_warnings(price_basis, refresh_prices),
            *_sector_warnings(include_sectors, bool(self.deps.yfinance), sector_failures),
        ]
        # The manifest's `scenario_magnitudes` input is the scale factor; `scale` is kept
        # as the older spelling.
        scale_raw = params.get("scale")
        if scale_raw is None:
            scale_raw = params.get("scenario_magnitudes", 1.0)
        scale = float(scale_raw)
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
            requested = _requested_scenarios(params.get("scenarios"))
            keys = requested or list(stress.SCENARIOS)
            # A key the engine does not run is reported, never silently dropped.
            unknown_warnings = [
                f"unknown scenario {k}: not run" for k in keys if k.upper() not in stress.SCENARIOS
            ]
            data = stress.compare_scenarios(
                positions_payload,
                keys,
                sector_lookup=sector_lookup,
                scale=scale,
                measured_by_key=measured_by_key,
            )
            compare_warnings = _unique_warnings(
                [price_warnings, unknown_warnings,
                 *(row.get("warnings", []) for row in data)],
            )
            return FunctionResult(code=self.code, instrument=None,
                                  warnings=compare_warnings,
                                  data={"comparisons": data,
                                        "rows": data,
                                        "summary": {
                                            "scenarios": len(data),
                                            "positions": len(positions_payload),
                                            "worst_total_pnl": data[0]["total_pnl"] if data else 0,
                                            "price_source": price_source,
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
            _stamp_price_basis(data, price_basis, price_source)
            return FunctionResult(code=self.code, instrument=None,
                                  warnings=_unique_warnings([price_warnings, data.get("warnings", [])]),
                                  data={**data, "rows": data.get("positions", []),
                                        "methodology": _methodology(),
                                        "field_dictionary": _field_dictionary()},
                                  sources=sources)
        # default: run named scenario
        key = (params.get("scenario") or params.get("key") or "GFC_2008").upper()
        sc = stress.get_scenario(key)
        if not sc:
            # Explicit input error with the runnable keys, not an empty payload.
            return FunctionResult(
                code=self.code, instrument=None,
                data={
                    "status": "input_error",
                    "reason": f"{key} is not a scenario the engine runs.",
                    "rows": [],
                    "scenarios": list(stress.SCENARIOS),
                    "methodology": _methodology(),
                    "field_dictionary": _field_dictionary(),
                    "next_actions": [
                        "Pass one of the listed scenario keys in `scenario`.",
                        "Use action=compare to run every listed scenario at once.",
                    ],
                },
                warnings=[f"unknown scenario {key}"],
                sources=["stress_scenarios"],
            )
        data = stress.apply_scenario(
            positions_payload, sc, sector_lookup=sector_lookup, scale=scale,
            measured=measured_by_key.get(key) if key in stress.MEASURED_WINDOWS else None,
        )
        _stamp_price_basis(data, price_basis, price_source)
        return FunctionResult(code=self.code, instrument=None,
                              warnings=_unique_warnings([price_warnings, data.get("warnings", [])]),
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

    async def _sectors(
        self, symbols: list[str], lookup: dict[str, str], timeout: float = 2.0,
        failures: dict[str, str] | None = None,
    ) -> None:
        """Fill ``lookup`` with sectors; record each symbol that got none in ``failures``.

        STRS#2: a failed or empty REFDATA answer is never swallowed. It is recorded
        with its reason so the handler can say the asset-class shock was used.
        """
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
                elif failures is not None:
                    failures[sym] = "no sector reported"
            except Exception as exc:
                if failures is not None:
                    failures[sym] = f"lookup failed ({type(exc).__name__})"
        await asyncio.gather(*(_s(s) for s in symbols))


def _sector_warnings(
    include_sectors: bool, has_adapter: bool, failures: dict[str, str],
) -> list[str]:
    """Why sector shocks may not have reached positions, stated in the result."""
    if not include_sectors:
        return []
    if not has_adapter:
        return ["sector lookup unavailable: no market data adapter; "
                "sector shocks not applied, asset-class shocks used"]
    return [
        f"{sym}: sector unavailable ({reason}); asset-class shock used, not a sector shock"
        for sym, reason in sorted(failures.items())
    ]


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


def _price_source(basis: dict[str, str], refresh_prices: bool) -> str:
    """live_quote when every position was quoted, mixed when some fell back, else cost."""
    if not refresh_prices or not basis:
        return "portfolio_state_cost"
    values = set(basis.values())
    if values == {"live_quote"}:
        return "live_quote"
    if "live_quote" in values:
        return "mixed"
    return "portfolio_state_cost"


def _price_warnings(basis: dict[str, str], refresh_prices: bool) -> list[str]:
    if not basis:
        return []
    if not refresh_prices:
        return ["positions valued at average cost (no live refresh); "
                "pass refresh_prices=true for live marks"]
    return [
        f"{sym}: live quote unavailable; valued at average cost (not a live mark)"
        for sym, value in basis.items() if value == "avg_cost_fallback"
    ]


def _stamp_price_basis(data: dict[str, Any], basis: dict[str, str], price_source: str) -> None:
    """Record the valuation basis on the response and on each stressed position."""
    data["price_source"] = price_source
    for row in data.get("positions", []):
        row["price_basis"] = basis.get(row.get("symbol"), "portfolio_state_cost")


def _unique_warnings(groups: Any) -> list[str]:
    seen: list[str] = []
    for group in groups:
        for warning in group or []:
            if warning not in seen:
                seen.append(warning)
    return seen


def _requested_scenarios(value: Any) -> list[str]:
    """Scenario keys from a list or a comma-separated string (iterating a str would split characters)."""
    if value is None:
        return []
    if isinstance(value, str):
        items: list[Any] = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]
    return [str(v).strip() for v in items if str(v).strip()]


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
        "price_source": "Valuation basis: portfolio_state_cost (average cost), live_quote (all positions quoted), or mixed (some positions fell back to average cost).",
        "price_basis": "Valuation basis of one position: portfolio_state_cost, live_quote, or avg_cost_fallback (live mode, no quote).",
        "sector": "Sector in the scenario taxonomy (GICS-style key that the shock lookup matches). A normalized name, not the provider's label.",
        "sector_provider_label": "The sector label the data provider returned, unchanged.",
    }
