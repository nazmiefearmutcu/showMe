"""WHAL - cross-market whale / large-flow monitor.

The native Whale Alert transfer feed requires an account API key. WHAL should
still be useful without that key, so it now routes to no-key public data:

* Crypto: Binance public aggregate trades, spot first then USD-M futures.
* US equities: SEC EDGAR recent ownership/insider filing signals.
* Equity/ETF/commodity/fx/index: Yahoo chart volume or price-impulse proxy.

Rows always disclose the source mode. Non-crypto rows are explicitly labelled as
large-flow proxies, not on-chain transfer events.
"""

from __future__ import annotations

import asyncio
import math
import statistics
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


BINANCE_SPOT = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions"
USER_AGENT = "showMe-WHAL/1.0 contact: local-terminal"


@FunctionRegistry.register
class WHALFunction(BaseFunction):
    code = "WHAL"
    name = "Whale Alerts"
    asset_classes = (
        AssetClass.CRYPTO,
        AssetClass.EQUITY,
        AssetClass.ETF,
        AssetClass.REIT,
        AssetClass.FUND,
        AssetClass.FX,
        AssetClass.COMMODITY,
        AssetClass.DERIVATIVE,
        AssetClass.INDEX,
    )
    category = "misc"
    description = "Cross-market large trades, filings, volume spikes, and liquidity impulses."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbol = _resolve_symbol(instrument, params)
        market = _resolve_market(instrument, params, symbol)
        chain = str(params.get("chain") or _chain_from_symbol(symbol)).upper()
        threshold_usd = max(0.0, _to_float(params.get("threshold_usd"), 1_000_000.0) or 0.0)
        limit = max(5, min(int(_to_float(params.get("limit"), 25) or 25), 100))
        trade_limit = max(100, min(int(_to_float(params.get("trade_limit"), 1000) or 1000), 1000))
        lookback_hours = max(1, min(int(_to_float(params.get("lookback_hours"), 24) or 24), 168))
        interval = str(params.get("interval") or ("1m" if market != "FX" else "5m")).lower()
        timeout = max(3.0, min(_to_float(params.get("timeout"), 8.0) or 8.0, 15.0))

        warnings: list[str] = []
        sources: list[str] = []
        payload: dict[str, Any]

        if market == "CRYPTO":
            payload, sources, warnings = await _crypto_whales(
                symbol=symbol,
                chain=chain,
                threshold_usd=threshold_usd,
                row_limit=limit,
                trade_limit=trade_limit,
                timeout=timeout,
            )
        else:
            payload, sources, warnings = await _market_flow_proxy(
                symbol=symbol,
                market=market,
                threshold_usd=threshold_usd,
                row_limit=limit,
                lookback_hours=lookback_hours,
                interval=interval,
                timeout=timeout,
            )

        payload.update(
            {
                "symbol": symbol,
                "market": market,
                "chain": chain if market == "CRYPTO" else None,
                "threshold_usd": threshold_usd,
                "lookback_hours": lookback_hours,
                "interval": interval,
                "whale_alert_api": "not_required_for_current_source",
                "native_transfer_feed": "not_configured",
                "methodology": _methodology(market),
                "field_dictionary": _field_dictionary(),
            }
        )
        if warnings:
            payload["provider_warnings"] = warnings[:8]
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=payload,
            sources=sources or ["cross_market_whale_proxy"],
            warnings=warnings,
            metadata={"market": market, "source_policy": "no_paid_api_required"},
        )


