"""BQL — Bloomberg Query Language (basit DSL).

Format:
    get(price, volume) for(['AAPL','MSFT']) with(start='2024-01-01', end='2024-12-31') by(date)

Bu sürüm parser'ı oldukça basit (regex tabanlı). Phase 7'de pyparsing/lark.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


_BLOCK = re.compile(r"(\w+)\s*\(([^)]*)\)")


@dataclass
class BQLQuery:
    fields: list[str]
    universe: list[str]
    params: dict[str, Any]
    by: str | None = None


def parse_bql(text: str) -> BQLQuery:
    blocks = {m.group(1): m.group(2) for m in _BLOCK.finditer(text)}
    fields = [s.strip() for s in (blocks.get("get") or "").split(",") if s.strip()]
    raw_universe = (blocks.get("for") or "").strip()
    universe = []
    if raw_universe.startswith("["):
        raw_universe = raw_universe.strip("[]")
        universe = [s.strip().strip("'\"") for s in raw_universe.split(",") if s.strip()]
    params: dict[str, Any] = {}
    for kv in (blocks.get("with") or "").split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            params[k.strip()] = v.strip().strip("'\"")
    by = (blocks.get("by") or None)
    if by is not None:
        by = by.strip()
    return BQLQuery(fields=fields, universe=universe, params=params, by=by)


def _infer_asset_class(symbol: str) -> AssetClass:
    upper = symbol.upper()
    if upper.startswith("^"):
        return AssetClass.INDEX
    if upper.endswith("=F") or upper in {"XAUUSD", "XAGUSD", "WTI", "BRENT"}:
        return AssetClass.COMMODITY
    if upper.endswith("=X") or re.fullmatch(r"[A-Z]{6}", upper):
        return AssetClass.FX
    if any(upper.endswith(q) for q in ("USDT", "USDC", "USD", "-USD", "/USD")) and len(upper) > 6:
        return AssetClass.CRYPTO
    return AssetClass.EQUITY


def _default_universe(instrument: Instrument | None, params: dict[str, Any]) -> list[str]:
    raw = params.get("symbols") or params.get("universe")
    if isinstance(raw, str):
        values = [s.strip() for s in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        values = [str(s).strip() for s in raw]
    else:
        values = []
    values = [s for s in values if s]
    if values:
        return values
    if instrument and instrument.symbol:
        return [instrument.symbol]
    symbol = str(params.get("symbol") or "").strip()
    return [symbol] if symbol else ["BTCUSDT"]


def _template_rows(query: BQLQuery, instrument: Instrument | None, params: dict[str, Any]) -> list[dict[str, Any]]:
    fields = query.fields or ["close", "volume"]
    universe = query.universe or _default_universe(instrument, params)
    today = datetime.now(timezone.utc).date()
    rows: list[dict[str, Any]] = []
    for offset in range(21, -1, -1):
        day = today - timedelta(days=offset)
        for idx, sym in enumerate(universe):
            seed = sum(ord(ch) for ch in sym.upper()) % 1000
            close = round(50 + seed / 13 + (21 - offset) * (0.15 + idx * 0.03), 4)
            row: dict[str, Any] = {"symbol": sym, "date": day.isoformat()}
            for field in fields:
                key = field.lower()
                if key in {"px_last", "last", "price", "close"}:
                    row[field] = close
                elif key in {"open"}:
                    row[field] = round(close * 0.997, 4)
                elif key in {"high"}:
                    row[field] = round(close * 1.012, 4)
                elif key in {"low"}:
                    row[field] = round(close * 0.988, 4)
                elif key in {"volume", "turnover"}:
                    row[field] = int(100_000 + seed * 173 + (21 - offset) * 900)
                elif key in {"return", "chg_pct", "change_pct"}:
                    row[field] = round((idx + 1) * 0.0015 + (21 - offset) * 0.0002, 6)
                else:
                    row[field] = close
            rows.append(row)
    return rows


@FunctionRegistry.register
class BQLFunction(BaseFunction):
    code = "BQL"
    name = "ShowMe Query Language"
    category = "api"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        text = params.get("query") or ""
        q = parse_bql(text)
        if not q.universe:
            q.universe = _default_universe(instrument, params)
        if not q.fields:
            q.fields = ["close", "volume"]
        rows: list[dict[str, Any]] = []
        if not (params.get("live_query") or params.get("live")):
            rows = _template_rows(q, instrument, params)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=rows,
                sources=["showme_query_model"],
                metadata={"parsed": q.__dict__, "rows": len(rows), "mode": "computed_model"},
            )
        if not self.deps.yfinance:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "BQL live mode requires the yfinance provider.",
                    "rows": [],
                },
                sources=["yfinance"],
                warnings=["no yfinance"],
                metadata={"parsed": q.__dict__, "rows": 0, "mode": "unavailable"},
            )
        from src.core.instrument import Instrument as I
        import asyncio
        tasks = [self.deps.yfinance.fetch(DataRequest(
            kind=DataKind.OHLCV,
            instrument=I(symbol=s, asset_class=_infer_asset_class(s)),
            start=pd.to_datetime(q.params.get("start")) if q.params.get("start") else None,
            end=pd.to_datetime(q.params.get("end")) if q.params.get("end") else None,
            interval=q.params.get("interval", "1d"),
            extra={"period": q.params.get("period", "1mo"), "timeout": float(params.get("yfinance_timeout", 6))},
        )) for s in q.universe]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        provider_errors: list[str] = []
        for sym, df in zip(q.universe, results):
            if isinstance(df, Exception) or df is None or df.empty:
                if isinstance(df, Exception):
                    provider_errors.append(f"{sym}: {df}")
                else:
                    provider_errors.append(f"{sym}: no rows")
                continue
            for ts, row in df.iterrows():
                d = {"symbol": sym, "date": ts.isoformat()}
                for f in q.fields:
                    if f.lower() in row.index.str.lower():
                        col = row.index[row.index.str.lower() == f.lower()][0]
                        d[f] = float(row[col])
                rows.append(d)
        if not rows:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "No live rows returned for the requested BQL universe.",
                    "rows": [],
                    "next_actions": [
                        "Use query like get(close, volume) for(['AAPL']) with(period='1mo') by(date).",
                        "For crypto, use Binance-style symbols such as BTCUSDT or Yahoo-style BTC-USD.",
                        "Increase timeout with params {\"live\":true,\"yfinance_timeout\":12}.",
                    ],
                },
                sources=["yfinance"],
                warnings=provider_errors,
                metadata={
                    "parsed": q.__dict__,
                    "rows": 0,
                    "mode": "unavailable",
                    "provider_errors": provider_errors,
                },
            )
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=rows,
            sources=["yfinance"],
            warnings=provider_errors,
            metadata={"parsed": q.__dict__, "rows": len(rows), "mode": "live"},
        )
