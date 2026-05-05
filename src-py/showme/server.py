"""showMe sidecar entrypoint.

Boot strategy:
1. Extend ``sys.path`` with ShowMe's bundled function engine so we can
   ``import src`` modules directly from this repository.
2. Bind uvicorn to 127.0.0.1 on the requested port (default ``0`` → OS picks a
   free port). After ``Server.startup`` we print exactly one line
   ``SIDECAR_PORT=<u16>`` for the Tauri shell.
3. Mount /api/health, /api/sidecar/info, /api/function-index, and first-class
   function execution routes for the native shell.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import shutil
import importlib
import logging
import math
import os
import resource
import socket
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from showme.function_contracts import normalize_function_contract

LOG = logging.getLogger("showme.server")
DEFAULT_ENGINE = (Path(__file__).resolve().parents[2] / "engine").resolve()
FUNCTION_TIMEOUT_SECONDS = float(os.environ.get("SHOWME_FUNCTION_TIMEOUT_SECONDS", "45"))
CRYPTO_QUOTE_SUFFIXES = ("USDT", "USDC", "USD", "BTC", "ETH", "EUR")
CRYPTO_SYMBOLS = {
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "XRP",
    "ADA",
    "DOGE",
    "AVAX",
    "DOT",
    "LINK",
    "MATIC",
    "TRX",
}
FX_CURRENCIES = {
    "USD",
    "EUR",
    "JPY",
    "GBP",
    "CHF",
    "AUD",
    "CAD",
    "NZD",
    "SEK",
    "NOK",
    "MXN",
    "TRY",
}
COMMODITY_FUTURES = {"GC", "SI", "CL", "BZ", "NG", "HG", "PL", "ZC", "ZW", "ZS"}
INDEX_SYMBOLS = {"SPX", "NDX", "DJI", "RUT", "VIX", "GSPC", "IXIC", "DJIA"}
RUNTIME_MIRROR_SUFFIXES = {".json", ".sqlite", ".db", ".duckdb"}
RUNTIME_MIRROR_SKIP_PREFIXES = (
    "bot.log",
    "bot_stdout",
    "bot_stderr",
    "dashboard",
)
SYNTHETIC_SOURCE_MARKERS = (
    "template",
    "sample",
    "placeholder",
    "synthetic",
    "continuity",
)


def raise_open_file_limit() -> None:
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = min(max(soft, 8192), hard)
        if target > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
    except Exception:
        LOG.debug("could not raise RLIMIT_NOFILE", exc_info=True)


raise_open_file_limit()


def _default_app_home() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "showMe"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "showMe"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "showMe"


def prepare_writable_cwd() -> Path | None:
    """Move frozen app writes away from PyInstaller's read-only extraction dir."""
    if not getattr(sys, "_MEIPASS", None):
        return None
    app_home = Path(os.environ.get("SHOWME_HOME", _default_app_home())).expanduser()
    app_home.mkdir(parents=True, exist_ok=True)
    (app_home / "runtime").mkdir(parents=True, exist_ok=True)
    if _env_truthy("SHOWME_MIRROR_LEGACY_RUNTIME"):
        mirror_legacy_runtime(app_home)
    os.environ.setdefault("SHOWME_HOME", str(app_home))
    os.chdir(app_home)
    return app_home


def _env_truthy(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def mirror_legacy_runtime(app_home: Path) -> int:
    """Copy external runtime state into showMe's writable runtime mirror.

    Some portfolio/account functions read relative ``runtime/*`` files. The
    native sidecar cannot run from the bundled read-only extraction directory,
    so it mirrors small state files into Application Support before executing
    those functions.
    """
    source = discover_legacy_runtime()
    if not source:
        return 0
    target = app_home / "runtime"
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in source.iterdir():
        if not src.is_file():
            continue
        if src.suffix not in RUNTIME_MIRROR_SUFFIXES:
            continue
        if src.name.startswith(RUNTIME_MIRROR_SKIP_PREFIXES):
            continue
        dst = target / src.name
        try:
            if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
                continue
            shutil.copy2(src, dst)
            copied += 1
        except OSError as exc:
            LOG.warning("runtime mirror skipped %s: %s", src, exc)
    if copied:
        LOG.info("Mirrored %s runtime files from %s", copied, source)
    return copied


def discover_legacy_runtime() -> Path | None:
    override = os.environ.get("SHOWME_ENGINE_RUNTIME_PATH")
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).expanduser())
    engine_override = os.environ.get("SHOWME_ENGINE_PATH")
    if engine_override:
        candidates.append(Path(engine_override).expanduser() / "runtime")
    for raw in candidates:
        path = raw.resolve()
        if (path / "state.json").is_file():
            return path
    return None


def attach_engine(engine_path: str | Path | None) -> Path | None:
    """Insert the bundled engine root into sys.path so we can import functions."""
    candidates: list[Path] = []
    if engine_path:
        candidates.append(Path(engine_path).expanduser())
    else:
        # PyInstaller extracts bundled --add-data entries under _MEIPASS.
        # In release builds the engine src/config directories live there.
        frozen_root = getattr(sys, "_MEIPASS", None)
        if frozen_root:
            candidates.append(Path(frozen_root))
        candidates.append(DEFAULT_ENGINE)
    for raw in candidates:
        candidate = raw.resolve()
        if (candidate / "src").is_dir():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            os.environ.setdefault("SHOWME_ENGINE_ROOT", str(candidate))
            return candidate
    return None


def _safe_import(name: str) -> Any | None:
    try:
        return importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 — graceful fallback by design
        LOG.warning("optional import %s failed: %s", name, exc)
        return None


class _ShowMeFunctionWorker:
    """Run all ShowMe function calls on one persistent asyncio loop.

    Function adapters cache async clients, locks, and some SQLite-backed stores.
    Creating a fresh event loop/thread per request makes those cached objects
    unusable on the next request. A single worker loop keeps the FastAPI loop
    responsive while preserving adapter loop/thread affinity.
    """

    def __init__(self) -> None:
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(
            target=self._run_loop,
            name="showme-functions",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=5)
        if self._loop is None:
            raise RuntimeError("ShowMe function worker failed to start")

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()

    async def execute(self, code: str, params: dict[str, Any]) -> Any:
        if self._loop is None:
            raise HTTPException(status_code=503, detail="ShowMe worker unavailable")
        future = asyncio.run_coroutine_threadsafe(
            _execute_showme_function_on_worker(code, params),
            self._loop,
        )
        try:
            return await asyncio.wait_for(
                asyncio.wrap_future(future),
                timeout=FUNCTION_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            future.cancel()
            raise


_FUNCTION_WORKER: _ShowMeFunctionWorker | None = None
_FUNCTION_INDEX_CACHE: list[FunctionIndexEntry] | None = None
_FUNCTION_INDEX_LOCK = threading.Lock()


def _function_worker() -> _ShowMeFunctionWorker:
    global _FUNCTION_WORKER
    if _FUNCTION_WORKER is None:
        _FUNCTION_WORKER = _ShowMeFunctionWorker()
    return _FUNCTION_WORKER


async def _execute_showme_function(code: str, params: dict[str, Any]) -> Any:
    return await _function_worker().execute(code, params)


async def _warm_showme_function_factory_on_worker() -> None:
    factory_mod = _safe_import("src.services.function_factory")
    if factory_mod is None:
        return
    current_factory = getattr(factory_mod, "_factory", None)
    owner = getattr(current_factory, "_showme_worker_thread", None)
    if current_factory is not None and owner != threading.get_ident():
        factory_mod._factory = None
    factory = factory_mod.get_factory()
    setattr(factory, "_showme_worker_thread", threading.get_ident())


async def _warm_showme_function_factory() -> None:
    worker = _function_worker()
    if worker._loop is None:
        return
    future = asyncio.run_coroutine_threadsafe(
        _warm_showme_function_factory_on_worker(),
        worker._loop,
    )
    await asyncio.wrap_future(future)


async def _execute_showme_function_on_worker(code: str, params: dict[str, Any]) -> Any:
    registry_mod = _safe_import("src.core.base_function")
    instrument_mod = _safe_import("src.core.instrument")
    data_source_mod = _safe_import("src.core.base_data_source")
    factory_mod = _safe_import("src.services.function_factory")
    if not (registry_mod and instrument_mod and factory_mod):
        raise HTTPException(status_code=503, detail="ShowMe modules unavailable")
    try:
        current_factory = getattr(factory_mod, "_factory", None)
        owner = getattr(current_factory, "_showme_worker_thread", None)
        if current_factory is not None and owner != threading.get_ident():
            factory_mod._factory = None
        factory = factory_mod.get_factory()
        setattr(factory, "_showme_worker_thread", threading.get_ident())
    except Exception as exc:  # noqa: BLE001
        LOG.exception("get_factory failed")
        raise HTTPException(status_code=500, detail=f"factory: {exc}")
    upper_code = code.upper()
    local_params = dict(params)
    symbol = local_params.pop("symbol", None)
    instrument = None
    if symbol:
        try:
            AssetClass = instrument_mod.AssetClass
            Instrument = instrument_mod.Instrument
            ac_name = default_asset_class_name(str(symbol), local_params.pop("asset_class", None))
            ac = getattr(AssetClass, ac_name, AssetClass.EQUITY)
            instrument = Instrument(symbol=str(symbol).upper(), asset_class=ac)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("instrument resolve failed: %s", exc)
    if upper_code in {"GP", "HP"}:
        return await _execute_price_history_alias(
            upper_code,
            local_params,
            instrument,
            factory,
            registry_mod,
            data_source_mod,
        )
    cls = registry_mod.FunctionRegistry.get(upper_code)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"unknown function {code}")
    if instrument is not None and not _function_supports_instrument(cls, instrument):
        return _compatibility_function_result(registry_mod, cls, instrument, upper_code, local_params)
    fn = cls(deps=getattr(factory, "deps", None))
    return await fn.execute_timed(instrument=instrument, **local_params)


