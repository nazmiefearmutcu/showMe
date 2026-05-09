"""yfinance adapter — kapsamlı equity/ETF/index/fx/commodity data source.

DATA PIPELINE:
    Source: yfinance (Yahoo Finance via requests)
    Cache:  in-memory adapter cache (60s)
    Fallback: stooq → polygon → finnhub
    Latency budget: <800ms warm, <3s cold

Yahoo public endpoints throttle aggressively. We keep an internal token
bucket and a circuit breaker.
"""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pandas as pd

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError, RateLimitError
)
from showme.engine.core.instrument import Instrument
from showme.engine.core.quote import Quote, utcnow
from showme.engine.core.refdata import ReferenceData
from showme.engine.utils.throttle import TokenBucket, CircuitBreaker


_INTERVAL_MAP: dict[str, str] = {
    "1m": "1m", "2m": "2m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "60m", "60m": "60m", "90m": "90m",
    "1d": "1d", "1d_unadj": "1d", "1w": "1wk", "1wk": "1wk",
    "1mo": "1mo", "3mo": "3mo",
    "4h": "60m",        # Yahoo lacks native 4h — caller resamples
    "1y": "1mo",
}


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "N/D"):
            return None
        return float(value)
    except Exception:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _json_scalar(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, pd.Timestamp):
        return _as_utc(value.to_pydatetime()).isoformat()
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _frame_records(frame: Any, *, limit: int | None = None) -> list[dict[str, Any]]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    df = frame.copy()
    if limit is not None:
        df = df.head(limit)
    df = df.reset_index()
    records: list[dict[str, Any]] = []
    for raw in df.to_dict(orient="records"):
        records.append({str(k): _json_scalar(v) for k, v in raw.items()})
    return records