async def _crypto_whales(
    *,
    symbol: str,
    chain: str,
    threshold_usd: float,
    row_limit: int,
    trade_limit: int,
    timeout: float,
) -> tuple[dict[str, Any], list[str], list[str]]:
    pair = _binance_pair(symbol, chain)
    warnings: list[str] = []
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
        for venue, base, trades_path, kline_path, ticker_path in (
            ("spot", BINANCE_SPOT, "/api/v3/aggTrades", "/api/v3/klines", "/api/v3/ticker/24hr"),
            ("usd_m_futures", BINANCE_FUTURES, "/fapi/v1/aggTrades", "/fapi/v1/klines", "/fapi/v1/ticker/24hr"),
        ):
            try:
                trades_res, klines_res, ticker_res = await asyncio.gather(
                    client.get(f"{base}{trades_path}", params={"symbol": pair, "limit": trade_limit}),
                    client.get(f"{base}{kline_path}", params={"symbol": pair, "interval": "1m", "limit": 120}),
                    client.get(f"{base}{ticker_path}", params={"symbol": pair}),
                    return_exceptions=True,
                )
                trades = _json_or_raise(trades_res, f"binance {venue} aggTrades")
                klines = _json_or_empty(klines_res)
                ticker = _json_or_empty(ticker_res)
            except Exception as exc:
                warnings.append(str(exc))
                continue

            rows = _shape_binance_trades(trades, pair, venue, threshold_usd, row_limit)
            history = _shape_binance_klines(klines, pair, venue)
            if rows or history:
                threshold_hits = sum(1 for row in rows if row.get("threshold_crossed"))
                return (
                    {
                        "status": "ok",
                        "signal_state": "threshold_cross" if threshold_hits else "no_threshold_cross",
                        "provider": f"binance_{venue}",
                        "provider_symbol": pair,
                        "rows": rows,
                        "history": history,
                        "cards": [
                            {"label": "Provider", "value": f"Binance {venue}"},
                            {"label": "Rows", "value": len(rows)},
                            {"label": "Threshold hits", "value": threshold_hits},
                            {"label": "24h quote volume", "value": _to_float(ticker.get("quoteVolume"))},
                        ],
                        "summary": (
                            f"{pair} latest Binance {venue} aggregate trades. "
                            f"{threshold_hits} trade(s) crossed ${threshold_usd:,.0f}."
                        ),
                    },
                    [f"binance_{venue}_public"],
                    warnings,
                )

    return (
        {
            "status": "provider_unavailable",
            "provider": "binance_public",
            "provider_symbol": pair,
            "rows": [],
            "history": [],
            "cards": [
                {"label": "Provider", "value": "Binance public"},
                {"label": "Rows", "value": 0},
                {"label": "Threshold hits", "value": 0},
            ],
            "summary": f"No usable public Binance trade rows were returned for {pair}.",
            "next_actions": [
                "Check that the symbol is listed on Binance spot or USD-M futures.",
                "Try BTCUSDT, ETHUSDT, SOLUSDT, or lower the threshold.",
            ],
        },
        ["binance_public"],
        warnings,
    )


async def _market_flow_proxy(
    *,
    symbol: str,
    market: str,
    threshold_usd: float,
    row_limit: int,
    lookback_hours: int,
    interval: str,
    timeout: float,
) -> tuple[dict[str, Any], list[str], list[str]]:
    yahoo_symbol = _yahoo_symbol(symbol, market)
    warnings: list[str] = []
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
        chart_task = asyncio.create_task(_fetch_yahoo_bars(client, yahoo_symbol, interval, lookback_hours))
        sec_task = (
            asyncio.create_task(_fetch_sec_filing_rows(client, symbol, row_limit))
            if market in {"EQUITY", "ETF", "REIT", "FUND"} and _looks_us_symbol(symbol)
            else None
        )
        try:
            bars = await chart_task
        except Exception as exc:
            bars = []
            warnings.append(f"yahoo_chart: {exc}")
        try:
            sec_rows = await sec_task if sec_task else []
        except Exception as exc:
            sec_rows = []
            warnings.append(f"sec_edgar: {exc}")

    flow_rows, history = _shape_market_bars(
        bars=bars,
        symbol=symbol,
        yahoo_symbol=yahoo_symbol,
        market=market,
        threshold_usd=threshold_usd,
        row_limit=row_limit,
    )
    rows = (sec_rows + flow_rows)[:row_limit]
    threshold_hits = sum(1 for row in rows if row.get("threshold_crossed"))
    status = "ok" if rows else "provider_unavailable"
    sources = ["yahoo_chart_public"]
    if sec_rows:
        sources.append("sec_edgar_public")
    return (
        {
            "status": status,
            "signal_state": "threshold_cross" if threshold_hits else "no_threshold_cross",
            "provider": "cross_market_public_proxy",
            "provider_symbol": yahoo_symbol,
            "rows": rows,
            "history": history,
            "cards": [
                {"label": "Provider", "value": "Yahoo chart + SEC" if sec_rows else "Yahoo chart"},
                {"label": "Rows", "value": len(rows)},
                {"label": "Threshold hits", "value": threshold_hits},
                {"label": "Proxy mode", "value": _proxy_mode(market, bars)},
            ],
            "summary": _market_summary(symbol, market, rows, threshold_hits, threshold_usd),
            "next_actions": [
                "For true broker-level prints, connect a licensed market-tape or broker feed.",
                "For WHAL without paid feeds, ShowMe labels these rows as volume/filing/impulse proxies.",
            ],
        },
        sources,
        warnings,
    )