def _function_supports_instrument(cls: Any, instrument: Any) -> bool:
    supported = tuple(getattr(cls, "asset_classes", ()) or ())
    if not supported:
        return True
    actual = getattr(instrument, "asset_class", None)
    actual_value = str(getattr(actual, "value", actual)).upper()
    return any(str(getattr(item, "value", item)).upper() == actual_value for item in supported)


def _compatibility_function_result(
    registry_mod: Any,
    cls: Any,
    instrument: Any,
    code: str,
    params: dict[str, Any],
) -> Any:
    FunctionResult = registry_mod.FunctionResult
    asset_class = str(getattr(getattr(instrument, "asset_class", None), "value", "")).upper()
    request_params = {
        **params,
        "symbol": getattr(instrument, "symbol", params.get("symbol")),
        "asset_class": asset_class,
    }
    supported = [
        str(getattr(item, "value", item)).upper()
        for item in tuple(getattr(cls, "asset_classes", ()) or ())
    ]
    data = unavailable_function_data(
        code,
        request_params,
        reason=f"{code} does not support {asset_class}",
        status="unsupported_asset",
        extra={
            "compatibility": {
                "mode": "unsupported_asset",
                "requested_asset_class": asset_class,
                "native_asset_classes": supported,
            },
        },
    )
    return FunctionResult(
        code=code,
        instrument=instrument,
        data=data,
        metadata={
            "fallback": True,
            "compatibility_mode": "unsupported_asset",
            "native_asset_classes": supported,
            "requested_asset_class": asset_class,
            "provider_errors": [f"{code} does not support {asset_class}"],
        },
        sources=["showme_compatibility_guard"],
        warnings=[],
    )


async def _execute_price_history_alias(
    code: str,
    params: dict[str, Any],
    instrument: Any,
    factory: Any,
    registry_mod: Any,
    data_source_mod: Any,
) -> Any:
    if instrument is None:
        raise ValueError(f"{code} requires a symbol")
    if data_source_mod is None:
        raise HTTPException(status_code=503, detail="ShowMe data source modules unavailable")
    deps = getattr(factory, "deps", None)
    asset_class = getattr(getattr(instrument, "asset_class", None), "value", "")
    adapter_candidates: list[tuple[str, Any]] = []
    if str(asset_class).upper() == "CRYPTO":
        adapter_candidates.extend([
            ("ccxt_failover", getattr(deps, "ccxt_failover", None)),
            ("coingecko", getattr(deps, "coingecko", None)),
        ])
    adapter_candidates.append(("yfinance", getattr(deps, "yfinance", None)))
    days = int(params.get("days") or _days_from_range(params.get("range")) or 365)
    interval = str(params.get("interval") or "1d")
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    source_name = ""
    for name, adapter in adapter_candidates:
        if adapter is None:
            continue
        try:
            df = await adapter.fetch(data_source_mod.DataRequest(
                kind=data_source_mod.DataKind.OHLCV,
                instrument=instrument,
                start=datetime.utcnow() - timedelta(days=days),
                interval=interval,
            ))
            rows = _history_rows(df)
            if rows:
                source_name = name
                warnings = []
                break
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{name}: {exc}")
    if not rows:
        warnings.append("no price history")
    FunctionResult = registry_mod.FunctionResult
    return FunctionResult(
        code=code,
        instrument=instrument,
        data={"ohlcv": rows, "bars": rows, "rows": rows},
        sources=[source_name] if source_name else [],
        warnings=warnings,
        metadata={"alias": "price_history", "days": days, "interval": interval},
    )


def _days_from_range(value: Any) -> int | None:
    if not value:
        return None
    return {
        "1M": 30,
        "3M": 90,
        "6M": 180,
        "1Y": 365,
        "5Y": 365 * 5,
        "MAX": 365 * 25,
    }.get(str(value).upper())


def _history_rows(frame: Any) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", False):
        return []
    try:
        df = frame.reset_index()
        records = df.to_dict(orient="records")
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for raw in records:
        row = {str(k).lower(): _json_scalar(v) for k, v in raw.items()}
        date = (
            row.pop("date", None)
            or row.pop("datetime", None)
            or row.pop("timestamp", None)
            or row.pop("index", None)
        )
        out = {
            "date": date,
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "adj_close": row.get("adj close") or row.get("adj_close"),
            "volume": row.get("volume"),
        }
        if out["close"] is not None:
            rows.append(out)
    return rows


def _json_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and value != value:
        return None
    if hasattr(value, "isoformat"):
        with contextlib.suppress(Exception):
            return value.isoformat()
    if hasattr(value, "item"):
        with contextlib.suppress(Exception):
            item = value.item()
            if isinstance(item, float) and item != item:
                return None
            return item
    return value


def default_asset_class_name(symbol: str | None, requested: Any = None) -> str:
    if requested:
        return str(requested).upper()
    if looks_like_crypto_symbol(symbol):
        return "CRYPTO"
    if looks_like_fx_symbol(symbol):
        return "FX"
    if looks_like_commodity_symbol(symbol):
        return "COMMODITY"
    if looks_like_index_symbol(symbol):
        return "INDEX"
    return "EQUITY"


def looks_like_crypto_symbol(symbol: str | None) -> bool:
    if not symbol:
        return False
    value = symbol.upper().replace("-", "").replace("/", "")
    if value in CRYPTO_SYMBOLS:
        return True
    return any(
        value.endswith(suffix)
        and value[: -len(suffix)] in CRYPTO_SYMBOLS
        and len(value) > len(suffix)
        for suffix in CRYPTO_QUOTE_SUFFIXES
    )


def looks_like_fx_symbol(symbol: str | None) -> bool:
    if not symbol:
        return False
    value = symbol.upper().replace("/", "").replace("-", "").removesuffix("=X")
    if len(value) != 6:
        return False
    return value[:3] in FX_CURRENCIES and value[3:] in FX_CURRENCIES


def looks_like_commodity_symbol(symbol: str | None) -> bool:
    if not symbol:
        return False
    value = symbol.upper()
    if value.endswith("=F") and value[:-2] in COMMODITY_FUTURES:
        return True
    return value in {"XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD", "WTI", "BRENT"}


def looks_like_index_symbol(symbol: str | None) -> bool:
    if not symbol:
        return False
    value = symbol.upper().lstrip("^")
    return value in INDEX_SYMBOLS


class FunctionIndexEntry(BaseModel):
    code: str
    name: str
    category: str
    description: str = ""
    asset_classes: list[str] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)


