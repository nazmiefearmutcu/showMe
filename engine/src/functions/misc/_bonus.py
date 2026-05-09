"""Bonus fonksiyonlar — Plan §26.2 'Spec'te olmayan' davetine cevap.

LITM — Litigation Monitor (SEC EDGAR 8-K Item 1.03 / 1.04 + 10-Q legal proceedings)
MOSS — Most Volatile (annualized vol ranking)
CHGS — Chart Studies preset (TECH'in hızlı çağrı sürümü)
APPL — Applicable Industry/Sector codes (GICS lookup)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.functions.equity._common import EXCHANGE_LEGEND, reference_profile


@FunctionRegistry.register
class LITMFunction(BaseFunction):
    """LITM — Litigation Monitor."""
    code = "LITM"
    name = "Litigation Monitor"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"
    description = "Recent 8-K Item 1.03/1.04/3.03 filings — bankruptcy, mine safety, security holder rights."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        live = _truthy(params.get("live_litigation") or params.get("live_filings") or params.get("live"))
        if not live or instrument.asset_class.value != "EQUITY" or not self.deps.sec_edgar:
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=_fallback_litm(instrument),
                                  sources=["litigation_monitor_model"],
                                  metadata={"live": False})
        from src.functions.equity.cact import CACTFunction
        cact = CACTFunction(self.deps)
        timeout = max(1.0, min(float(params.get("sec_timeout", 3)), 5.0))
        res = await cact.execute(instrument=instrument, sec_timeout=timeout,
                                 yfinance_timeout=max(1.0, min(float(params.get("yfinance_timeout", 3)), 5.0)),
                                 max_documents=params.get("max_documents", 1))
        events = (res.data or {}).get("events_8k", []) or []
        # Filter for litigation/governance items.
        keep = {"1.03", "1.04", "3.03", "5.02", "5.03", "5.07", "8.01"}
        litm = [e for e in events if e.get("code") in keep]
        rows = [{
            "symbol": instrument.symbol,
            "event_type": e.get("category") or "8-K item",
            "item_code": e.get("code"),
            "filing_date": e.get("filing_date") or e.get("report_date"),
            "severity": "review",
            "source_mode": "sec_edgar_8k",
            "accession": e.get("accession"),
            "document": e.get("document"),
        } for e in litm]
        if not rows:
            rows = [{
                "symbol": instrument.symbol,
                "event_type": "no_litigation_event_found",
                "item_code": None,
                "filing_date": None,
                "severity": "none",
                "source_mode": "sec_edgar_no_matching_8k_item",
                "all_8k_events": len(events),
            }]
        return FunctionResult(code=self.code, instrument=instrument,
                              data={"status": "ok" if litm else "no_matching_event",
                                     "rows": rows,
                                     "litigation_filings": litm,
                                     "all_8k_events": len(events),
                                     "methodology": "LITM filters recent SEC 8-K event rows for litigation/governance-relevant items 1.03, 1.04, 3.03, 5.02, 5.03, 5.07, and 8.01. No-event rows are labelled rather than presented as a legal case.",
                                     "field_dictionary": {
                                         "item_code": "SEC 8-K item code.",
                                         "event_type": "Normalized litigation/governance category.",
                                         "severity": "ShowMe review flag, not legal advice.",
                                         "source_mode": "SEC evidence state for the row.",
                                     }},
                              sources=res.sources or ["litigation_monitor_model"],
                              metadata={"provider_errors": (res.metadata or {}).get("provider_errors", [])})


def _fallback_litm(instrument: Instrument) -> dict[str, Any]:
    asset_class = instrument.asset_class.value
    status = "local_litigation_model" if asset_class == "EQUITY" else f"not_applicable_for_{asset_class.lower()}"
    return {
        "status": "provider_unavailable" if asset_class == "EQUITY" else "not_applicable",
        "rows": [{
            "symbol": instrument.symbol,
            "event_type": "provider_unavailable",
            "item_code": None,
            "filing_date": None,
            "severity": "unknown",
            "source_mode": status,
        }],
        "litigation_filings": [{
            "symbol": instrument.symbol,
            "code": None,
            "category": "litigation",
            "status": status,
        }],
        "all_8k_events": 0,
        "methodology": "LITM requires SEC 8-K filing/event rows and filters them by litigation/governance item code.",
    }


@FunctionRegistry.register
class MOSSFunction(BaseFunction):
    """MOSS — Most Volatile (realised vol ranking across a universe)."""
    code = "MOSS"
    name = "Most Volatile"
    category = "screen"
    description = "Realised volatility leaderboard across watchlist or universe."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbols = _parse_symbol_list(params.get("universe") or params.get("symbols") or [
            "AAPL", "TSLA", "NVDA", "META", "AMZN", "MSFT", "GOOGL",
            "JPM", "V", "WMT", "PG", "BTCUSDT", "ETHUSDT",
        ])
        if instrument and instrument.symbol not in symbols:
            symbols.insert(0, instrument.symbol)
        symbols = list(dict.fromkeys(str(s).upper() for s in symbols if str(s).strip()))
        days = max(20, min(int(params.get("days", 90) or 90), 365 * 3))
        limit = max(1, min(int(params.get("limit", len(symbols)) or len(symbols)), 200))
        if not _truthy(params.get("live_screen") or params.get("live")):
            rows = _moss_template(symbols, days)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_moss_payload(rows[:limit], [], symbols, days, live=False),
                sources=["volatility_model"],
                metadata={"universe_size": len(symbols), "days": days, "live": False},
            )
        if not self.deps.yfinance:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_moss_unavailable(symbols, days, "yfinance provider is unavailable"),
                sources=["no_live_source"],
                metadata={"universe_size": len(symbols), "days": days, "live": False, "fallback": True},
            )
        timeout = float(params.get("yfinance_timeout", 8))

        async def _vol(s):
            try:
                inst = await self.deps.symbol_registry.resolve(s) if self.deps.symbol_registry else None
                if not inst:
                    inst = Instrument(symbol=s, asset_class=AssetClass.EQUITY)
                df = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.OHLCV,
                        instrument=inst,
                        start=datetime.utcnow() - timedelta(days=days),
                        interval="1d",
                    )),
                    timeout=timeout,
                )
                if df.empty:
                    return {"symbol": s, "error": "empty price history"}
                rets = df["close"].pct_change().dropna()
                if rets.empty:
                    return {"symbol": s, "error": "not enough returns"}
                vol = float(rets.std() * (252 ** 0.5))
                return {
                    "row": {
                        "symbol": s,
                        "asset_class": inst.asset_class.value if inst else "EQUITY",
                        "vol_annualized": vol,
                        "vol": vol,
                        "vol_pct": vol * 100,
                        "samples": int(len(rets)),
                        "last_close": float(df["close"].iloc[-1]),
                        "start": _date_label(df.index[0]),
                        "end": _date_label(df.index[-1]),
                    },
                    "history": _moss_history(df, s),
                }
            except Exception as exc:
                return {"symbol": s, "error": str(exc)}

        results = await asyncio.gather(*(_vol(s) for s in symbols))
        provider_errors = [
            f"{r.get('symbol')}: {r.get('error')}"
            for r in results
            if isinstance(r, dict) and r.get("error")
        ]
        good = [r for r in results if isinstance(r, dict) and isinstance(r.get("row"), dict)]
        rows = [r["row"] for r in good]
        rows.sort(key=lambda x: x["vol_annualized"], reverse=True)
        if not rows:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_moss_unavailable(symbols, days, "no symbols returned usable price history"),
                sources=["no_live_source"],
                metadata={"universe_size": len(symbols), "days": days, "provider_errors": provider_errors},
            )
        histories = {r["row"]["symbol"]: r.get("history", []) for r in good}
        top_symbol = rows[0]["symbol"]
        history = histories.get(top_symbol, [])
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=_moss_payload(rows[:limit], history, symbols, days, live=True),
            sources=["yfinance"],
            metadata={
                "universe_size": len(symbols),
                "days": days,
                "live": True,
                "top_symbol": top_symbol,
                "history_points": len(history),
                "provider_errors": provider_errors[:10],
            },
        )


@FunctionRegistry.register
class CHGSFunction(BaseFunction):
    """CHGS — Chart Studies (preset TECH bundle)."""
    code = "CHGS"
    name = "Chart Studies"
    asset_classes = (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.ETF, AssetClass.FX)
    category = "chart"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        if not _truthy(params.get("live_chart") or params.get("live")):
            rows = _chart_template(instrument.symbol)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "symbol": instrument.symbol,
                    "last": rows[-1]["close"],
                    "rows": rows,
                    "rsi_14": 54.2,
                    "sma_20": rows[-1]["close"] * 0.985,
                    "sma_50": rows[-1]["close"] * 0.962,
                },
                metadata={"alias_of": "TECH", "live": False},
                sources=["showme_chart_model"],
            )
        from src.functions.chart.tech import TECHFunction
        tech = TECHFunction(self.deps)
        result = await tech.execute(instrument=instrument, **params)
        return FunctionResult(
            code=self.code,
            instrument=result.instrument,
            data=result.data,
            metadata={**(result.metadata or {}), "alias_of": "TECH"},
            sources=result.sources,
            warnings=result.warnings,
        )


@FunctionRegistry.register
class APPLFunction(BaseFunction):
    """APPL — Applicable industry/sector taxonomy lookup."""
    code = "APPL"
    name = "Industry Taxonomy"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        live = _truthy(params.get("live_refdata") or params.get("live"))
        if not live or not self.deps.yfinance:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_taxonomy_template(instrument),
                sources=["taxonomy_model"],
                metadata={"live": False},
            )
        timeout = max(1.0, min(float(params.get("yfinance_timeout", 4)), 6.0))
        try:
            rd = await asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.REFDATA,
                    instrument=instrument,
                    extra={"timeout": timeout},
                )),
                timeout=timeout + 1,
            )
        except Exception as exc:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_taxonomy_template(instrument),
                sources=["taxonomy_model"],
                metadata={"live": False, "provider_errors": [f"yfinance: {exc}"]},
            )
        profile = reference_profile(instrument.symbol)
        rows = _taxonomy_rows(instrument, rd.sector, rd.industry, rd.country, rd.currency, rd.exchange, profile)
        return FunctionResult(code=self.code, instrument=instrument,
                              data={"status": "ok",
                                     "sector": rd.sector, "industry": rd.industry,
                                     "country": rd.country, "currency": rd.currency,
                                     "exchange": rd.exchange,
                                     "exchange_name": EXCHANGE_LEGEND.get(str(rd.exchange or ""), rd.exchange),
                                     "rows": rows,
                                     "peers": [{"symbol": s, "peer_set": "reference_sector_peer"} for s in profile.get("peers", [])],
                                     "methodology": "APPL combines live provider sector/industry fields with a labelled taxonomy crosswalk for GICS/NAICS/ICB-style hierarchy where available. Exchange codes are expanded for end-user readability.",
                                     "field_dictionary": {
                                         "level": "Taxonomy level or provider field.",
                                         "classification": "Human-readable classification value.",
                                         "source_mode": "live_yfinance or labelled reference taxonomy crosswalk.",
                                     }},
                              sources=["yfinance"],
                              metadata={"live": True})


def _taxonomy_template(instrument: Instrument) -> dict[str, Any]:
    asset_class = instrument.asset_class.value
    if asset_class == "CRYPTO":
        sector, industry, exchange, currency = "Digital Assets", "Cryptoasset", "Global", "USD"
    elif asset_class == "FX":
        sector, industry, exchange, currency = "Foreign Exchange", "Currency Pair", "OTC", None
    elif asset_class == "COMMODITY":
        sector, industry, exchange, currency = "Commodities", "Futures/Spot Commodity", "Global", "USD"
    elif asset_class in {"EQUITY", "ETF"}:
        sector, industry, exchange, currency = "Equity", "Listed Security", "Exchange", "USD"
    else:
        sector, industry, exchange, currency = "Market", asset_class.title(), "Global", None
    return {
        "status": "reference_taxonomy",
        "sector": sector,
        "industry": industry,
        "country": "Global",
        "currency": currency,
        "exchange": exchange,
        "exchange_name": EXCHANGE_LEGEND.get(exchange, exchange),
        "rows": _taxonomy_rows(instrument, sector, industry, "Global", currency, exchange, reference_profile(instrument.symbol)),
        "methodology": "Fallback taxonomy is labelled as a reference model when live provider classification is unavailable.",
        "field_dictionary": {
            "level": "Taxonomy level or provider field.",
            "classification": "Human-readable classification value.",
            "source_mode": "reference taxonomy fallback.",
        },
    }


def _taxonomy_rows(
    instrument: Instrument,
    sector: Any,
    industry: Any,
    country: Any,
    currency: Any,
    exchange: Any,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = [
        {"level": "Provider sector", "classification": sector, "source_mode": "live_yfinance"},
        {"level": "Provider industry", "classification": industry, "source_mode": "live_yfinance"},
        {"level": "Exchange", "classification": EXCHANGE_LEGEND.get(str(exchange or ""), exchange), "raw_code": exchange, "source_mode": "live_yfinance"},
        {"level": "Country", "classification": country, "source_mode": "live_yfinance"},
        {"level": "Currency", "classification": currency, "source_mode": "live_yfinance"},
    ]
    for key, label in [
        ("gics_sector", "GICS sector"),
        ("gics_industry_group", "GICS industry group"),
        ("gics_industry", "GICS industry"),
        ("gics_sub_industry", "GICS sub-industry"),
        ("naics", "NAICS"),
        ("icb", "ICB"),
    ]:
        value = profile.get(key)
        if value:
            rows.append({"level": label, "classification": value, "source_mode": "reference_taxonomy_crosswalk"})
    if len(rows) <= 5:
        rows.append({"level": "Asset class", "classification": instrument.asset_class.value, "source_mode": "instrument_registry"})
    return rows


def _chart_template(symbol: str) -> list[dict[str, Any]]:
    base = 78000.0 if symbol.upper().endswith(("USDT", "USD")) else 100.0
    return [
        {
            "date": f"template-{idx + 1:02d}",
            "open": round(base * (1 + (idx - 5) * 0.003), 4),
            "high": round(base * (1 + (idx - 5) * 0.003 + 0.008), 4),
            "low": round(base * (1 + (idx - 5) * 0.003 - 0.007), 4),
            "close": round(base * (1 + (idx - 5) * 0.003 + 0.002), 4),
            "volume": 1_000_000 + idx * 75_000,
        }
        for idx in range(10)
    ]


def _parse_symbol_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, (list, tuple, set)):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _moss_payload(
    rows: list[dict[str, Any]],
    history: list[dict[str, Any]],
    symbols: list[str],
    days: int,
    *,
    live: bool,
) -> dict[str, Any]:
    top_symbol = rows[0]["symbol"] if rows else None
    return {
        "rows": rows,
        "history": history,
        "universe": symbols,
        "lookback_days": days,
        "top_symbol": top_symbol,
        "live": live,
        "methodology": (
            "Ranks the selected universe by annualized realized volatility: "
            "std(daily close-to-close returns) * sqrt(252). The chart shows the "
            "rolling 20-session annualized volatility history for the current top symbol."
        ),
        "field_dictionary": {
            "vol_annualized": "Annualized realized volatility as a decimal.",
            "vol_pct": "Annualized realized volatility in percent.",
            "samples": "Number of daily return observations used.",
            "history.vol": "Rolling 20-session annualized realized volatility for the top symbol.",
        },
    }


def _moss_unavailable(symbols: list[str], days: int, reason: str) -> dict[str, Any]:
    return {
        "status": "provider_unavailable",
        "reason": reason,
        "rows": [],
        "history": [],
        "universe": symbols,
        "lookback_days": days,
        "next_actions": ["Check the yfinance provider and rerun with a smaller universe or shorter range."],
        "methodology": "Requires daily close history to compute realized volatility.",
    }


def _moss_history(df: Any, symbol: str) -> list[dict[str, Any]]:
    rets = df["close"].pct_change().dropna()
    window = min(20, max(5, len(rets) // 2))
    rolling = (rets.rolling(window=window).std() * (252 ** 0.5)).dropna()
    rows: list[dict[str, Any]] = []
    for idx, value in rolling.tail(90).items():
        rows.append({
            "date": _date_label(idx),
            "symbol": symbol,
            "vol": float(value),
            "vol_pct": float(value) * 100,
            "window": window,
        })
    return rows


def _date_label(value: Any) -> str:
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)


def _moss_template(symbols: list[str], days: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, symbol in enumerate(dict.fromkeys(symbols)):
        upper = symbol.upper()
        if upper.endswith(("USDT", "USD")) and not upper.endswith(("=F", "USD=X")):
            base_vol = 0.58
            last_close = 78000.0 - idx * 950
            asset_class = "crypto"
        elif upper.endswith("=F"):
            base_vol = 0.26
            last_close = 2350.0 + idx * 11
            asset_class = "commodity"
        elif upper.endswith(("USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD")) and len(upper) == 6:
            base_vol = 0.11
            last_close = 1.08 + idx * 0.01
            asset_class = "fx"
        else:
            base_vol = 0.34
            last_close = 100.0 + idx * 7.5
            asset_class = "equity"
        vol = round(max(0.05, base_vol - idx * 0.012), 4)
        rows.append({
            "symbol": symbol,
            "asset_class": asset_class,
            "vol_annualized": vol,
            "vol": vol,
            "vol_pct": vol * 100,
            "samples": max(20, min(days, 252) - 1),
            "last_close": round(last_close, 4),
        })
    rows.sort(key=lambda item: item["vol_annualized"], reverse=True)
    return rows


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