class YFinanceAdapter(BaseDataSource):
    """yfinance is a read-only, anonymous-friendly Yahoo wrapper.

    We import yfinance lazily inside calls so a deployment that never uses
    equity (e.g. crypto-only) doesn't pay the dependency cost at boot.
    """
    name = "yfinance"
    supported_kinds = (
        DataKind.QUOTE, DataKind.OHLCV, DataKind.REFDATA,
        DataKind.FUNDAMENTALS, DataKind.EVENTS, DataKind.HOLDINGS,
        DataKind.OPTIONS_CHAIN, DataKind.NEWS,
    )
    rate_limit_rps = 2.0
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._bucket = TokenBucket(rate=2.0, capacity=5)
        # Public Yahoo endpoints intermittently reject individual requests under
        # broad audits. Do not let a few transient misses lock every equity and
        # chart function; per-call fallbacks and timeouts handle those cases.
        self._breaker = CircuitBreaker(threshold=50, cooldown=5)
        self._info_cache: dict[str, tuple[datetime, ReferenceData]] = {}
        self._chart_client: httpx.AsyncClient | None = None

    async def fetch(self, request: DataRequest) -> Any:
        if self._breaker.open:
            raise RateLimitError(f"{self.name} circuit open")
        await self._bucket.acquire()
        try:
            timeout = float(request.extra.get("timeout", self.config.get("timeout_seconds", 8)))
            if request.kind == DataKind.QUOTE:
                return await asyncio.wait_for(self._fetch_quote(request), timeout=timeout)
            if request.kind == DataKind.OHLCV:
                return await asyncio.wait_for(self._fetch_ohlcv(request), timeout=timeout)
            if request.kind == DataKind.REFDATA:
                return await asyncio.wait_for(self._fetch_refdata(request), timeout=timeout)
            if request.kind == DataKind.FUNDAMENTALS:
                return await asyncio.wait_for(self._fetch_fundamentals(request), timeout=timeout)
            if request.kind == DataKind.EVENTS:
                return await asyncio.wait_for(self._fetch_events(request), timeout=timeout)
            if request.kind == DataKind.HOLDINGS:
                return await asyncio.wait_for(self._fetch_holdings(request), timeout=timeout)
            if request.kind == DataKind.OPTIONS_CHAIN:
                return await asyncio.wait_for(self._fetch_options(request), timeout=timeout)
            if request.kind == DataKind.NEWS:
                return await asyncio.wait_for(self._fetch_news(request), timeout=timeout)
            raise DataSourceError(f"unsupported kind {request.kind}")
        except Exception:
            self._breaker.record_failure()
            raise
        else:
            self._breaker.record_success()

    # ── Internals ──
    @staticmethod
    def _yf_symbol(instrument: Instrument | None, fallback: str | None = None) -> str:
        if instrument is None:
            return fallback or ""
        sym = instrument.symbol
        # FX → "EURUSD=X"
        if instrument.asset_class.value == "FX" and "=" not in sym:
            return f"{sym}=X"
        # Yahoo uses dash-separated spot pairs for common crypto quotes.
        if instrument.asset_class.value == "CRYPTO":
            clean = sym.upper().replace("/", "").replace("-", "")
            for quote in ("USDT", "USDC", "USD"):
                if clean.endswith(quote) and len(clean) > len(quote):
                    base = clean[: -len(quote)]
                    yf_quote = "USD" if quote in {"USDT", "USDC"} else quote
                    return f"{base}-{yf_quote}"
        return sym

    def _ticker(self, symbol: str) -> Any:
        import yfinance as yf
        return yf.Ticker(symbol)

    async def _chart_client_(self) -> httpx.AsyncClient:
        if self._chart_client is None:
            self._chart_client = httpx.AsyncClient(
                base_url=str(self.config.get("base_url", "https://query1.finance.yahoo.com")),
                timeout=float(self.config.get("timeout_seconds", 6)),
                headers={"User-Agent": "showMe-yahoo-chart/1.0"},
            )
        return self._chart_client

    async def _fetch_news(self, req: DataRequest) -> list[dict[str, Any]]:
        sym = self._yf_symbol(req.instrument, req.symbols[0] if req.symbols else None)
        if not sym:
            raise DataSourceError("no symbol")
        ticker = await asyncio.to_thread(self._ticker, sym)
        raw_items = await asyncio.to_thread(lambda: getattr(ticker, "news", []) or [])
        out: list[dict[str, Any]] = []
        for item in raw_items[: req.limit or 25]:
            content = item.get("content") if isinstance(item, dict) else None
            if not isinstance(content, dict):
                content = item if isinstance(item, dict) else {}
            provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
            canonical = content.get("canonicalUrl") if isinstance(content.get("canonicalUrl"), dict) else {}
            click = content.get("clickThroughUrl") if isinstance(content.get("clickThroughUrl"), dict) else {}
            out.append({
                "title": content.get("title") or "",
                "summary": content.get("summary") or content.get("description") or "",
                "published_at": content.get("pubDate") or content.get("displayTime"),
                "url": canonical.get("url") or click.get("url"),
                "source": provider.get("displayName") or "Yahoo Finance",
                "provider": "yfinance",
            })
        return out

    async def _fetch_quote(self, req: DataRequest) -> Quote:
        sym = self._yf_symbol(req.instrument, req.symbols[0] if req.symbols else None)
        if not sym:
            raise DataSourceError("no symbol in request")
        if req.instrument and req.instrument.asset_class.value in {"EQUITY", "ETF", "REIT"}:
            raced_quote = await self._race_equity_quotes(sym, req.instrument.symbol)
            if raced_quote is not None:
                return raced_quote
        try:
            return await self._fetch_chart_quote(sym)
        except Exception:
            pass
        ticker = await asyncio.to_thread(self._ticker, sym)
        info = await asyncio.to_thread(getattr, ticker, "fast_info", {}) or {}
        return Quote(
            symbol=sym,
            timestamp=utcnow(),
            bid=info.get("bid") if hasattr(info, "get") else None,
            ask=info.get("ask") if hasattr(info, "get") else None,
            last=info.get("last_price") if hasattr(info, "get") else None,
            volume_24h=info.get("last_volume") if hasattr(info, "get") else None,
            open_24h=info.get("open") if hasattr(info, "get") else None,
            high_24h=info.get("day_high") if hasattr(info, "get") else None,
            low_24h=info.get("day_low") if hasattr(info, "get") else None,
            close_prev=info.get("previous_close") if hasattr(info, "get") else None,
            source=self.name,
        )

    async def _fetch_chart_quote(self, sym: str) -> Quote:
        try:
            client = await self._chart_client_()
            response = await client.get(f"/v8/finance/chart/{sym}", params={"range": "1d", "interval": "1m"})
            response.raise_for_status()
            result = (((response.json() or {}).get("chart") or {}).get("result") or [None])[0] or {}
            meta = result.get("meta") or {}
            last = meta.get("regularMarketPrice") or meta.get("previousClose")
            return Quote(
                symbol=sym,
                timestamp=utcnow(),
                last=last,
                volume_24h=meta.get("regularMarketVolume"),
                open_24h=meta.get("regularMarketOpen"),
                high_24h=meta.get("regularMarketDayHigh"),
                low_24h=meta.get("regularMarketDayLow"),
                close_prev=meta.get("previousClose"),
                source=self.name,
            )
        except Exception:
            raise

    async def _race_equity_quotes(self, yahoo_symbol: str, raw_symbol: str) -> Quote | None:
        tasks = {
            asyncio.create_task(self._fetch_chart_quote(yahoo_symbol)),
            asyncio.create_task(self._fetch_stooq_quote(raw_symbol)),
        }
        pending = set(tasks)
        deadline = asyncio.get_running_loop().time() + 3.0
        try:
            while pending:
                timeout = max(0.0, deadline - asyncio.get_running_loop().time())
                if timeout <= 0:
                    break
                done, pending = await asyncio.wait(
                    pending,
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    break
                for task in done:
                    try:
                        quote = task.result()
                    except Exception:
                        continue
                    if quote is not None:
                        return quote
            return None
        finally:
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def _fetch_stooq_quote(self, symbol: str) -> Quote | None:
        stooq_symbol = self._stooq_symbol(symbol)
        if not stooq_symbol:
            return None
        try:
            async with httpx.AsyncClient(
                base_url="https://stooq.com",
                timeout=min(float(self.config.get("timeout_seconds", 6)), 3.0),
                follow_redirects=True,
                headers={"User-Agent": "showMe-stooq-quote/1.0"},
            ) as client:
                response = await client.get(
                    "/q/l/",
                    params={"s": stooq_symbol, "f": "sd2t2ohlcv", "h": "", "e": "csv"},
                )
                response.raise_for_status()
            rows = list(csv.DictReader(io.StringIO(response.text)))
            if not rows:
                return None
            row = rows[0]
            close = _to_float(row.get("Close"))
            if close is None:
                return None
            return Quote(
                symbol=symbol.upper(),
                timestamp=utcnow(),
                last=close,
                open_24h=_to_float(row.get("Open")),
                high_24h=_to_float(row.get("High")),
                low_24h=_to_float(row.get("Low")),
                volume_24h=_to_float(row.get("Volume")),
                source="stooq_quote",
            )
        except Exception:
            return None

    @staticmethod
    def _stooq_symbol(symbol: str) -> str:
        clean = symbol.strip().lower().replace("-", ".")
        if not clean:
            return ""
        if "." not in clean:
            return f"{clean}.us"
        return clean

    async def _fetch_ohlcv(self, req: DataRequest) -> pd.DataFrame:
        sym = self._yf_symbol(req.instrument, req.symbols[0] if req.symbols else None)
        if not sym:
            raise DataSourceError("no symbol")
        interval = _INTERVAL_MAP.get(req.interval or "1d", "1d")
        period = req.extra.get("period")
        start = req.start
        end = req.end or datetime.now(tz=timezone.utc)
        if start is None and not period:
            # default last 6 months
            period = "6mo"
        try:
            df = await self._fetch_chart_ohlcv(sym, interval, start, end, period)
            if not df.empty:
                if (req.interval or "").lower() == "4h":
                    df = df.resample("4H").agg({
                        "open": "first", "high": "max", "low": "min",
                        "close": "last", "volume": "sum",
                    }).dropna()
                if req.limit:
                    df = df.tail(req.limit)
                return df
        except Exception:
            pass
        ticker = await asyncio.to_thread(self._ticker, sym)
        if period:
            df = await asyncio.to_thread(
                ticker.history, period=period, interval=interval,
                auto_adjust=False, actions=True,
            )
        else:
            df = await asyncio.to_thread(
                ticker.history, start=start, end=end, interval=interval,
                auto_adjust=False, actions=True,
            )
        df = df.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
            "Dividends": "dividends", "Stock Splits": "splits",
        })
        # 4h resample if requested
        if (req.interval or "").lower() == "4h":
            df = df.resample("4H").agg({
                "open": "first", "high": "max", "low": "min",
                "close": "last", "volume": "sum",
            }).dropna()
        if req.limit:
            df = df.tail(req.limit)
        return df

    async def _fetch_chart_ohlcv(
        self,
        sym: str,
        interval: str,
        start: datetime | None,
        end: datetime | None,
        period: str | None,
    ) -> pd.DataFrame:
        client = await self._chart_client_()
        params: dict[str, Any] = {
            "interval": interval,
            "includePrePost": "false",
            "events": "div,splits",
        }
        if period:
            params["range"] = period
        else:
            if start is None:
                start = datetime.now(tz=timezone.utc) - timedelta(days=180)
            if end is None:
                end = datetime.now(tz=timezone.utc)
            params["period1"] = int(_as_utc(start).timestamp())
            params["period2"] = int(_as_utc(end).timestamp())
        response = await client.get(f"/v8/finance/chart/{sym}", params=params)
        response.raise_for_status()
        result = (((response.json() or {}).get("chart") or {}).get("result") or [None])[0]
        if not isinstance(result, dict):
            return pd.DataFrame()
        timestamps = result.get("timestamp") or []
        quote = (((result.get("indicators") or {}).get("quote") or [None])[0]) or {}
        if not timestamps or not isinstance(quote, dict):
            return pd.DataFrame()
        idx = pd.to_datetime(timestamps, unit="s", utc=True)
        frame = pd.DataFrame(
            {
                "open": quote.get("open") or [],
                "high": quote.get("high") or [],
                "low": quote.get("low") or [],
                "close": quote.get("close") or [],
                "volume": quote.get("volume") or [],
            },
            index=idx,
        )
        frame = frame.dropna(subset=["close"])
        return frame

    async def _fetch_refdata(self, req: DataRequest) -> ReferenceData:
        sym = self._yf_symbol(req.instrument, req.symbols[0] if req.symbols else None)
        cached = self._info_cache.get(sym)
        include_recommendations = bool(req.extra.get("include_recommendations"))
        if cached and not include_recommendations and (utcnow() - cached[0]) < timedelta(hours=12):
            return cached[1]
        ticker = await asyncio.to_thread(self._ticker, sym)
        try:
            info = await asyncio.wait_for(
                asyncio.to_thread(lambda: getattr(ticker, "info", {}) or {}),
                timeout=float(req.extra.get("info_timeout", 8)),
            )
        except Exception as exc:
            info = {}
            info_error = str(exc)
        else:
            info_error = ""
        raw = {k: v for k, v in info.items() if k not in {"longBusinessSummary"}}
        if info_error:
            raw["info_error"] = info_error
        if include_recommendations:
            try:
                recs = await asyncio.wait_for(
                    asyncio.to_thread(lambda: getattr(ticker, "recommendations_summary", pd.DataFrame())),
                    timeout=float(req.extra.get("recommendations_timeout", 8)),
                )
                if not isinstance(recs, pd.DataFrame) or recs.empty:
                    recs = await asyncio.wait_for(
                        asyncio.to_thread(lambda: getattr(ticker, "recommendations", pd.DataFrame())),
                        timeout=float(req.extra.get("recommendations_timeout", 8)),
                    )
                raw["recommendations_summary"] = _frame_records(recs)
            except Exception as exc:
                raw["recommendations_error"] = str(exc)
            try:
                actions = await asyncio.wait_for(
                    asyncio.to_thread(lambda: getattr(ticker, "upgrades_downgrades", pd.DataFrame())),
                    timeout=float(req.extra.get("actions_timeout", 8)),
                )
                if isinstance(actions, pd.DataFrame) and not actions.empty:
                    actions = actions.sort_index(ascending=False)
                raw["upgrades_downgrades"] = _frame_records(actions, limit=80)
            except Exception as exc:
                raw["upgrades_downgrades_error"] = str(exc)
        rd = ReferenceData(
            symbol=sym,
            name=info.get("shortName") or info.get("longName"),
            asset_class=req.instrument.asset_class.value if req.instrument else None,
            exchange=info.get("exchange"),
            currency=info.get("currency"),
            country=info.get("country"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            market_cap=info.get("marketCap"),
            shares_outstanding=info.get("sharesOutstanding"),
            shares_float=info.get("floatShares"),
            employees=info.get("fullTimeEmployees"),
            website=info.get("website"),
            description=info.get("longBusinessSummary"),
            ceo=info.get("companyOfficers", [{}])[0].get("name") if info.get("companyOfficers") else None,
            headquarters=", ".join(filter(None, [info.get("city"), info.get("state"), info.get("country")])),
            isin=info.get("isin"),
            source=self.name,
            fetched_at=utcnow(),
            extras={"raw": raw},
        )
        if not include_recommendations:
            self._info_cache[sym] = (utcnow(), rd)
        return rd

    async def _fetch_fundamentals(self, req: DataRequest) -> dict[str, pd.DataFrame]:
        sym = self._yf_symbol(req.instrument, req.symbols[0] if req.symbols else None)
        ticker = await asyncio.to_thread(self._ticker, sym)
        period = req.extra.get("period", "annual")
        if period == "quarterly":
            inc = await asyncio.to_thread(getattr, ticker, "quarterly_income_stmt", pd.DataFrame())
            bs  = await asyncio.to_thread(getattr, ticker, "quarterly_balance_sheet", pd.DataFrame())
            cf  = await asyncio.to_thread(getattr, ticker, "quarterly_cashflow", pd.DataFrame())
        else:
            inc = await asyncio.to_thread(getattr, ticker, "income_stmt", pd.DataFrame())
            bs  = await asyncio.to_thread(getattr, ticker, "balance_sheet", pd.DataFrame())
            cf  = await asyncio.to_thread(getattr, ticker, "cashflow", pd.DataFrame())
        return {"income": inc, "balance": bs, "cashflow": cf}

    async def _fetch_events(self, req: DataRequest) -> dict[str, Any]:
        sym = self._yf_symbol(req.instrument, req.symbols[0] if req.symbols else None)
        ticker = await asyncio.to_thread(self._ticker, sym)
        return {
            "calendar": await asyncio.to_thread(getattr, ticker, "calendar", None),
            "earnings_dates": await asyncio.to_thread(getattr, ticker, "earnings_dates", pd.DataFrame()),
            "actions": await asyncio.to_thread(getattr, ticker, "actions", pd.DataFrame()),
            "dividends": await asyncio.to_thread(getattr, ticker, "dividends", pd.Series(dtype=float)),
            "splits": await asyncio.to_thread(getattr, ticker, "splits", pd.Series(dtype=float)),
        }

    async def _fetch_holdings(self, req: DataRequest) -> dict[str, Any]:
        sym = self._yf_symbol(req.instrument, req.symbols[0] if req.symbols else None)
        ticker = await asyncio.to_thread(self._ticker, sym)
        return {
            "major": await asyncio.to_thread(getattr, ticker, "major_holders", pd.DataFrame()),
            "institutional": await asyncio.to_thread(getattr, ticker, "institutional_holders", pd.DataFrame()),
            "mutualfund": await asyncio.to_thread(getattr, ticker, "mutualfund_holders", pd.DataFrame()),
            "insider_transactions": await asyncio.to_thread(getattr, ticker, "insider_transactions", pd.DataFrame()),
        }

    async def _fetch_options(self, req: DataRequest) -> dict[str, Any]:
        sym = self._yf_symbol(req.instrument, req.symbols[0] if req.symbols else None)
        ticker = await asyncio.to_thread(self._ticker, sym)
        expiries = await asyncio.to_thread(getattr, ticker, "options", ()) or ()
        target_expiry = req.extra.get("expiry")
        if target_expiry and target_expiry in expiries:
            chain = await asyncio.to_thread(ticker.option_chain, target_expiry)
            return {
                "expiry": target_expiry,
                "calls": chain.calls,
                "puts": chain.puts,
                "expiries": list(expiries),
            }
        return {"expiries": list(expiries), "calls": pd.DataFrame(), "puts": pd.DataFrame()}