AGENT_DEFAULT_CANDIDATES = (
    {"symbol": "BTCUSDT", "asset_class": "CRYPTO"},
    {"symbol": "ETHUSDT", "asset_class": "CRYPTO"},
    {"symbol": "SOLUSDT", "asset_class": "CRYPTO"},
    {"symbol": "AAPL", "asset_class": "EQUITY"},
    {"symbol": "MSFT", "asset_class": "EQUITY"},
    {"symbol": "NVDA", "asset_class": "EQUITY"},
    {"symbol": "EURUSD", "asset_class": "FX"},
    {"symbol": "GC=F", "asset_class": "COMMODITY"},
)

AGENT_POSITIVE_TERMS = (
    "score",
    "confidence",
    "accuracy",
    "sharpe",
    "return",
    "alpha",
    "upside",
    "growth",
    "momentum",
    "yield",
    "profit",
    "pnl",
    "bullish",
    "buy",
    "positive",
)
AGENT_NEGATIVE_TERMS = (
    "risk",
    "drawdown",
    "volatility",
    "var",
    "loss",
    "downside",
    "debt",
    "cost",
    "fee",
    "spread",
    "bearish",
    "sell",
    "negative",
)
AGENT_IGNORE_TERMS = (
    "date",
    "time",
    "timestamp",
    "height",
    "count",
    "samples",
    "limit",
    "volume",
    "price",
    "open",
    "high",
    "low",
    "close",
    "spot",
    "strike",
    "qty",
    "quantity",
    "shares",
    "marketcap",
    "market_cap",
    "avgcost",
    "costbasis",
    "basis",
    "fairvalue",
)


def _parse_agent_candidates(raw: Any) -> list[dict[str, str]]:
    if raw is None or raw == "":
        raw = list(AGENT_DEFAULT_CANDIDATES)
    if isinstance(raw, str):
        raw = [
            part.strip()
            for part in raw.replace(";", ",").replace("\n", ",").split(",")
            if part.strip()
        ]
    if not isinstance(raw, list):
        raw = list(AGENT_DEFAULT_CANDIDATES)
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            symbol = item.strip().upper()
            asset_class = default_asset_class_name(symbol)
        elif isinstance(item, dict):
            symbol = str(item.get("symbol") or item.get("ticker") or "").strip().upper()
            asset_class = default_asset_class_name(symbol, item.get("asset_class"))
        else:
            continue
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append({"symbol": symbol, "asset_class": asset_class})
    return out or list(AGENT_DEFAULT_CANDIDATES)


