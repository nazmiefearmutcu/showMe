"""FXH — FX hedging (forward overlay) calculator."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.services.fx_hedge import FXExposure, forward_rate, hedge_book, hedge_one


@FunctionRegistry.register
class FXHFunction(BaseFunction):
    code = "FXH"
    name = "FX Hedge"
    asset_classes = (AssetClass.FX,)
    category = "fx"
    description = "Forward-rate overlay calculator for foreign-currency exposure."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = (params.get("action") or "calc").lower()
        pair = _normalize_pair(
            str(params.get("pair") or params.get("symbol") or (instrument.symbol if instrument else "") or "EURUSD")
        )
        pair_base, pair_quote = pair[:3], pair[3:6]
        home = (params.get("home_currency") or pair_quote or "USD").upper()
        days = int(params.get("days", 90))
        ratio = float(params.get("hedge_ratio", 0.75))
        shock = float(params.get("usd_shock_pct", 0.05))
        source_mode = "manual_exposure"
        # explicit exposures override manual defaults; portfolio state is only
        # used when explicitly requested so crypto/stablecoin positions do not
        # masquerade as an FX hedge book.
        exposures = params.get("exposures")
        if not exposures:
            if _truthy(params.get("use_portfolio") or params.get("portfolio")):
                exposures = await self._derive_exposures(home)
                source_mode = "portfolio_state"
            else:
                exposures = [{
                    "currency": (params.get("currency") or pair_base or "EUR").upper(),
                    "notional": float(params.get("notional", 1_000_000)),
                    "spot_rate": params.get("spot_rate") or params.get("spot"),
                    "base_rate": params.get("base_rate", 0.035),
                    "home_rate": params.get("home_rate", 0.045),
                }]
        # Resolve spot rates if missing
        await self._fill_spots(exposures, home)
        objs = [
            FXExposure(
                currency=e["currency"].upper(), home_currency=home,
                notional=float(e["notional"]),
                spot_rate=float(e.get("spot_rate") or 1.0),
                base_rate=float(e.get("base_rate", 0.04)),
                home_rate=float(e.get("home_rate", 0.045)),
            ) for e in exposures
        ]
        if action == "forward":
            return FunctionResult(
                code=self.code, instrument=None,
                data={"forwards": [{
                    "pair": f"{e.currency}/{home}",
                    "spot": e.spot_rate,
                    "forward": forward_rate(spot=e.spot_rate,
                                            home_rate=e.home_rate,
                                            base_rate=e.base_rate, days=days),
                    "days": days,
                } for e in objs]},
            )
        out = hedge_book(objs, hedge_ratio=ratio, days=days, usd_shock_pct=shock)
        out["rows"] = list(out.get("exposures") or [])
        out["curve"] = _scenario_curve(objs, ratio, days)
        out["source_mode"] = source_mode
        out["methodology"] = (
            "FXH computes a forward overlay for foreign-currency exposure. "
            "Forward rate uses covered interest parity: F = S * (1 + home_rate*T) / (1 + base_rate*T). "
            "Hedged notional = exposure * hedge_ratio. Scenario P&L applies shocks to the unhedged residual plus locked-in carry."
        )
        out["field_dictionary"] = {
            "notional_foreign": "Exposure amount in the foreign/base currency.",
            "spot_rate": "Home currency units per one foreign/base currency.",
            "forward_rate": "Covered-interest-parity forward rate for the selected maturity.",
            "hedge_ratio": "Share of the foreign exposure hedged with forwards.",
            "carry_pnl_home": "Forward carry P&L on the hedged notional.",
            "pnl_if_home_strengthens": "Residual exposure P&L if home currency strengthens by shock_pct, plus carry.",
            "pnl_if_home_weakens": "Residual exposure P&L if home currency weakens by shock_pct, plus carry.",
        }
        return FunctionResult(code=self.code, instrument=instrument,
                              data=out, sources=["yfinance", "ecb"])

    async def _derive_exposures(self, home: str) -> list[dict[str, Any]]:
        """Group portfolio positions by foreign currency."""
        from src.portfolio.state import PortfolioState
        ps = PortfolioState()
        ps.import_legacy_crypto()
        by_ccy: dict[str, float] = {}
        for p in ps.positions:
            ccy = (p.currency or home).upper()
            if ccy == home:
                continue
            by_ccy[ccy] = by_ccy.get(ccy, 0.0) + p.quantity * p.avg_cost
        return [{"currency": c, "notional": n} for c, n in by_ccy.items()]

    async def _fill_spots(self, exposures: list[dict[str, Any]], home: str) -> None:
        if not self.deps.yfinance:
            return
        async def _q(e: dict[str, Any]) -> None:
            if e.get("spot_rate"):
                return
            pair = f"{e['currency']}{home}=X"
            try:
                inst = Instrument(symbol=pair, asset_class=AssetClass.FX)
                quote = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.QUOTE, instrument=inst))
                e["spot_rate"] = float(getattr(quote, "last", 0) or 0) or 1.0
            except Exception:
                e["spot_rate"] = 1.0
        await asyncio.gather(*(_q(e) for e in exposures))


def _normalize_pair(raw: str) -> str:
    value = raw.upper().strip().replace("/", "").replace("-", "").replace(" ", "")
    value = value.replace("=X", "")
    if len(value) >= 6 and value[:3].isalpha() and value[3:6].isalpha():
        return value[:6]
    return "EURUSD"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _scenario_curve(objs: list[FXExposure], hedge_ratio: float, days: int) -> list[dict[str, Any]]:
    curve = []
    shocks = [-0.10, -0.05, 0.0, 0.05, 0.10]
    for shock in shocks:
        total = 0.0
        unhedged = 0.0
        for exp in objs:
            fwd = forward_rate(
                spot=exp.spot_rate,
                home_rate=exp.home_rate,
                base_rate=exp.base_rate,
                days=days,
            )
            hedged_notional = exp.notional * hedge_ratio
            residual = exp.notional - hedged_notional
            shocked_spot = exp.spot_rate * (1 + shock)
            carry = (fwd - exp.spot_rate) * hedged_notional
            total += residual * (shocked_spot - exp.spot_rate) + carry
            unhedged += exp.notional * (shocked_spot - exp.spot_rate)
        curve.append({
            "shock_pct": round(shock * 100, 2),
            "total_pnl": total,
            "unhedged_pnl": unhedged,
            "days": days,
            "hedge_ratio": hedge_ratio,
        })
    return curve
