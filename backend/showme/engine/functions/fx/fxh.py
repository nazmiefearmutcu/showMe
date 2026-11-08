"""FXH — FX hedging (forward overlay) calculator."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.services.fx_hedge import SIDE_SIGN, FXExposure, forward_rate, hedge_book

# Illustrative-book defaults. The pane exposes explicit inputs for all three;
# these remain for API callers and are echoed as ``assumed_defaults`` so a
# synthetic $1M book is never presented as the caller's own exposure.
DEFAULT_NOTIONAL = 1_000_000.0
DEFAULT_BASE_RATE = 0.035
DEFAULT_HOME_RATE = 0.045
# Manifest default for the hedge bid-ask (pips), used for hedge_cost.
DEFAULT_BID_ASK_PIPS = 2.0
# Manifest tenor options (see fxh_seed.py) mapped to calendar days.
TENOR_DAYS: dict[str, int] = {"1W": 7, "1M": 30, "3M": 90, "6M": 180, "1Y": 365}


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
        ratio = float(params.get("hedge_ratio", 0.75))
        # Manifest tenor (1W..1Y) maps to days unless an explicit days is given.
        if _missing(params.get("days")) and not _missing(params.get("tenor")):
            tenor_key = str(params.get("tenor")).strip().upper()
            if tenor_key not in TENOR_DAYS:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        "status": "input_error",
                        "reason": f"Unknown tenor {params.get('tenor')!r}; expected one of {sorted(TENOR_DAYS)}.",
                        "rows": [],
                        "source_mode": "manual_exposure",
                    },
                    sources=["manual_exposure"],
                    warnings=[],
                )
            days = TENOR_DAYS[tenor_key]
        else:
            days = int(params.get("days", 90))
        # Manifest exposure_side (long_foreign | short_foreign). Per-exposure
        # ``side`` overrides it; an unknown side is an explicit input error.
        exposure_side = str(params.get("exposure_side") or "long_foreign").strip().lower()
        if exposure_side not in SIDE_SIGN:
            return _input_error(
                self.code,
                f"Unknown exposure_side {params.get('exposure_side')!r}; expected long_foreign or short_foreign.",
            )
        # Shock: legacy usd_shock_pct is a decimal; the manifest spot_shock_pct
        # is a percent. The legacy key wins when both are sent.
        if not _missing(params.get("usd_shock_pct")):
            shock = float(params["usd_shock_pct"])
        elif not _missing(params.get("spot_shock_pct")):
            shock_pct = float(params["spot_shock_pct"])
            if not -50.0 <= shock_pct <= 50.0:
                return _input_error(
                    self.code,
                    f"spot_shock_pct {shock_pct:g} is outside the manifest range -50..50 percent.",
                )
            shock = shock_pct / 100.0
        else:
            shock = 0.05
        source_mode = "manual_exposure"
        assumed_defaults: list[str] = []
        # explicit exposures override manual defaults; portfolio state is only
        # used when explicitly requested so crypto/stablecoin positions do not
        # masquerade as an FX hedge book.
        exposures = params.get("exposures")
        if not exposures:
            if _truthy(params.get("use_portfolio") or params.get("portfolio")):
                exposures = await self._derive_exposures(home)
                source_mode = "portfolio_state"
            else:
                raw_notional = params.get("notional", params.get("exposure_notional"))
                if raw_notional in (None, ""):
                    assumed_defaults.append("notional")
                    notional = DEFAULT_NOTIONAL
                else:
                    notional = float(raw_notional)
                if params.get("base_rate") in (None, ""):
                    assumed_defaults.append("base_rate")
                if params.get("home_rate") in (None, ""):
                    assumed_defaults.append("home_rate")
                exposures = [{
                    "currency": (params.get("currency") or pair_base or "EUR").upper(),
                    "notional": notional,
                    "spot_rate": params.get("spot_rate") or params.get("spot"),
                    "base_rate": params.get("base_rate", DEFAULT_BASE_RATE),
                    "home_rate": params.get("home_rate", DEFAULT_HOME_RATE),
                    "side": exposure_side,
                }]
        for e in exposures:
            if _missing(e.get("side")):
                e["side"] = exposure_side
            if str(e["side"]).strip().lower() not in SIDE_SIGN:
                return _input_error(
                    self.code,
                    f"Unknown exposure side {e['side']!r}; expected long_foreign or short_foreign.",
                )
            e["side"] = str(e["side"]).strip().lower()
        # Resolve spot rates if missing. _fill_spots returns the list of
        # currencies whose spot could NOT be resolved live and were not
        # supplied manually. We do not substitute 1.0 silently — the hedge
        # book would otherwise compute fictitious notionals and carry P&L.
        spot_failed, fetched_live = await self._fill_spots(exposures, home)
        warnings: list[str] = []
        if spot_failed:
            warnings.append(
                "FXH: spot rate unavailable for "
                + ", ".join(sorted(set(spot_failed)))
                + "; rows for those currencies are omitted from the hedge book."
            )
            exposures = [
                e for e in exposures
                if e.get("spot_rate") and e["currency"].upper() not in {c.upper() for c in spot_failed}
            ]
        if not exposures and source_mode == "portfolio_state":
            # Portfolio mode found no non-home-currency positions: there is
            # nothing to hedge, which is not a spot-provider problem.
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "empty",
                    "reason": (
                        f"No non-home-currency positions in the portfolio to hedge "
                        f"(home currency {home}). Add a foreign-currency position or "
                        "pass explicit exposures."
                    ),
                    "rows": [],
                    "source_mode": "portfolio_state",
                    "home_currency": home,
                    "methodology": "FXH hedges only positions whose currency differs from the home currency.",
                },
                sources=[source_mode],
                warnings=warnings,
            )
        if not exposures:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "data_unavailable",
                    "reason": "No exposure has a usable spot rate; provide spot_rate manually or retry when the FX quote provider recovers.",
                    "rows": [],
                    "source_mode": "no_spot_data",
                    "methodology": "FXH refuses to compute a hedge book without a real spot rate to avoid fictitious notionals.",
                },
                sources=[source_mode],
                warnings=warnings,
            )
        objs: list[FXExposure] = []
        for e in exposures:
            # Any rate the caller did not supply falls back to the documented
            # engine default and is echoed in assumed_defaults (never a silent
            # literal such as the old 0.04 base-rate fallback).
            for rate_key in ("base_rate", "home_rate"):
                if _missing(e.get(rate_key)) and rate_key not in assumed_defaults:
                    assumed_defaults.append(rate_key)
            objs.append(FXExposure(
                currency=e["currency"].upper(), home_currency=home,
                notional=float(e["notional"]),
                spot_rate=float(e["spot_rate"]),
                base_rate=_rate(e.get("base_rate"), DEFAULT_BASE_RATE),
                home_rate=_rate(e.get("home_rate"), DEFAULT_HOME_RATE),
                side=e["side"],
            ))
        # Effective source_mode reflects whether ANY spot came from the live
        # provider — not a blanket "yfinance,ecb" claim.
        effective_source = (
            "live_yfinance_quote" if fetched_live and source_mode == "manual_exposure"
            else source_mode
        )
        sources_used = sorted(
            {effective_source, *(["yfinance"] if fetched_live else [])}
        )
        if action == "forward":
            forward_data = {
                "forwards": [{
                    "pair": f"{e.currency}/{home}",
                    "spot": e.spot_rate,
                    "forward": forward_rate(
                        spot=e.spot_rate,
                        home_rate=e.home_rate,
                        base_rate=e.base_rate, days=days,
                    ),
                    "days": days,
                } for e in objs],
                "source_mode": effective_source,
                "assumed_defaults": assumed_defaults,
                "methodology": (
                    "FXH forward branch returns covered-interest-parity forward rates "
                    "F = S * (1 + home_rate*T) / (1 + base_rate*T) for each exposure pair."
                ),
                "field_dictionary": {
                    "spot": "Live or supplied spot rate in home currency units per foreign unit.",
                    "forward": "Covered-interest-parity forward rate for the selected maturity.",
                    "days": "Maturity (days) used for the forward calculation.",
                },
            }
            _attach_assumed_values(forward_data, assumed_defaults)
            return FunctionResult(
                code=self.code, instrument=None,
                data=forward_data,
                sources=sources_used,
                warnings=warnings,
            )
        # Hedge bid-ask in pips drives hedge_cost. Missing -> manifest default,
        # flagged in assumed_defaults so it is never a silent literal.
        if _missing(params.get("bid_ask_pips")):
            if "bid_ask_pips" not in assumed_defaults:
                assumed_defaults.append("bid_ask_pips")
            bid_ask_pips = DEFAULT_BID_ASK_PIPS
        else:
            bid_ask_pips = float(params["bid_ask_pips"])
        out = hedge_book(objs, hedge_ratio=ratio, days=days, usd_shock_pct=shock)
        out["rows"] = list(out.get("exposures") or [])
        # Manifest contract fields (additive): per-row spot / notionals / cost
        # plus the single-scenario P&L from the manifest formulas.
        scenario_totals = _manifest_scenario(objs, out["rows"], ratio, shock, bid_ask_pips)
        out["pair"] = pair
        out["as_of"] = datetime.now(timezone.utc).isoformat()
        out["data_mode"] = effective_source
        out["bid_ask_pips"] = bid_ask_pips
        out["spot_shock_pct"] = shock * 100
        # Top-level side follows the computed rows (a per-row side overrides
        # the request default); mixed sides have no single top-level side.
        row_sides = {e.side for e in objs}
        out["exposure_side"] = next(iter(row_sides)) if len(row_sides) == 1 else None
        single = out["rows"][0] if len(out["rows"]) == 1 else None
        out["spot"] = single["spot_rate"] if single else None
        out["exposure_notional"] = single["notional_foreign"] if single else None
        out["hedge_notional"] = single["hedge_notional"] if single else None
        out["residual_notional"] = single["residual_notional"] if single else None
        out["pnl_unhedged"] = scenario_totals["pnl_unhedged"]
        out["pnl_hedged"] = scenario_totals["pnl_hedged"]
        out["hedge_cost"] = scenario_totals["hedge_cost"]
        if not single:
            warnings.append(
                "Multi-currency book: spot, exposure and hedge notionals are per currency "
                "in rows[] (foreign units are not summed); P&L and cost totals are in home currency."
            )
        # Portfolio notionals are quantity * avg_cost: a historical cost basis,
        # not market value. Disclose it so the hedge is not read as tracking price.
        out["notional_basis"] = (
            "portfolio_historical_cost" if source_mode == "portfolio_state" else "user_supplied"
        )
        if source_mode == "portfolio_state":
            warnings.append(
                "Portfolio notionals are quantity x average cost (historical cost basis, "
                "not market value); the hedge does not follow later price moves."
            )
        out["curve"] = _scenario_curve(objs, ratio, days)
        out["source_mode"] = effective_source
        out["assumed_defaults"] = assumed_defaults
        _attach_assumed_values(out, assumed_defaults)
        out["methodology"] = (
            "FXH computes a forward overlay for foreign-currency exposure. "
            "Forward rate uses covered interest parity: F = S * (1 + home_rate*T) / (1 + base_rate*T). "
            "Hedged notional = exposure * hedge_ratio. Scenario P&L applies shocks to the unhedged residual plus locked-in carry."
        )
        if source_mode == "portfolio_state":
            out["methodology"] += (
                " Notional basis: historical cost (quantity x avg_cost), not market value."
            )
        out["field_dictionary"] = {
            "hedge_cost": "Hedge transaction cost in home currency: hedge_notional * bid_ask_pips * pip_size (pip 0.0001, JPY quote 0.01).",
            "pnl_unhedged": "Manifest scenario: sign(side) * exposure * spot * spot_shock; home currency.",
            "pnl_hedged": "Manifest scenario: sign(side) * residual * spot * spot_shock - hedge_cost; home currency.",
            "notional_foreign": "Exposure amount in the foreign/base currency.",
            "spot_rate": "Home currency units per one foreign/base currency.",
            "forward_rate": "Covered-interest-parity forward rate for the selected maturity.",
            "hedge_ratio": "Share of the foreign exposure hedged with forwards.",
            "carry_pnl_home": "Forward carry P&L on the hedged notional.",
            "pnl_if_home_strengthens": "Residual exposure P&L if home currency strengthens by shock_pct, plus carry.",
            "pnl_if_home_weakens": "Residual exposure P&L if home currency weakens by shock_pct, plus carry.",
        }
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=out,
            sources=sources_used,
            warnings=warnings,
        )

    async def _derive_exposures(self, home: str) -> list[dict[str, Any]]:
        """Group portfolio positions by foreign currency."""
        from showme.engine.portfolio.state import PortfolioState
        ps = PortfolioState()
        ps.import_legacy_crypto()
        by_ccy: dict[str, float] = {}
        for p in ps.positions:
            ccy = (p.currency or home).upper()
            if ccy == home:
                continue
            by_ccy[ccy] = by_ccy.get(ccy, 0.0) + p.quantity * p.avg_cost
        return [{"currency": c, "notional": n} for c, n in by_ccy.items()]

    async def _fill_spots(
        self, exposures: list[dict[str, Any]], home: str,
    ) -> tuple[list[str], bool]:
        """Resolve missing spot rates from the FX provider.

        Returns (failed_currencies, fetched_live). Does NOT substitute 1.0
        for a missing rate — callers must filter or surface the failure.
        """
        if not self.deps.yfinance:
            return ([e["currency"] for e in exposures if not e.get("spot_rate")], False)
        failed: list[str] = []
        live_hits = 0

        async def _q(e: dict[str, Any]) -> None:
            nonlocal live_hits
            if e.get("spot_rate"):
                return
            pair = f"{e['currency']}{home}=X"
            try:
                inst = Instrument(symbol=pair, asset_class=AssetClass.FX)
                quote = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.QUOTE, instrument=inst))
                last = float(getattr(quote, "last", 0) or 0)
                if last > 0:
                    e["spot_rate"] = last
                    live_hits += 1
                else:
                    failed.append(e["currency"])
            except Exception:
                failed.append(e["currency"])

        await asyncio.gather(*(_q(e) for e in exposures))
        return (failed, live_hits > 0)


def _normalize_pair(raw: str) -> str:
    value = raw.upper().strip().replace("/", "").replace("-", "").replace(" ", "")
    value = value.replace("=X", "")
    if len(value) >= 6 and value[:3].isalpha() and value[3:6].isalpha():
        return value[:6]
    return "EURUSD"


def _attach_assumed_values(
    data: dict[str, Any], assumed_defaults: list[str],
) -> None:
    """Echo the concrete default values behind ``assumed_defaults``.

    The assumptions list names which inputs fell back to the engine default;
    this adds the actual numbers so any UI/API caller can label them without
    duplicating the constants.
    """
    if not assumed_defaults:
        return
    values: dict[str, float] = {}
    if "notional" in assumed_defaults:
        values["notional"] = DEFAULT_NOTIONAL
    if "base_rate" in assumed_defaults:
        values["base_rate"] = DEFAULT_BASE_RATE
    if "home_rate" in assumed_defaults:
        values["home_rate"] = DEFAULT_HOME_RATE
    if "bid_ask_pips" in assumed_defaults:
        values["bid_ask_pips"] = DEFAULT_BID_ASK_PIPS
    data["assumed_values"] = values


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _manifest_scenario(
    objs: list[FXExposure], rows: list[dict[str, Any]],
    hedge_ratio: float, shock: float, bid_ask_pips: float,
) -> dict[str, float]:
    """Manifest formulas per exposure, written onto each row and summed.

    shock is a decimal spot move (positive = base appreciates vs quote), so
    the move is spot * shock. Hedge cost is hedge_notional * pips * pip_size
    in home currency (pip 0.0001; 0.01 when the home/quote currency is JPY).
    """
    totals = {"pnl_unhedged": 0.0, "pnl_hedged": 0.0, "hedge_cost": 0.0}
    for exp, row in zip(objs, rows):
        sign = SIDE_SIGN[exp.side]
        pip_size = 0.01 if exp.home_currency == "JPY" else 0.0001
        hedge_n = exp.notional * hedge_ratio
        residual = exp.notional - hedge_n
        move = exp.spot_rate * shock
        cost = hedge_n * bid_ask_pips * pip_size
        pnl_unhedged = sign * exp.notional * move
        pnl_hedged = sign * residual * move - cost
        row.update({
            "spot": exp.spot_rate,
            "exposure_notional": exp.notional,
            "hedge_notional": hedge_n,
            "residual_notional": residual,
            "pnl_unhedged": pnl_unhedged,
            "pnl_hedged": pnl_hedged,
            "hedge_cost": cost,
            "bid_ask_pips": bid_ask_pips,
        })
        totals["pnl_unhedged"] += pnl_unhedged
        totals["pnl_hedged"] += pnl_hedged
        totals["hedge_cost"] += cost
    return totals


def _input_error(code: str, reason: str) -> FunctionResult:
    return FunctionResult(
        code=code,
        instrument=None,
        data={"status": "input_error", "reason": reason, "rows": [], "source_mode": "manual_exposure"},
        sources=["manual_exposure"],
        warnings=[],
    )


def _missing(value: Any) -> bool:
    return value is None or value == ""


def _rate(value: Any, default: float) -> float:
    return default if _missing(value) else float(value)


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
            sign = SIDE_SIGN[exp.side]
            hedged_notional = exp.notional * hedge_ratio
            residual = exp.notional - hedged_notional
            shocked_spot = exp.spot_rate * (1 + shock)
            carry = sign * (fwd - exp.spot_rate) * hedged_notional
            total += sign * residual * (shocked_spot - exp.spot_rate) + carry
            unhedged += sign * exp.notional * (shocked_spot - exp.spot_rate)
        curve.append({
            "shock_pct": round(shock * 100, 2),
            "total_pnl": total,
            "unhedged_pnl": unhedged,
            "days": days,
            "hedge_ratio": hedge_ratio,
        })
    return curve