def _shape_binance_trades(
    trades: Any,
    pair: str,
    venue: str,
    threshold_usd: float,
    row_limit: int,
) -> list[dict[str, Any]]:
    if not isinstance(trades, list):
        return []
    parsed: list[dict[str, Any]] = []
    for item in trades:
        if not isinstance(item, dict):
            continue
        price = _to_float(item.get("p"))
        qty = _to_float(item.get("q"))
        if price is None or qty is None:
            continue
        value = price * qty
        ts = _epoch_ms_to_iso(item.get("T"))
        threshold_crossed = value >= threshold_usd if threshold_usd else True
        parsed.append(
            {
                "alert_type": "crypto_large_trade" if threshold_crossed else "crypto_top_trade",
                "market": "CRYPTO",
                "symbol": pair,
                "venue": f"binance_{venue}",
                "timestamp": ts,
                "price": round(price, 10),
                "amount": round(qty, 10),
                "usd_value": round(value, 2),
                "threshold_usd": threshold_usd,
                "threshold_crossed": threshold_crossed,
                "direction": "sell_initiated" if item.get("m") else "buy_initiated",
                "severity": _severity(value, threshold_usd),
                "source_mode": f"binance_{venue}_aggtrades",
                "explanation": "Public aggregate trade notional from Binance; this is exchange trade flow, not wallet-label transfer data.",
            }
        )
    parsed.sort(key=lambda row: float(row.get("usd_value") or 0), reverse=True)
    crossed = [row for row in parsed if row.get("threshold_crossed")]
    return (crossed or parsed)[:row_limit]


