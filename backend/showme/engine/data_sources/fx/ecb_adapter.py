"""ECB Statistical Data Warehouse (SDW) adapter — ücretsiz, anahtarsız.

DATA PIPELINE:
    Source: https://data-api.ecb.europa.eu/service/data
    Coverage: euro reference rates (EUR/USD, EUR/GBP, EUR/JPY, ...) günlük.
    Latency: <500ms.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pandas as pd

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)
from showme.engine.core.quote import Quote, utcnow


def _fixing_timestamp(index_value: Any) -> datetime | None:
    """UTC timestamp of one ECB fixing from its date index (day precision).

    Returns None when the index does not carry a date, so the caller can
    refuse to stamp a value of unknown age (ASOF-5).
    """
    if not isinstance(index_value, (datetime, pd.Timestamp)):
        return None
    ts = pd.Timestamp(index_value)
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.to_pydatetime()


def _fixing_quote(symbol: str, df: pd.DataFrame, source: str) -> Quote:
    """Last ECB fixing as a Quote dated by the fixing's own date.

    The ECB daily reference rate is dated by the CSV TIME_PERIOD, which is
    the DataFrame index. A Saturday/Sunday call therefore still reports the
    Friday fixing as Friday, not as the wall-clock time of the request.
    """
    if df is None or df.empty:
        return Quote(symbol=symbol, timestamp=utcnow(), last=None, source=source)
    stamp = _fixing_timestamp(df.index[-1])
    last = float(df["value"].iloc[-1])
    if stamp is None:
        # Value without a date: keep it out of the quote rather than age it.
        return Quote(symbol=symbol, timestamp=utcnow(), last=None, source=source)
    return Quote(symbol=symbol, timestamp=stamp, last=last, source=source)


class ECBAdapter(BaseDataSource):
    name = "ecb"
    supported_kinds = (DataKind.ECON_SERIES, DataKind.QUOTE, DataKind.OHLCV)
    rate_limit_rps = 5.0
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get(
            "base_url", "https://data-api.ecb.europa.eu/service/data"
        )
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Accept": "text/csv"}
            self._client = httpx.AsyncClient(
                base_url=self.base_url, headers=headers,
                timeout=self.timeout_seconds,
            )
        return self._client

    async def euro_rate(self, currency: str, start: str | None = None) -> pd.DataFrame:
        """ECB euro reference rate against ``currency`` (e.g. USD)."""
        flow = "EXR"
        key = f"D.{currency}.EUR.SP00.A"  # daily, foreign-vs-EUR, spot, average
        client = await self._client_()
        url = f"/{flow}/{key}"
        params = {"format": "csvdata"}
        if start:
            params["startPeriod"] = start
        r = await client.get(url, params=params)
        r.raise_for_status()
        try:
            from io import StringIO
            df = pd.read_csv(StringIO(r.text))
        except Exception as e:
            raise DataSourceError(f"ECB CSV parse failed: {e}")
        if "TIME_PERIOD" in df.columns and "OBS_VALUE" in df.columns:
            df = df.rename(columns={"TIME_PERIOD": "date", "OBS_VALUE": "value"})
            df["date"] = pd.to_datetime(df["date"])
            return df.set_index("date")[["value"]]
        return df

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if sym and len(sym) >= 6 and request.kind in (DataKind.QUOTE, DataKind.OHLCV):
            start = request.start
            if request.kind == DataKind.QUOTE and start is None:
                start = datetime.now(timezone.utc) - timedelta(days=14)
            df = await self.fx_pair(
                sym[:3].upper(),
                sym[3:6].upper(),
                start=start.strftime("%Y-%m-%d") if start else None,
            )
            if request.kind == DataKind.OHLCV:
                out = df.rename(columns={"value": "close"})
                out["open"] = out["close"]
                out["high"] = out["close"]
                out["low"] = out["close"]
                out["volume"] = 0
                candles = out[["open", "high", "low", "close", "volume"]]
                # ECB publishes a single daily reference rate; the OHLCV
                # shape above is synthetic (open=high=low=close, no volume).
                # Tag it so consumers never read these as real candles.
                candles.attrs["data_mode"] = "modeled"
                return candles
            return _fixing_quote(sym, df, self.name)
        if request.kind in (DataKind.ECON_SERIES, DataKind.OHLCV):
            if not sym:
                raise DataSourceError("ECB needs a currency symbol")
            currency = sym[:3] if len(sym) >= 3 else sym
            df = await self.euro_rate(
                currency,
                start=request.start.strftime("%Y-%m-%d") if request.start else None,
            )
            return df
        if request.kind == DataKind.QUOTE:
            df = await self.fetch(DataRequest(
                kind=DataKind.ECON_SERIES,
                instrument=request.instrument, symbols=request.symbols,
            ))
            return _fixing_quote(
                request.symbols[0] if request.symbols else (request.instrument.symbol if request.instrument else ""),
                df,
                self.name,
            )
        raise DataSourceError(f"unsupported kind {request.kind}")

    async def fx_pair(self, base: str, quote: str, start: str | None = None) -> pd.DataFrame:
        """Return quote currency units per one base currency."""
        if base == quote:
            return pd.DataFrame({"value": [1.0]}, index=[pd.Timestamp.utcnow()])
        if base == "EUR":
            return await self.euro_rate(quote, start=start)
        if quote == "EUR":
            df = await self.euro_rate(base, start=start)
            df["value"] = 1.0 / df["value"]
            return df
        base_df = (await self.euro_rate(base, start=start)).rename(columns={"value": "base_per_eur"})
        quote_df = (await self.euro_rate(quote, start=start)).rename(columns={"value": "quote_per_eur"})
        joined = base_df.join(quote_df, how="inner")
        if joined.empty:
            return pd.DataFrame(columns=["value"])
        joined["value"] = joined["quote_per_eur"] / joined["base_per_eur"]
        return joined[["value"]]