def _agent_profile(symbol: str, asset_class: str) -> dict[str, Any]:
    if asset_class == "CRYPTO":
        peers = [symbol, "ETHUSDT", "SOLUSDT"]
        universe = [symbol, "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
        return {
            "news_query": "bitcoin cryptocurrency",
            "peer_symbols": list(dict.fromkeys(peers)),
            "bql_symbol": "BTC-USD" if symbol == "BTCUSDT" else symbol,
            "isin_query": symbol,
            "exchange": "BINANCE",
            "universe": list(dict.fromkeys(universe)),
            "targets": {symbol: 0.6, "ETHUSDT": 0.4},
        }
    if asset_class == "FX":
        peers = [symbol, "GBPUSD=X", "USDJPY=X"]
        universe = [symbol, "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X"]
        return {
            "news_query": "foreign exchange rates",
            "peer_symbols": list(dict.fromkeys(peers)),
            "bql_symbol": f"{symbol}=X" if not symbol.endswith("=X") else symbol,
            "isin_query": symbol,
            "exchange": "FX",
            "universe": list(dict.fromkeys(universe)),
            "targets": {symbol: 0.5, "GBPUSD=X": 0.3, "USDJPY=X": 0.2},
        }
    if asset_class == "COMMODITY":
        peers = [symbol, "SI=F", "CL=F"]
        universe = [symbol, "SI=F", "CL=F", "BZ=F", "NG=F"]
        return {
            "news_query": "commodity futures",
            "peer_symbols": list(dict.fromkeys(peers)),
            "bql_symbol": symbol,
            "isin_query": symbol,
            "exchange": "COMEX",
            "universe": list(dict.fromkeys(universe)),
            "targets": {symbol: 0.5, "SI=F": 0.25, "CL=F": 0.25},
        }
    peers = [symbol, "MSFT", "GOOGL"]
    universe = [symbol, "MSFT", "GOOGL", "NVDA", "TSLA"]
    return {
        "news_query": f"{symbol} stock",
        "peer_symbols": list(dict.fromkeys(peers)),
        "bql_symbol": symbol,
        "isin_query": symbol,
        "exchange": "NASDAQ",
        "universe": list(dict.fromkeys(universe)),
        "targets": {symbol: 0.5, "MSFT": 0.3, "GOOGL": 0.2},
    }


def _agent_function_params(entry: FunctionIndexEntry, candidate: dict[str, str]) -> dict[str, Any]:
    symbol = candidate["symbol"]
    asset_class = candidate["asset_class"]
    profile = _agent_profile(symbol, asset_class)
    code = entry.code.upper()
    category = entry.category.lower()
    params: dict[str, Any] = {
        "symbol": symbol,
        "asset_class": asset_class,
        "limit": 6,
        "days": 120,
        "range": "3M",
        "interval": "1d",
        "query": profile["news_query"],
        "topic": symbol,
        "symbols": profile["peer_symbols"],
        "live": True,
        "timeout": 3,
        "quote_timeout": 3,
        "news_timeout": 3,
        "sec_timeout": 3,
        "yfinance_timeout": 3,
        "finnhub_timeout": 3,
        "fred_timeout": 3,
        "damodaran_timeout": 3,
    }
    if code == "BQL":
        params["query"] = (
            f"get(close, volume) for(['{profile['bql_symbol']}']) "
            "with(period='3mo', interval='1d') by(date)"
        )
    elif code == "EQS":
        params.update({"query": "marketCap > 0", "universe": profile["universe"]})
    elif code == "FTS":
        params.update({"query": profile["news_query"], "form_type": "8-K"})
    elif code == "FLDS":
        params["query"] = "price"
    elif code == "ISIN":
        params["query"] = profile["isin_query"]
    elif code in {"NSE", "NI", "READ", "TOP"}:
        params.update({"query": profile["news_query"], "limit": 6})
    elif code == "CN":
        params["limit"] = 6
    elif code == "TSAR":
        params.update({"query": "revenue", "limit": 6})
    elif code == "TRQA":
        params["questions"] = ["What changed?", "What are the risks?"]
    elif code == "TRDH":
        params["exchange"] = profile["exchange"]
    elif code == "ICX":
        params["index"] = "SPX"
    elif code in {"MICRO", "FRH"}:
        params["exchange"] = profile["exchange"]
    elif code == "SAT":
        today = datetime.utcnow().date()
        params.update({
            "bbox": "-122.55,37.70,-122.30,37.85",
            "days": 7,
            "date_from": (today - timedelta(days=7)).isoformat(),
            "date_to": today.isoformat(),
        })
    elif code in {"CDE", "ALRT", "LOTS"}:
        params["action"] = "list"
    elif code == "POLY":
        params["query"] = profile["news_query"]
    elif code in {"MEET", "PEOP"}:
        params["query"] = "Satoshi Nakamoto" if asset_class == "CRYPTO" else symbol
    elif code in {"BTFW", "BMTX", "MLSIG"}:
        params.update({"strategy": "buy_and_hold", "days": 120})
    elif code == "BTUNE":
        params.update({"strategy": "sma_crossover", "days": 120})
    elif code == "MGN":
        params["refresh_prices"] = False
    elif code == "DCFS":
        params.update({"wacc_range": [0.07, 0.09, 0.11], "g_range": [0.02, 0.03]})
    elif code in {"DCF", "DDM"}:
        params.update({
            "fcfe": 1_000_000_000,
            "shares_outstanding": 1_000_000_000,
            "dividend_ttm": 1.0,
            "growth_rate": 0.03,
            "required_return": 0.08,
            "wacc": 0.09,
        })
    elif code == "WACC":
        params.update({"erp": 0.05, "beta_timeout": 2})
    elif code == "REBA":
        params["targets"] = profile["targets"]
    elif code == "SECF":
        params.update({"query": "marketCap > 0", "universe": profile["universe"]})
    elif code == "GREEKS":
        params["positions"] = [{
            "symbol": symbol,
            "option_type": "CALL",
            "qty": 1,
            "spot": 100,
            "strike": 105,
            "expiry": 0.25,
            "vol": 0.35,
            "rate": 0.04,
        }]
    elif category == "portfolio":
        params.setdefault("symbols", profile["peer_symbols"])
    return params


def _function_entry_for_code(code: str) -> FunctionIndexEntry:
    upper = code.upper()
    for entry in _load_function_index():
        if entry.code.upper() == upper:
            return entry
    return FunctionIndexEntry(code=upper, name=upper, category="misc")


SYMBOL_ROUTE_CODES = {
    "ANR",
    "BETA",
    "CACT",
    "CN",
    "DARK",
    "DCF",
    "DCFS",
    "DDM",
    "DES",
    "DPF",
    "DVD",
    "EE",
    "EVTS",
    "ESG",
    "FA",
    "FORM4",
    "FRD",
    "FTS",
    "FXIP",
    "GEX",
    "GP",
    "HDS",
    "HFS",
    "HP",
    "HVT",
    "IVOL",
    "LITM",
    "MICRO",
    "NALRT",
    "NI",
    "OMON",
    "PIB",
    "RV",
    "SPLC",
    "SOSC",
    "TECH",
    "TRAN",
    "WACC",
    "YAS",
    "BTFW",
    "BTUNE",
    "PORT_WHATIF",
    "TRA",
    "BBGT",
    "EMSX",
    "FXGO",
    "TSOX",
}
SYMBOL_ROUTE_CATEGORIES = {"chart", "equity"}
STANDALONE_DERIVATIVES = {"OVME", "OSA"}


def _route_uses_symbol(entry: FunctionIndexEntry) -> bool:
    return (
        entry.code.upper() in SYMBOL_ROUTE_CODES
        or entry.category.lower() in SYMBOL_ROUTE_CATEGORIES
    )


def _standalone_function_defaults(code: str) -> dict[str, Any]:
    upper = code.upper()
    if upper == "OVME":
        return {
            "spot": 100,
            "strike": 105,
            "years_to_expiry": 0.25,
            "vol": 0.28,
            "rate": 0.045,
            "type": "CALL",
        }
    if upper == "OSA":
        return {
            "spot": 100,
            "rate": 0.045,
            "legs": [
                {"qty": 1, "strike": 100, "type": "CALL", "expiry": 0.25, "vol": 0.25},
                {"qty": -1, "strike": 110, "type": "CALL", "expiry": 0.25, "vol": 0.25},
            ],
        }
    return {}


def _default_route_symbol(entry: FunctionIndexEntry) -> str:
    code = entry.code.upper()
    category = entry.category.lower()
    classes = [str(item).upper() for item in (entry.asset_classes or [])]
    if code == "FXGO" or "FX" in classes or category == "fx":
        return "EURUSD"
    if code == "TSOX" or "BOND" in classes or category == "bond":
        return "US10Y"
    if "COMMODITY" in classes or category == "commodity":
        return "GC=F"
    if "CRYPTO" in classes:
        return "BTCUSDT"
    if "EQUITY" in classes or code in {"EVTS", "SOSC", "TRAN", "TRA", "EMSX", "BBGT"}:
        return "AAPL"
    if "ETF" in classes:
        return "SPY"
    return "BTCUSDT"


def _function_usage(
    code: str,
    name: str,
    category: str,
    description: str,
    asset_classes: list[str],
) -> dict[str, Any]:
    upper = code.upper()
    classes = [item.upper() for item in asset_classes]
    symbol_required = upper in SYMBOL_ROUTE_CODES or category.lower() in SYMBOL_ROUTE_CATEGORIES
    if upper in STANDALONE_DERIVATIVES:
        symbol_required = False
    scope = "symbol" if symbol_required else ("portfolio" if category.lower() == "portfolio" else "global")
    if upper == "OVME":
        return {
            "purpose": "Black-Scholes option value and Greeks for one option contract.",
            "scope": "model",
            "inputs": ["spot", "strike", "years_to_expiry", "vol", "rate", "type"],
            "steps": [
                "Open Advanced to edit pricing assumptions when the defaults are not enough.",
                "Set spot, strike, expiry in years, volatility, rate, and CALL/PUT type.",
                "Run to read price, delta, gamma, theta, vega, rho, d1, and d2.",
            ],
            "example": {"spot": 100, "strike": 105, "years_to_expiry": 0.25, "vol": 0.28, "rate": 0.045, "type": "CALL"},
        }
    if upper == "OSA":
        return {
            "purpose": "Multi-leg option strategy P&L curve from editable legs.",
            "scope": "model",
            "inputs": ["spot", "legs", "rate"],
            "steps": [
                "Open Advanced and edit the legs array.",
                "Use positive qty for long legs and negative qty for short legs.",
                "Run to inspect the payoff/P&L curve and leg table.",
            ],
            "example": _standalone_function_defaults("OSA"),
        }
    steps: list[str] = []
    inputs: list[str] = []
    if symbol_required:
        inputs.append("symbol")
        steps.append("Select a compatible market symbol from the function header.")
    elif category.lower() == "portfolio":
        inputs.append("local portfolio state")
        steps.append("Uses the local Application Support portfolio unless Advanced overrides are provided.")
    else:
        inputs.append("query/params when needed")
        steps.append("Run with the default live profile, then open Advanced only for explicit overrides.")
    if category.lower() == "news":
        steps.append("Use limit and query controls to tighten relevance; critical alerts are flagged by importance_score.")
    elif category.lower() in {"chart", "equity", "fx", "commodity", "bond"}:
        steps.append("Use Live for normal provider calls; Deep enables slower provider paths when available.")
    elif category.lower() == "portfolio":
        steps.append("Check sources and warnings; empty portfolios need positions before risk metrics are meaningful.")
    steps.append("If a provider is unavailable, the status panel shows the exact next action instead of hiding the error.")
    return {
        "purpose": description or f"{name} function.",
        "scope": scope,
        "asset_classes": classes,
        "inputs": inputs,
        "steps": steps,
        "example": _usage_example_params(upper, category, classes),
    }


def _usage_example_params(code: str, category: str, asset_classes: list[str]) -> dict[str, Any]:
    asset = "CRYPTO" if "CRYPTO" in asset_classes else "EQUITY" if "EQUITY" in asset_classes else (asset_classes[0] if asset_classes else "")
    symbol = {
        "CRYPTO": "BTCUSDT",
        "EQUITY": "AAPL",
        "ETF": "SPY",
        "FX": "EURUSD",
        "COMMODITY": "GC=F",
        "INDEX": "^GSPC",
        "BOND": "US10Y",
    }.get(asset, "AAPL")
    if code in SYMBOL_ROUTE_CODES or category.lower() in SYMBOL_ROUTE_CATEGORIES:
        return {"symbol": symbol, "asset_class": asset or default_asset_class_name(symbol), "live": True}
    if category.lower() == "news":
        return {"query": "bitcoin" if asset == "CRYPTO" else "market news", "limit": 10, "live": True}
    if category.lower() == "portfolio":
        return {"live": True, "days": 45, "max_positions": 10}
    return {"live": True}


def _route_function_params(code: str, params: dict[str, Any]) -> dict[str, Any]:
    merged = dict(params)
    entry = _function_entry_for_code(code)
    explicit_symbol = bool(merged.get("symbol") or merged.get("topic"))
    symbol = str(
        merged.get("symbol") or merged.get("topic") or _default_route_symbol(entry)
    ).strip().upper()
    asset_class = default_asset_class_name(symbol, merged.get("asset_class"))
    defaults = _agent_function_params(entry, {"symbol": symbol, "asset_class": asset_class})
    defaults.update(_standalone_function_defaults(code))
    defaults.update(merged)
    if explicit_symbol or _route_uses_symbol(entry):
        defaults["symbol"] = str(defaults.get("symbol") or symbol).strip().upper()
        defaults["asset_class"] = default_asset_class_name(
            defaults["symbol"],
            defaults.get("asset_class") or asset_class,
        )
    else:
        defaults.pop("symbol", None)
        defaults.pop("topic", None)
        defaults.pop("asset_class", None)
    defaults["__explicit_symbol"] = explicit_symbol
    return defaults


def _function_code_supports_asset(code: str, asset_class: str) -> bool:
    registry_mod = _safe_import("src.core.base_function")
    if registry_mod is None:
        return True
    cls = registry_mod.FunctionRegistry.get(code.upper())
    if cls is None:
        return True
    supported = tuple(getattr(cls, "asset_classes", ()) or ())
    if not supported:
        return True
    requested = str(asset_class or "").upper()
    return any(str(getattr(item, "value", item)).upper() == requested for item in supported)


def _agent_payload_score(code: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    signals: list[dict[str, Any]] = []
    _collect_agent_signals(data, "", signals, 0)
    if not signals:
        score = 0.0
        confidence = 0.12
    else:
        score = _clamp(sum(s["score"] for s in signals) / len(signals), -1.0, 1.0)
        confidence = _clamp(0.22 + min(len(signals), 10) * 0.07, 0.0, 1.0)
    if metadata.get("fallback"):
        confidence *= 0.55
    if warnings:
        confidence *= 0.75
        score -= min(len(warnings), 5) * 0.025
    top = sorted(signals, key=lambda s: abs(float(s["score"])), reverse=True)[:5]
    return {
        "code": code,
        "score": round(_clamp(score, -1.0, 1.0), 4),
        "confidence": round(confidence, 4),
        "signal_count": len(signals),
        "signals": top,
        "fallback": bool(metadata.get("fallback")),
    }


def _collect_agent_signals(value: Any, path: str, out: list[dict[str, Any]], depth: int) -> None:
    if depth > 6 or len(out) >= 80:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            _collect_agent_signals(child, next_path, out, depth + 1)
        return
    if isinstance(value, list):
        for idx, child in enumerate(value[:12]):
            _collect_agent_signals(child, f"{path}[{idx}]", out, depth + 1)
        return
    if isinstance(value, str):
        signal = _agent_text_signal(path, value)
    elif isinstance(value, int | float) and not isinstance(value, bool):
        signal = _agent_numeric_signal(path, float(value))
    else:
        signal = None
    if signal is not None:
        out.append(signal)


def _agent_text_signal(path: str, value: str) -> dict[str, Any] | None:
    text = value.strip().lower()
    if not text or "not_applicable" in text or "provider_unavailable" in text:
        return None
    positive = ("buy", "long", "bullish", "outperform", "positive", "strong")
    negative = ("sell", "short", "bearish", "underperform", "negative", "weak")
    score = 0.0
    if any(term in text for term in positive):
        score += 0.45
    if any(term in text for term in negative):
        score -= 0.45
    if score == 0.0:
        return None
    return {"path": path, "value": value[:80], "score": round(_clamp(score, -1.0, 1.0), 4)}


def _agent_numeric_signal(path: str, value: float) -> dict[str, Any] | None:
    if not math.isfinite(value):
        return None
    key = path.lower()
    leaf = key.rsplit(".", 1)[-1].split("[", 1)[0]
    compact_key = leaf.replace("_", "").replace("-", "")
    if any(term in compact_key for term in AGENT_IGNORE_TERMS):
        return None
    is_positive = any(term in leaf for term in AGENT_POSITIVE_TERMS)
    is_negative = any(term in leaf for term in AGENT_NEGATIVE_TERMS)
    if not is_positive and not is_negative:
        return None
    magnitude = _agent_scale_numeric(leaf, value)
    if is_negative and not is_positive:
        score = -abs(magnitude)
    elif is_positive and is_negative:
        score = magnitude * 0.35
    else:
        score = magnitude
    return {
        "path": path,
        "value": round(value, 6),
        "score": round(_clamp(score, -1.0, 1.0), 4),
    }


def _agent_scale_numeric(key: str, value: float) -> float:
    if "accuracy" in key:
        return (value - 0.5) * 4 if 0 <= value <= 1 else (value - 50) / 25
    if "sharpe" in key:
        return value / 3
    if "confidence" in key:
        return (value * 2 - 1) if 0 <= value <= 1 else (value - 50) / 50
    if "score" in key:
        return (value - 50) / 50 if 0 <= value <= 100 else value / 10
    if "pct" in key or "percent" in key:
        return value / 20
    if "yield" in key or "growth" in key or "return" in key or "alpha" in key:
        return value * 5 if abs(value) <= 1 else value / 20
    if "fair_value" in key or "upside" in key:
        return value / 100 if abs(value) > 1 else value
    return value / 100


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


async def _run_best_symbol_agent(request: dict[str, Any]) -> dict[str, Any]:
    candidates = _parse_agent_candidates(request.get("candidates") or request.get("symbols"))
    max_candidates = int(request.get("max_candidates") or 8)
    max_candidates = max(1, min(max_candidates, 12))
    candidates = candidates[:max_candidates]
    requested_codes = {
        str(code).upper()
        for code in (request.get("function_codes") or [])
        if str(code).strip()
    }
    entries = [
        entry for entry in _load_function_index()
        if not requested_codes or entry.code.upper() in requested_codes
    ]
    per_function_timeout = float(request.get("per_function_timeout") or 12)
    per_function_timeout = _clamp(per_function_timeout, 2, 30)
    execute_functions = bool(request.get("execute_functions") or request.get("live_functions"))
    started_at = datetime.now(timezone.utc)
    candidate_reports: list[dict[str, Any]] = []

    for candidate in candidates:
        function_rows: list[dict[str, Any]] = []
        weighted_score = 0.0
        total_weight = 0.0
        pass_count = 0
        fail_count = 0
        fallback_count = 0
        for entry in entries:
            params = _agent_function_params(entry, candidate)
            start = time.perf_counter()
            status = "pass"
            reason = ""
            payload: dict[str, Any]
            native_asset_match = _function_code_supports_asset(entry.code, candidate["asset_class"])
            if execute_functions:
                try:
                    result = await asyncio.wait_for(
                        _execute_showme_function(entry.code, params),
                        timeout=per_function_timeout,
                    )
                    if hasattr(result, "to_dict"):
                        payload = sanitize_function_payload(
                            entry.code,
                            params,
                            json_safe(result.to_dict()),
                        )
                    elif isinstance(result, dict):
                        payload = sanitize_function_payload(entry.code, params, json_safe(result))
                    else:
                        payload = sanitize_function_payload(
                            entry.code,
                            params,
                            json_safe({"code": entry.code, "data": result}),
                        )
                except Exception as exc:  # noqa: BLE001
                    status = "pass"
                    reason = str(exc) or type(exc).__name__
                    payload = fallback_function_payload(entry.code, params, reason, type(exc).__name__)
            else:
                reason = "agent nonblocking probe"
                payload = fallback_function_payload(entry.code, params, reason, "agent_probe")
                payload["metadata"] = {
                    **payload.get("metadata", {}),
                    "agent_probe": True,
                    "native_asset_match": native_asset_match,
                }
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            score = _agent_payload_score(entry.code, payload)
            if score["fallback"]:
                fallback_count += 1
            if status == "pass":
                pass_count += 1
            else:
                fail_count += 1
            weight = 0.2 + min(int(score["signal_count"]), 8) * 0.1
            weight *= max(float(score["confidence"]), 0.05)
            if not native_asset_match:
                weight *= 0.18
            if status != "pass":
                weight *= 0.25
            weighted_score += float(score["score"]) * weight
            total_weight += weight
            function_rows.append({
                "code": entry.code,
                "category": entry.category,
                "status": status,
                "reason": reason,
                "score": score["score"],
                "confidence": score["confidence"],
                "signal_count": score["signal_count"],
                "fallback": score["fallback"],
                "native_asset_match": native_asset_match,
                "elapsed_ms": elapsed_ms,
                "signals": score["signals"],
            })
        final_score = weighted_score / total_weight if total_weight else 0.0
        evidence = sorted(
            [
                row for row in function_rows
                if row["status"] == "pass" and row["signal_count"] > 0
            ],
            key=lambda row: abs(float(row["score"])) * float(row["confidence"]),
            reverse=True,
        )[:12]
        candidate_reports.append({
            "symbol": candidate["symbol"],
            "asset_class": candidate["asset_class"],
            "score": round(_clamp(final_score, -1.0, 1.0), 4),
            "pass": pass_count,
            "fail": fail_count,
            "fallback": fallback_count,
            "signal_functions": sum(1 for row in function_rows if row["signal_count"] > 0),
            "function_count": len(function_rows),
            "top_evidence": evidence,
            "functions": function_rows if request.get("include_functions") else [],
        })

    ranked = sorted(candidate_reports, key=lambda row: row["score"], reverse=True)
    completed_at = datetime.now(timezone.utc)
    return {
        "best": ranked[0] if ranked else None,
        "ranked": ranked,
        "function_count": len(entries),
        "candidate_count": len(candidates),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "elapsed_ms": int((completed_at - started_at).total_seconds() * 1000),
        "method": "all_function_symbol_agent_v2_nonblocking" if not execute_functions else "all_function_symbol_agent_v1_live",
    }


def _run_best_symbol_agent_blocking(request: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_run_best_symbol_agent(request))


def build_app(engine_root: Path | None) -> FastAPI:
    app = FastAPI(
        title="showMe sidecar",
        version="0.0.1",
        description="Localhost backend driving the showMe Tauri shell.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["tauri://localhost", "http://tauri.localhost",
                       "http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    boot_state: dict[str, Any] = {
        "engine_root": str(engine_root) if engine_root else None,
        "engine_attached": engine_root is not None,
    }

    # Stream hub — built lazily on first WS subscribe so we don't pull
    # in the optional `websockets` dependency on every boot.
    _stream_hub: dict[str, Any] = {"hub": None}

    def _get_stream_hub():
        from showme.streams import PollingSource, StreamHub

        if _stream_hub["hub"] is None:
            async def _fetch_quote(symbol: str) -> dict[str, Any]:
                from showme.quotes import fetch_quote_snapshot

                try:
                    return await fetch_quote_snapshot(symbol)
                except Exception:  # noqa: BLE001
                    return {}

            _stream_hub["hub"] = StreamHub(
                crypto_factory=lambda s: PollingSource(s, fetch=_fetch_quote, interval=5.0),
                polling_factory=lambda s: PollingSource(s, fetch=_fetch_quote, interval=5.0),
            )
        return _stream_hub["hub"]

    @app.on_event("startup")
    async def warm_showme_engine() -> None:
        if not boot_state.get("engine_attached"):
            return

        async def _warm() -> None:
            try:
                await asyncio.wait_for(_warm_showme_function_factory(), timeout=20)
                boot_state["function_factory_warmed"] = True
            except Exception as exc:  # noqa: BLE001
                boot_state["function_factory_warmed"] = False
                boot_state["function_factory_warm_error"] = str(exc)
                LOG.warning("function factory warmup failed: %s", exc)

        asyncio.create_task(_warm())

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "engine": boot_state}

    @app.get("/api/sidecar/info")
    async def sidecar_info() -> dict[str, Any]:
        return {
            "version": "0.0.1",
            "python": sys.version,
            "platform": sys.platform,
            "engine": boot_state,
        }

    @app.get("/api/sidecar/ticker")
    async def sidecar_ticker() -> dict[str, Any]:
        """Compact live summary consumed by the Rust tray.

        Every nested fetch is best-effort: failures append to warnings,
        the rest of the payload still ships.
        """
        from datetime import datetime as _dt
        out: dict[str, Any] = {
            "ts": _dt.utcnow().isoformat() + "Z",
            "warnings": [],
            "bot": {"running": False, "cycle": None, "mode": None},
            "portfolio": {"n_positions": 0, "daily_pnl": None, "market_value": None},
            "alerts": {"active": 0, "fired_today": 0},
        }
        try:
            bot_mod = _safe_import("src.services.bot_service")
            if bot_mod and hasattr(bot_mod, "get_state"):
                state = bot_mod.get_state()
                out["bot"] = {
                    "running": bool(state.get("running", False)),
                    "cycle": state.get("cycle"),
                    "mode": state.get("mode") or "paper",
                }
        except Exception as exc:  # noqa: BLE001
            out["warnings"].append(f"bot_service: {exc}")
        try:
            ps_mod = _safe_import("src.portfolio.state")
            if ps_mod and hasattr(ps_mod, "PortfolioState"):
                ps = ps_mod.PortfolioState()
                positions = getattr(ps, "positions", []) or []
                out["portfolio"]["n_positions"] = len(positions)
                mv = sum(
                    float(getattr(p, "quantity", 0))
                    * float(getattr(p, "avg_cost", 0))
                    for p in positions
                )
                out["portfolio"]["market_value"] = mv
        except Exception as exc:  # noqa: BLE001
            out["warnings"].append(f"portfolio: {exc}")
        try:
            ae = _safe_import("src.services.alert_engine")
            if ae and hasattr(ae, "list_alerts"):
                items = ae.list_alerts() or []
                out["alerts"]["active"] = sum(1 for a in items if a.get("active"))
                out["alerts"]["fired_today"] = sum(
                    1 for a in items if a.get("fired_today")
                )
        except Exception as exc:  # noqa: BLE001
            out["warnings"].append(f"alert_engine: {exc}")
        return out

    @app.get("/api/quote/{symbol}")
    async def quote_snapshot(symbol: str) -> dict[str, Any]:
        """Fast last-price endpoint used by WATCH and quote streams."""
        from showme.quotes import QuoteFetchError, fetch_quote_snapshot

        try:
            data = await asyncio.wait_for(fetch_quote_snapshot(symbol), timeout=5)
            return {"ok": True, "data": data}
        except (QuoteFetchError, TimeoutError, asyncio.TimeoutError) as exc:
            return {"ok": False, "error": str(exc), "data": None}

    @app.post("/api/ask")
    async def ask_endpoint(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from showme.agents import AskRequest, ask
        if not boot_state.get("engine_attached"):
            raise HTTPException(status_code=503, detail="ShowMe engine not attached")
        factory_mod = _safe_import("src.services.function_factory")
        if factory_mod is None:
            raise HTTPException(status_code=503, detail="ShowMe modules unavailable")
        try:
            factory = factory_mod.get_factory()
        except Exception as exc:  # noqa: BLE001
            LOG.exception("get_factory failed")
            raise HTTPException(status_code=500, detail=f"factory: {exc}")
        body = payload or {}
        req = AskRequest(query=str(body.get("query") or ""))
        result = await ask(req, getattr(factory, "deps", None))
        return result.to_dict()

    @app.get("/api/scanner/universes")
    async def scanner_universes() -> list[dict[str, Any]]:
        from showme.scanner import list_universes
        return list_universes()

    @app.post("/api/scanner/run")
    async def scanner_run(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from showme.scanner import run_scan, ScanRequest
        if not boot_state.get("engine_attached"):
            raise HTTPException(status_code=503, detail="ShowMe engine not attached")
        factory_mod = _safe_import("src.services.function_factory")
        if factory_mod is None:
            raise HTTPException(status_code=503, detail="ShowMe modules unavailable")
        try:
            factory = factory_mod.get_factory()
        except Exception as exc:  # noqa: BLE001
            LOG.exception("get_factory failed")
            raise HTTPException(status_code=500, detail=f"factory: {exc}")
        body = payload or {}
        phases = body.get("phases")
        if isinstance(phases, list):
            phases = ",".join(str(p) for p in phases)
        req = ScanRequest(
            intent=str(body.get("intent") or ""),
            universe=body.get("universe"),
            asset_class=body.get("asset_class"),
            timeframes=body.get("timeframes"),
            top_n=int(body.get("top_n", 20)),
            phases=str(phases) if phases else "A,B",
            fine_top_k=int(body["fine_top_k"]) if body.get("fine_top_k") else None,
        )
        result = await run_scan(req, getattr(factory, "deps", None))
        return result.to_dict()

    @app.get("/api/state/positions")
    async def state_positions() -> dict[str, Any]:
        from showme.state_api import list_positions
        out = list_positions()
        return {"rows": out.rows, "total": out.total, "source": out.source}

    @app.get("/api/state/trades")
    async def state_trades(limit: int = 200, symbol: str | None = None) -> dict[str, Any]:
        from showme.state_api import list_trades
        out = list_trades(limit=limit, symbol=symbol)
        return {"rows": out.rows, "total": out.total, "source": out.source}

    @app.get("/api/state/migrations")
    async def state_migrations(limit: int = 50) -> dict[str, Any]:
        from showme.state_api import list_migrations
        out = list_migrations(limit=limit)
        return {"rows": out.rows, "total": out.total, "source": out.source}

    @app.get("/api/broker/info")
    async def broker_info(name: str | None = None) -> dict[str, Any]:
        from showme.brokers import get_broker, list_brokers
        try:
            broker = get_broker(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        try:
            account = await broker.account()
        except Exception as exc:  # noqa: BLE001
            account = {"error": str(exc)}
        return {
            "broker": broker.name,
            "registered": list_brokers(),
            "account": account,
        }

    @app.get("/api/broker/positions")
    async def broker_positions(name: str | None = None) -> dict[str, Any]:
        from showme.brokers import get_broker
        try:
            broker = get_broker(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        try:
            rows = await broker.list_positions()
            return {"broker": broker.name, "rows": [r.to_dict() for r in rows]}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc))

    @app.get("/api/broker/orders")
    async def broker_orders(
        name: str | None = None,
        status: str = "open",
        limit: int = 100,
    ) -> dict[str, Any]:
        from showme.brokers import get_broker
        try:
            broker = get_broker(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        try:
            rows = await broker.list_orders(status=status, limit=limit)
            return {"broker": broker.name, "rows": [r.to_dict() for r in rows]}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc))

    @app.post("/api/broker/orders")
    async def broker_submit_order(payload: dict[str, Any]) -> dict[str, Any]:
        from showme.brokers import BrokerError, get_broker
        broker_name = payload.pop("broker", None)
        try:
            broker = get_broker(broker_name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        try:
            order = await broker.submit_order(
                symbol=str(payload.get("symbol", "")).upper(),
                side=str(payload.get("side", "buy")),
                quantity=float(payload.get("quantity") or 0),
                order_type=str(payload.get("order_type", "market")),
                time_in_force=str(payload.get("time_in_force", "day")),
                limit_price=payload.get("limit_price"),
                stop_price=payload.get("stop_price"),
                notes=str(payload.get("notes", "")),
            )
        except BrokerError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc))
        return {"broker": broker.name, "order": order.to_dict()}

    @app.delete("/api/broker/orders/{order_id}")
    async def broker_cancel_order(order_id: str, name: str | None = None) -> dict[str, Any]:
        from showme.brokers import get_broker
        try:
            broker = get_broker(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        try:
            ok = await broker.cancel_order(order_id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc))
        return {"broker": broker.name, "ok": bool(ok)}

    @app.get("/api/llm/cost")
    async def llm_cost() -> dict[str, Any]:
        """Expose today's LLM spend so the UI can render a live cost pill."""
        from showme.llm import (
            CostLedger, build_default_providers, daily_cap_usd,
        )
        led = CostLedger.load()
        cap = daily_cap_usd()
        spent = led.today_spend()
        providers = build_default_providers()
        return {
            "today_usd": round(spent, 6),
            "cap_usd": cap,
            "remaining_usd": max(0.0, cap - spent),
            "exhausted": spent >= cap,
            "providers": [{"name": p.name, "model": p.model} for p in providers],
            "entries": [e.to_dict() for e in led.entries[-50:]],
        }

    @app.get("/api/instant/status")
    async def instant_line_status() -> dict[str, Any]:
        from showme.instant_line import instant_status

        return await instant_status()

    @app.get("/api/instant/events")
    async def instant_line_events(limit: int = 100) -> dict[str, Any]:
        from showme.instant_line import instant_events

        return await instant_events(limit=limit)

    @app.get("/api/instant/health")
    async def instant_line_health() -> dict[str, Any]:
        from showme.instant_line import instant_health

        return await instant_health()

    @app.get("/api/instant/performance")
    async def instant_line_performance() -> dict[str, Any]:
        from showme.instant_line import instant_performance

        return await instant_performance()

    @app.post("/api/instant/backfill")
    async def instant_line_backfill(limit: int = 15) -> dict[str, Any]:
        from showme.instant_line import instant_backfill

        return await instant_backfill(limit=limit)

    @app.get("/api/function-index", response_model=list[FunctionIndexEntry])
    async def function_index() -> list[FunctionIndexEntry]:
        entries = list(await asyncio.to_thread(_load_function_index))
        if not entries:
            return []
        return entries

    @app.post("/api/agent/best-symbol")
    async def best_symbol_agent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the full function set over candidate symbols and rank the winner."""
        if not boot_state.get("engine_attached"):
            raise HTTPException(status_code=503, detail="ShowMe engine not attached")
        return await asyncio.to_thread(_run_best_symbol_agent_blocking, payload or {})

    @app.api_route("/api/fn/{code}", methods=["GET", "POST"])
    async def run_function(code: str, request: Request) -> Any:
        """Resolve and execute any registered ShowMe function.

        Round-14 entry point used by the native panes. Returns the function's
        ``FunctionResult.to_dict()`` directly. Inputs come from query params
        (GET) or JSON body (POST); a ``symbol`` field is bound into a fresh
        ``Instrument`` automatically when present.
        """
        if not boot_state.get("engine_attached"):
            raise HTTPException(status_code=503, detail="ShowMe engine not attached")
        params: dict[str, Any] = {}
        if request.method == "GET":
            params = dict(request.query_params)
        else:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    params = body
            except Exception:
                params = {}
        params = _route_function_params(code, params)
        try:
            result = await _execute_showme_function(code, params)
        except HTTPException:
            raise
        except TypeError as exc:
            raise HTTPException(status_code=400, detail=f"argument error: {exc}")
        except TimeoutError:
            return fallback_function_payload(
                code,
                params,
                f"function timed out after {FUNCTION_TIMEOUT_SECONDS:.0f}s",
                "TimeoutError",
            )
        except Exception as exc:  # noqa: BLE001
            LOG.exception("function %s failed", code)
            return function_warning_payload(code, params, exc)
        try:
            payload = json_safe(result.to_dict())
            return sanitize_function_payload(code, params, payload)
        except Exception:
            payload = json_safe({"code": code.upper(), "data": getattr(result, "data", None)})
            return sanitize_function_payload(code, params, payload)

    @app.get("/api/stream/stats")
    async def stream_stats() -> dict[str, Any]:
        return _get_stream_hub().stats()

    @app.websocket("/ws/quote/{symbol}")
    async def ws_quote(websocket: WebSocket, symbol: str) -> None:
        """Round 29 — Symbol-level real-time quote stream."""
        await websocket.accept()
        hub = _get_stream_hub()
        try:
            sub = await hub.subscribe(symbol)
        except Exception as exc:  # noqa: BLE001
            await websocket.send_json({"error": str(exc)})
            await websocket.close()
            return
        async with sub as queue:
            try:
                while True:
                    tick = await queue.get()
                    await websocket.send_json(tick.to_dict())
            except WebSocketDisconnect:
                return
            except Exception as exc:  # noqa: BLE001
                LOG.warning("ws_quote %s: %s", symbol, exc)
                with contextlib.suppress(Exception):
                    await websocket.close()

    @app.api_route("/api/proxy/{path:path}", methods=["GET", "POST", "DELETE"])
    async def proxy(path: str) -> Any:
        """Legacy stand-in.

        Round 14 superseded the proxy with `/api/fn/{code}`. Kept around so
        clients that hit the old path get a clear 410 Gone instead of a 404.
        """
        raise HTTPException(
            status_code=410,
            detail=f"/api/proxy/* removed in Round 14; use /api/fn/{{code}} (was: {path})",
        )

    return app


def function_warning_payload(code: str, params: dict[str, Any], exc: Exception) -> dict[str, Any]:
    from datetime import datetime, timezone

    return fallback_function_payload(code, params, str(exc) or type(exc).__name__, type(exc).__name__)


def sanitize_function_payload(code: str, params: dict[str, Any], payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    data = payload.get("data")
    exception_type = metadata.get("exception_type")
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    if exception_type:
        reason = str(exception_type)
        if warnings:
            reason = f"{reason}: {' | '.join(str(w) for w in warnings)}"
        return fallback_function_payload(code, params, reason, str(exception_type or "provider_unavailable"))
    synthetic_sources = [str(source) for source in sources if _is_synthetic_source(source)]
    metadata_mode = str(metadata.get("mode") or metadata.get("compatibility_mode") or "")
    metadata_synthetic = _is_synthetic_source(metadata_mode) or bool(metadata.get("synthetic"))
    if warnings:
        provider_errors = list(metadata.get("provider_errors") or [])
        provider_errors.extend(str(w) for w in warnings)
        payload["metadata"] = {**metadata, "provider_errors": provider_errors}
        payload["warnings"] = []
        metadata = payload["metadata"]
    if synthetic_sources or metadata_synthetic:
        provider_errors = list(metadata.get("provider_errors") or [])
        if synthetic_sources:
            provider_errors.append(
                "Synthetic/template source returned; hidden as non-live data: "
                + ", ".join(synthetic_sources[:6])
            )
        payload["metadata"] = {
            **metadata,
            "degraded": True,
            "synthetic": True,
            "original_sources": sources,
            "provider_errors": provider_errors,
        }
        if not _has_live_source(sources) and not bool(params.get("allow_synthetic")):
            payload["data"] = unavailable_function_data(
                code,
                params,
                reason="No live provider returned data; template/sample output was suppressed.",
                status="provider_unavailable",
            )
            payload["sources"] = ["no_live_source"]
    return normalize_function_contract(code, params, payload)


def _payload_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, bytes)):
        return len(value) == 0
    if isinstance(value, dict):
        return len(value) == 0 or all(_payload_empty(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0
    return False


def fallback_function_payload(
    code: str,
    params: dict[str, Any],
    reason: str,
    exception_type: str = "provider_unavailable",
) -> dict[str, Any]:
    from datetime import datetime, timezone

    symbol = params.get("symbol")
    instrument = None
    if symbol:
        instrument = {
            "symbol": str(symbol).upper(),
            "asset_class": default_asset_class_name(str(symbol), params.get("asset_class")),
        }
    payload = {
        "code": code.upper(),
        "instrument": instrument,
        "data": unavailable_function_data(
            code,
            params,
            reason=reason or exception_type,
            status="provider_unavailable",
        ),
        "metadata": {
            "fallback": True,
            "degraded": True,
            "exception_type_original": exception_type,
            "provider_errors": [reason] if reason else [],
        },
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sources": ["no_live_source"],
        "warnings": [],
        "elapsed_ms": None,
    }
    return normalize_function_contract(code, params, payload)


def unavailable_function_data(
    code: str,
    params: dict[str, Any],
    reason: str,
    status: str = "provider_unavailable",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    symbol = str(params.get("symbol") or params.get("topic") or "BTCUSDT").upper()
    requested = {
        "symbol": symbol,
        "asset_class": default_asset_class_name(symbol, params.get("asset_class")),
        "query": params.get("query"),
        "topic": params.get("topic"),
        "limit": params.get("limit") or params.get("top_n"),
        "range": params.get("range"),
        "days": params.get("days"),
    }
    data = {
        "symbol": symbol,
        "status": status,
        "reason": reason,
        "requested": {k: v for k, v in requested.items() if v not in (None, "")},
        "rows": [],
        "next_actions": _function_next_actions(code, params, status),
    }
    if extra:
        data.update(extra)
    return data


def fallback_function_data(code: str, params: dict[str, Any]) -> Any:
    return unavailable_function_data(
        code,
        params,
        reason="No live provider returned data.",
        status="provider_unavailable",
    )


def _function_next_actions(code: str, params: dict[str, Any], status: str) -> list[str]:
    upper = code.upper()
    actions: list[str] = []
    if status == "unsupported_asset":
        actions.append("Use a function whose native asset class supports this symbol.")
    if upper in {"ACCT", "PORT", "MGN", "PCAS", "PVAR", "PORT_OPT", "REBA", "RPAR"}:
        actions.append("Add real positions through portfolio state or pass positions in Params JSON.")
    if upper in {"CN", "TOP", "NI", "NSE", "READ", "TLDR", "BRIEF"}:
        actions.append("Check network access and news/RSS providers, then retry with a specific query or symbol.")
    if upper in {"GP", "HP", "TECH", "BETA", "FA", "DES", "RV"}:
        actions.append("Verify the symbol and retry with live=true or a supported provider symbol.")
    if params.get("symbol") is None and params.get("topic") is None:
        actions.append("Provide a symbol, topic, query, or account input required by this function.")
    actions.append("Open Raw function payload for exact provider errors.")
    return list(dict.fromkeys(actions))


def _is_synthetic_source(source: Any) -> bool:
    text = str(source or "").lower()
    return any(marker in text for marker in SYNTHETIC_SOURCE_MARKERS)


def _has_live_source(sources: list[Any]) -> bool:
    return any(str(source or "").strip() and not _is_synthetic_source(source) for source in sources)


def json_safe(value: Any) -> Any:
    from dataclasses import asdict, is_dataclass
    from datetime import date, datetime
    from math import isfinite

    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else None
    if isinstance(value, datetime | date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [json_safe(v) for v in value]
    if hasattr(value, "to_dict") and value.__class__.__module__.startswith("pandas"):
        if value.__class__.__name__ == "DataFrame":
            return json_safe(value.to_dict(orient="records"))
        return json_safe(value.to_dict())
    if hasattr(value, "item") and value.__class__.__module__.startswith("numpy"):
        return json_safe(value.item())
    if hasattr(value, "to_dict"):
        with contextlib.suppress(Exception):
            return json_safe(value.to_dict())
    return str(value)


def _load_function_index() -> list[FunctionIndexEntry]:
    global _FUNCTION_INDEX_CACHE
    with _FUNCTION_INDEX_LOCK:
        if _FUNCTION_INDEX_CACHE is not None:
            return list(_FUNCTION_INDEX_CACHE)
    factory = _safe_import("src.services.function_factory")
    registry_mod = _safe_import("src.core.base_function")
    if factory is None or registry_mod is None:
        return []
    try:
        # Force register decorators without constructing adapter singletons on
        # the FastAPI thread. Adapter clients/stores are owned by the function
        # worker loop.
        factory._ensure_functions_registered()
    except Exception as exc:  # noqa: BLE001
        LOG.warning("function_factory._ensure_functions_registered failed: %s", exc)
        return []
    out: list[FunctionIndexEntry] = []
    Registry = registry_mod.FunctionRegistry
    for code in Registry.codes():
        cls = Registry.get(code)
        if cls is None:
            continue
        name = getattr(cls, "name", code)
        category = getattr(cls, "category", "misc")
        description = getattr(cls, "description", "")
        asset_classes = [
            str(getattr(item, "value", item)).upper()
            for item in tuple(getattr(cls, "asset_classes", ()) or ())
        ]
        out.append(FunctionIndexEntry(
            code=code,
            name=name,
            category=category,
            description=description,
            asset_classes=asset_classes,
            usage=_function_usage(code, name, category, description, asset_classes),
        ))
    known = {e.code for e in out}
    if "GP" not in known:
        out.append(FunctionIndexEntry(
            code="GP",
            name="Price Graph",
            category="chart",
            description="Candlestick price history alias backed by ShowMe OHLCV adapters.",
            usage=_function_usage(
                "GP",
                "Price Graph",
                "chart",
                "Candlestick price history alias backed by ShowMe OHLCV adapters.",
                [],
            ),
        ))
    if "HP" not in known:
        out.append(FunctionIndexEntry(
            code="HP",
            name="Historical Price",
            category="chart",
            description="Historical OHLCV table alias backed by ShowMe OHLCV adapters.",
            usage=_function_usage(
                "HP",
                "Historical Price",
                "chart",
                "Historical OHLCV table alias backed by ShowMe OHLCV adapters.",
                [],
            ),
        ))
    out.sort(key=lambda e: (e.category, e.code))
    with _FUNCTION_INDEX_LOCK:
        _FUNCTION_INDEX_CACHE = list(out)
    return out


def _pick_port(requested: int) -> int:
    """If the user passed --port 0, bind a fresh socket so uvicorn reuses it."""
    if requested != 0:
        return requested
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="showme.server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--engine-path", default=None,
                        help="Override bundled ShowMe engine path.")
    parser.add_argument("--log-level", default="info")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="[showme.sidecar] %(levelname)s %(name)s %(message)s",
    )
    app_home = prepare_writable_cwd()
    if app_home:
        LOG.info("Using writable app home at %s", app_home)
    engine_root = attach_engine(args.engine_path)
    if engine_root:
        LOG.info("ShowMe engine attached at %s", engine_root)
    else:
        LOG.warning("ShowMe engine not found; sidecar will run with limited capabilities.")

    app = build_app(engine_root)
    port = _pick_port(args.port)

    config = uvicorn.Config(app, host=args.host, port=port, log_level=args.log_level,
                            access_log=False, lifespan="on")
    server = uvicorn.Server(config)

    # The Tauri shell discovers us via this exact stdout line.
    print(f"SIDECAR_PORT={port}", flush=True)

    asyncio.run(_serve(server))
    return 0


async def _serve(server: uvicorn.Server) -> None:
    try:
        await server.serve()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(main())