def _shape_binance_klines(klines: Any, pair: str, venue: str) -> list[dict[str, Any]]:
    if not isinstance(klines, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in klines[-60:]:
        if not isinstance(item, list) or len(item) < 8:
            continue
        rows.append(
            {
                "timestamp": _epoch_ms_to_iso(item[0]),
                "symbol": pair,
                "close": _to_float(item[4]),
                "volume": _to_float(item[5]),
                "quote_volume": _to_float(item[7]),
                "source_mode": f"binance_{venue}_klines",
            }
        )
    return rows


async def _fetch_yahoo_bars(
    client: httpx.AsyncClient,
    yahoo_symbol: str,
    interval: str,
    lookback_hours: int,
) -> list[dict[str, Any]]:
    ranges = ["1d", "5d"] if lookback_hours <= 24 else ["5d", "1mo"]
    intervals = [interval, "5m", "15m", "1d"]
    last_error: Exception | None = None
    for range_value in ranges:
        for interval_value in intervals:
            try:
                response = await client.get(
                    f"{YAHOO_CHART}/{yahoo_symbol}",
                    params={
                        "range": range_value,
                        "interval": interval_value,
                        "includePrePost": "true",
                        "events": "div,splits",
                    },
                )
                response.raise_for_status()
                result = (((response.json() or {}).get("chart") or {}).get("result") or [None])[0]
                if not isinstance(result, dict):
                    continue
                timestamps = result.get("timestamp") or []
                quote = (((result.get("indicators") or {}).get("quote") or [None])[0]) or {}
                bars: list[dict[str, Any]] = []
                for idx, ts in enumerate(timestamps):
                    close = _nth_float(quote.get("close"), idx)
                    if close is None:
                        continue
                    bars.append(
                        {
                            "timestamp": datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(),
                            "open": _nth_float(quote.get("open"), idx),
                            "high": _nth_float(quote.get("high"), idx),
                            "low": _nth_float(quote.get("low"), idx),
                            "close": close,
                            "volume": _nth_float(quote.get("volume"), idx),
                            "interval": interval_value,
                            "range": range_value,
                        }
                    )
                if bars:
                    cutoff = time.time() - lookback_hours * 3600
                    fresh = [
                        row for row in bars
                        if _iso_timestamp(row.get("timestamp")) >= cutoff
                    ]
                    return fresh or bars[-120:]
            except Exception as exc:
                last_error = exc
                continue
    if last_error:
        raise last_error
    return []


def _shape_market_bars(
    *,
    bars: list[dict[str, Any]],
    symbol: str,
    yahoo_symbol: str,
    market: str,
    threshold_usd: float,
    row_limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not bars:
        return [], []
    multiplier = _contract_multiplier(symbol, market)
    enriched: list[dict[str, Any]] = []
    prev_close: float | None = None
    notionals: list[float] = []
    returns: list[float] = []
    for row in bars:
        close = _to_float(row.get("close"))
        volume = _to_float(row.get("volume"))
        notional = close * volume * multiplier if close is not None and volume and multiplier else None
        ret_pct = None
        if prev_close and close:
            ret_pct = (close / prev_close - 1.0) * 100.0
            returns.append(abs(ret_pct))
        if notional:
            notionals.append(notional)
        prev_close = close or prev_close
        enriched.append({**row, "notional_usd": notional, "return_pct": ret_pct})

    baseline_notional = _median([v for v in notionals if v > 0])
    baseline_return = _median([v for v in returns if v > 0])
    rows: list[dict[str, Any]] = []
    for row in enriched:
        notional = _to_float(row.get("notional_usd"))
        ret_pct = _to_float(row.get("return_pct"))
        notional_ratio = (notional / baseline_notional) if (notional and baseline_notional) else None
        impulse_ratio = (abs(ret_pct) / baseline_return) if (ret_pct is not None and baseline_return) else None
        threshold_crossed = bool(notional is not None and notional >= threshold_usd)
        anomaly = (
            threshold_crossed
            or (notional_ratio is not None and notional_ratio >= 2.0)
            or (impulse_ratio is not None and impulse_ratio >= 2.5)
        )
        if not anomaly:
            continue
        source_mode = "yahoo_volume_notional_proxy" if notional is not None else "yahoo_price_impulse_proxy"
        rows.append(
            {
                "alert_type": "large_volume_proxy" if notional is not None else "liquidity_impulse_proxy",
                "market": market,
                "symbol": symbol,
                "provider_symbol": yahoo_symbol,
                "timestamp": row.get("timestamp"),
                "price": row.get("close"),
                "volume": row.get("volume"),
                "usd_value": round(notional, 2) if notional is not None else None,
                "threshold_usd": threshold_usd,
                "threshold_crossed": threshold_crossed,
                "notional_vs_median": round(notional_ratio, 2) if notional_ratio is not None else None,
                "impulse_vs_median": round(impulse_ratio, 2) if impulse_ratio is not None else None,
                "return_pct": round(ret_pct, 4) if ret_pct is not None else None,
                "direction": "up" if (ret_pct or 0) > 0 else "down" if (ret_pct or 0) < 0 else "flat",
                "severity": _severity(notional or (abs(ret_pct or 0) * 1_000_000), threshold_usd),
                "source_mode": source_mode,
                "explanation": (
                    "Public chart proxy. This is not a broker tape print; it flags unusually large "
                    "bar notional/volume or, when volume is unavailable, an unusual price impulse."
                ),
            }
        )
    if not rows:
        rows = _top_market_rows(enriched, symbol, yahoo_symbol, market, threshold_usd, row_limit)
    rows.sort(
        key=lambda row: (
            float(row.get("usd_value") or 0),
            float(row.get("impulse_vs_median") or 0),
        ),
        reverse=True,
    )
    history = [
        {
            "timestamp": row.get("timestamp"),
            "symbol": symbol,
            "close": row.get("close"),
            "volume": row.get("volume"),
            "notional_usd": round(row["notional_usd"], 2) if row.get("notional_usd") else None,
            "return_pct": row.get("return_pct"),
            "source_mode": "yahoo_chart_public",
        }
        for row in enriched[-80:]
    ]
    return rows[:row_limit], history


def _top_market_rows(
    enriched: list[dict[str, Any]],
    symbol: str,
    yahoo_symbol: str,
    market: str,
    threshold_usd: float,
    row_limit: int,
) -> list[dict[str, Any]]:
    ordered = sorted(
        enriched,
        key=lambda row: (float(row.get("notional_usd") or 0), abs(float(row.get("return_pct") or 0))),
        reverse=True,
    )
    rows: list[dict[str, Any]] = []
    for row in ordered[:row_limit]:
        notional = _to_float(row.get("notional_usd"))
        ret_pct = _to_float(row.get("return_pct"))
        rows.append(
            {
                "alert_type": "top_volume_window" if notional is not None else "top_impulse_window",
                "market": market,
                "symbol": symbol,
                "provider_symbol": yahoo_symbol,
                "timestamp": row.get("timestamp"),
                "price": row.get("close"),
                "volume": row.get("volume"),
                "usd_value": round(notional, 2) if notional is not None else None,
                "threshold_usd": threshold_usd,
                "threshold_crossed": bool(notional is not None and notional >= threshold_usd),
                "return_pct": round(ret_pct, 4) if ret_pct is not None else None,
                "direction": "up" if (ret_pct or 0) > 0 else "down" if (ret_pct or 0) < 0 else "flat",
                "severity": _severity(notional or (abs(ret_pct or 0) * 1_000_000), threshold_usd),
                "source_mode": "yahoo_chart_top_window",
                "explanation": "Largest public chart window observed; no threshold-crossing flow was found.",
            }
        )
    return rows


async def _fetch_sec_filing_rows(
    client: httpx.AsyncClient,
    symbol: str,
    row_limit: int,
) -> list[dict[str, Any]]:
    response = await client.get(SEC_TICKERS, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    tickers = response.json() or {}
    clean_symbol = symbol.upper().split(".")[0]
    cik: int | None = None
    company_name = ""
    for item in tickers.values() if isinstance(tickers, dict) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("ticker") or "").upper() == clean_symbol:
            cik = int(item.get("cik_str"))
            company_name = str(item.get("title") or "")
            break
    if not cik:
        return []
    sub = await client.get(f"{SEC_SUBMISSIONS}/CIK{cik:010d}.json", headers={"User-Agent": USER_AGENT})
    sub.raise_for_status()
    recent = (sub.json() or {}).get("filings", {}).get("recent", {})
    forms = recent.get("form") or []
    filing_dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []
    rows: list[dict[str, Any]] = []
    interesting = {"3", "4", "5", "13F-HR", "SC 13D", "SC 13G", "13D", "13G"}
    for idx, form in enumerate(forms):
        form = str(form or "").upper()
        if form not in interesting:
            continue
        accession = str(_nth(accessions, idx) or "").replace("-", "")
        doc = str(_nth(docs, idx) or "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}" if accession and doc else None
        rows.append(
            {
                "alert_type": "sec_ownership_filing",
                "market": "EQUITY",
                "symbol": clean_symbol,
                "company": company_name,
                "timestamp": _nth(filing_dates, idx),
                "form": form,
                "threshold_usd": None,
                "threshold_crossed": False,
                "severity": "high" if form in {"SC 13D", "SC 13G", "13D", "13G"} else "medium",
                "source_mode": "sec_edgar_submissions",
                "url": url,
                "explanation": "Official SEC ownership/insider filing signal. It is a whale activity clue, not a live trade print.",
            }
        )
        if len(rows) >= max(3, row_limit // 2):
            break
    return rows


def _resolve_symbol(instrument: Instrument | None, params: dict[str, Any]) -> str:
    raw = params.get("symbol") or (instrument.symbol if instrument else None) or params.get("chain") or "BTCUSDT"
    symbol = str(raw).strip().upper().replace(" ", "")
    if symbol in {"BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA"}:
        return f"{symbol}USDT"
    return symbol


def _resolve_market(instrument: Instrument | None, params: dict[str, Any], symbol: str) -> str:
    raw = params.get("market") or params.get("asset_class")
    if raw:
        value = str(raw).strip().upper()
        aliases = {
            "STOCK": "EQUITY",
            "SHARE": "EQUITY",
            "CRYPTOCURRENCY": "CRYPTO",
            "COIN": "CRYPTO",
            "FUTURE": "COMMODITY",
        }
        return aliases.get(value, value)
    if instrument is not None:
        return instrument.asset_class.value
    return _guess_market(symbol)


def _guess_market(symbol: str) -> str:
    clean = symbol.upper()
    if clean.endswith(("USDT", "USDC", "FDUSD")) or clean in {"BTC", "ETH", "SOL", "BNB"}:
        return "CRYPTO"
    if clean.endswith("=X") or (len(clean) == 6 and clean[:3].isalpha() and clean[3:].isalpha()):
        return "FX"
    if clean.endswith("=F"):
        return "COMMODITY"
    if clean.startswith("^"):
        return "INDEX"
    return "EQUITY"


def _chain_from_symbol(symbol: str) -> str:
    clean = symbol.upper()
    if clean.startswith("ETH"):
        return "ETH"
    if clean.startswith("SOL"):
        return "SOL"
    if clean.startswith("BNB"):
        return "BSC"
    return "BTC"


def _binance_pair(symbol: str, chain: str) -> str:
    clean = symbol.upper().replace("/", "").replace("-", "")
    if clean.endswith("USD") and not clean.endswith("USDT"):
        clean = f"{clean[:-3]}USDT"
    if clean in {"BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA"}:
        return f"{clean}USDT"
    if clean in {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"} or clean.endswith(("USDT", "USDC", "FDUSD")):
        return clean
    return f"{chain.upper()}USDT"


def _yahoo_symbol(symbol: str, market: str) -> str:
    clean = symbol.upper()
    if market == "FX" and not clean.endswith("=X"):
        return f"{clean.replace('/', '').replace('-', '')}=X"
    if market == "CRYPTO":
        for quote in ("USDT", "USDC", "USD"):
            if clean.endswith(quote) and len(clean) > len(quote):
                return f"{clean[:-len(quote)]}-USD"
    return clean


def _contract_multiplier(symbol: str, market: str) -> float:
    if market in {"EQUITY", "ETF", "REIT", "FUND"}:
        return 1.0
    if market in {"FX", "INDEX"}:
        return 0.0
    root = symbol.upper().split("=")[0]
    for prefix, multiplier in {
        "CL": 1000.0,
        "BZ": 1000.0,
        "NG": 10000.0,
        "GC": 100.0,
        "SI": 5000.0,
        "HG": 25000.0,
        "PL": 50.0,
        "PA": 100.0,
        "ZC": 5000.0,
        "ZW": 5000.0,
        "ZS": 5000.0,
    }.items():
        if root.startswith(prefix):
            return multiplier
    return 1.0 if market in {"COMMODITY", "DERIVATIVE"} else 0.0


def _methodology(market: str) -> str:
    if market == "CRYPTO":
        return (
            "WHAL uses Binance public aggregate trades and 1-minute klines for crypto symbols. "
            "A row is a large exchange trade or the largest observed trade if the USD threshold was not crossed. "
            "It is not a wallet-labelled Whale Alert transfer unless a native transfer feed is separately configured."
        )
    return (
        "WHAL uses no-key public market data outside crypto. Equity/ETF/commodity rows flag large bar notional "
        "or unusual volume versus the recent median; FX/index rows use price-impulse proxies when volume is missing. "
        "US stocks may include SEC EDGAR ownership/insider filing signals. These rows are market-flow proxies, "
        "not licensed tape prints or on-chain transfers."
    )


def _field_dictionary() -> dict[str, str]:
    return {
        "alert_type": "Type of whale/flow signal: crypto trade, large-volume proxy, liquidity impulse, or SEC filing.",
        "usd_value": "Estimated USD notional where the public source supports it.",
        "threshold_crossed": "True when estimated notional is at or above the requested threshold.",
        "source_mode": "Exact public source/method used for the row.",
        "notional_vs_median": "Bar notional divided by recent median notional.",
        "impulse_vs_median": "Absolute return impulse divided by recent median absolute return.",
        "explanation": "Plain-English caveat so proxy rows are not confused with real transfer feeds.",
    }


def _market_summary(symbol: str, market: str, rows: list[dict[str, Any]], hits: int, threshold: float) -> str:
    if not rows:
        return f"No public WHAL proxy rows were returned for {symbol} ({market})."
    if hits:
        return f"{symbol} has {hits} public row(s) above ${threshold:,.0f}."
    return f"{symbol} returned {len(rows)} public WHAL proxy row(s), but none crossed ${threshold:,.0f}."


def _proxy_mode(market: str, bars: list[dict[str, Any]]) -> str:
    if market in {"FX", "INDEX"}:
        return "price_impulse"
    if any(_to_float(row.get("volume")) for row in bars):
        return "volume_notional"
    return "price_impulse"


def _severity(value: float | None, threshold_usd: float) -> str:
    if value is None:
        return "medium"
    if threshold_usd <= 0:
        return "high"
    if value >= threshold_usd * 5:
        return "critical"
    if value >= threshold_usd:
        return "high"
    if value >= threshold_usd * 0.25:
        return "medium"
    return "low"


def _json_or_raise(result: Any, label: str) -> Any:
    if isinstance(result, Exception):
        raise RuntimeError(f"{label}: {result}")
    if not isinstance(result, httpx.Response):
        raise RuntimeError(f"{label}: invalid response")
    if result.status_code != 200:
        raise RuntimeError(f"{label}: HTTP {result.status_code} {result.text[:160]}")
    return result.json()


def _json_or_empty(result: Any) -> Any:
    if isinstance(result, Exception) or not isinstance(result, httpx.Response) or result.status_code != 200:
        return {}
    try:
        return result.json()
    except Exception:
        return {}


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, "", "N/D"):
            return default
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return default
        return out
    except Exception:
        return default


def _nth_float(values: Any, idx: int) -> float | None:
    return _to_float(_nth(values, idx))


def _nth(values: Any, idx: int) -> Any:
    try:
        return values[idx]
    except Exception:
        return None


def _median(values: list[float]) -> float | None:
    clean = [float(v) for v in values if v is not None and v > 0]
    if not clean:
        return None
    return statistics.median(clean)


def _epoch_ms_to_iso(value: Any) -> str | None:
    ts = _to_float(value)
    if ts is None:
        return None
    return datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat()


def _iso_timestamp(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _looks_us_symbol(symbol: str) -> bool:
    clean = symbol.upper()
    return clean.replace(".", "").isalpha() and 1 <= len(clean) <= 5


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "live"}
