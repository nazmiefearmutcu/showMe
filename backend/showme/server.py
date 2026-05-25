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


def _pin_bundled_cacert() -> None:
    """SEC-11: pin certifi's cacert.pem before any HTTP backend loads.

    PyInstaller bundles relocate libssl/libcrypto; ``ssl.get_default_verify_paths``
    returns the COMPILED-IN OpenSSL path, which is the BUILD host's path —
    not present on the user's machine. ``curl_cffi`` captures ``DEFAULT_CACERT``
    at module import, so we MUST export the env var BEFORE any
    ``from curl_cffi import requests`` happens (yfinance 1.3+, screener,
    holders, history, ...).

    Idempotent: only sets env vars if they are not already set, so users
    can override via their environment for testing.
    """
    import os as _os
    try:
        import certifi as _certifi  # type: ignore[import-not-found]
    except ImportError:
        return
    bundle = _certifi.where()
    if bundle and _os.path.isfile(bundle):
        _os.environ.setdefault("SSL_CERT_FILE", bundle)
        _os.environ.setdefault("CURL_CA_BUNDLE", bundle)
        _os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)


_pin_bundled_cacert()

import argparse
import asyncio
import contextlib
import shutil
import importlib
import logging
import os
import resource
import socket
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import uvicorn
from fastapi import (
    FastAPI,
    HTTPException,
    Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from showme.crypto_aliases import (
    CRYPTO_BASES,
    CRYPTO_QUOTE_SUFFIXES,
    is_crypto_symbol as crypto_alias_is_crypto_symbol,
    resolve_crypto_symbol_alias,
)
from showme.chart_history import (
    DEFAULT_BARS as DEFAULT_HISTORY_BARS,
    fetch_longest_history,
    normalize_history_interval,
    parse_history_bars,
)
from showme.function_contracts import normalize_function_contract

LOG = logging.getLogger("showme.server")
# After the unified-tree refactor the engine is a regular Python subpackage
# (`showme.engine`). DEFAULT_ENGINE now resolves to that subpackage's directory
# so legacy callers and the PyInstaller bundle can still locate engine config
# files via SHOWME_ENGINE_ROOT.
DEFAULT_ENGINE = (Path(__file__).resolve().parent / "engine").resolve()
FUNCTION_TIMEOUT_SECONDS = float(os.environ.get("SHOWME_FUNCTION_TIMEOUT_SECONDS", "45"))
CRYPTO_SYMBOLS = set(CRYPTO_BASES)
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
BOND_SYMBOLS = {"US1M", "US3M", "US6M", "US1Y", "US2Y", "US3Y", "US5Y", "US7Y", "US10Y", "US20Y", "US30Y"}
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
    "_model",
    "_baseline",
    "_defaults",
    "reference",
    "auction_model",
    "auction_fallback",
    "tax_loss_model",
    "total_return_model",
    "briefing_model",
    "deterministic_tldr",
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
    """Ensure ``SHOWME_HOME`` is published before the engine boots.

    Per ARCH-09 P0: the original ``os.chdir(app_home)`` was the only thing
    keeping the engine's hardcoded ``Path("runtime/...")`` literals pointed
    at the right directory. We now route every store through
    ``showme.app_paths.runtime_path`` so the chdir is no longer necessary;
    we keep the home/runtime directories ensured + the env var published
    for any sub-process that consults it.
    """
    if not getattr(sys, "_MEIPASS", None):
        return None
    app_home = Path(os.environ.get("SHOWME_HOME", _default_app_home())).expanduser()
    app_home.mkdir(parents=True, exist_ok=True)
    (app_home / "runtime").mkdir(parents=True, exist_ok=True)
    if _env_truthy("SHOWME_MIRROR_LEGACY_RUNTIME"):
        mirror_legacy_runtime(app_home)
    os.environ.setdefault("SHOWME_HOME", str(app_home))
    return app_home


def ensure_app_home_env() -> Path:
    """Publish the canonical showMe state root for dev and packaged runtimes."""
    app_home = Path(os.environ.get("SHOWME_HOME", _default_app_home())).expanduser()
    (app_home / "runtime").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("SHOWME_HOME", str(app_home))
    return app_home


def _env_truthy(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_truthy_default(name: str, default: str) -> bool:
    """Like ``_env_truthy`` but returns the truthiness of ``default`` when unset."""
    value = os.environ.get(name)
    if value is None:
        value = default
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
    """Resolve the bundled engine root for config loading.

    Post-refactor the engine is a real Python subpackage (``showme.engine``)
    imported through normal package resolution — no ``sys.path`` injection
    needed. This helper still publishes ``SHOWME_ENGINE_ROOT`` so engine code
    that reads adjacent ``config/*.yaml`` files keeps working in dev,
    PyInstaller, and ``SHOWME_ENGINE_PATH``-overridden setups.
    """
    candidates: list[Path] = []
    if engine_path:
        candidates.append(Path(engine_path).expanduser())
    else:
        frozen_root = getattr(sys, "_MEIPASS", None)
        if frozen_root:
            # PyInstaller extracts add-data entries under _MEIPASS; the
            # engine package and its sibling config/ live there.
            candidates.append(Path(frozen_root) / "showme" / "engine")
            candidates.append(Path(frozen_root))
        candidates.append(DEFAULT_ENGINE)
    for raw in candidates:
        candidate = raw.resolve()
        # Accept either the new unified layout (engine package directly) or
        # the legacy layout (<root>/src/) for backwards compatibility.
        if candidate.is_dir() and (
            (candidate / "indicators").is_dir() or (candidate / "src").is_dir()
        ):
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
# PERF-09: build lock held across the (slow) 112-module registration walk so
# a second arrival blocks on the in-flight build instead of redoing it.
# Python's import lock would serialize both walks anyway; without this we
# pay 2x wall-clock when the warmup thread races the first request.
_FUNCTION_INDEX_BUILD_LOCK = threading.Lock()


def _function_worker() -> _ShowMeFunctionWorker:
    global _FUNCTION_WORKER
    if _FUNCTION_WORKER is None:
        _FUNCTION_WORKER = _ShowMeFunctionWorker()
    return _FUNCTION_WORKER


async def _execute_showme_function(code: str, params: dict[str, Any]) -> Any:
    return await _function_worker().execute(code, params)


async def _warm_showme_function_factory_on_worker() -> None:
    factory_mod = _safe_import("showme.engine.services.function_factory")
    if factory_mod is None:
        return
    current_factory = getattr(factory_mod, "_factory", None)
    owner = getattr(current_factory, "_showme_worker_thread", None)
    if current_factory is not None and owner != threading.get_ident():
        factory_mod._factory = None
    factory = factory_mod.get_factory()
    factory._showme_worker_thread = threading.get_ident()


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
    registry_mod = _safe_import("showme.engine.core.base_function")
    instrument_mod = _safe_import("showme.engine.core.instrument")
    data_source_mod = _safe_import("showme.engine.core.base_data_source")
    factory_mod = _safe_import("showme.engine.services.function_factory")
    if not (registry_mod and instrument_mod and factory_mod):
        raise HTTPException(status_code=503, detail="ShowMe modules unavailable")
    try:
        current_factory = getattr(factory_mod, "_factory", None)
        owner = getattr(current_factory, "_showme_worker_thread", None)
        if current_factory is not None and owner != threading.get_ident():
            factory_mod._factory = None
        factory = factory_mod.get_factory()
        factory._showme_worker_thread = threading.get_ident()
    except Exception as exc:  # noqa: BLE001
        LOG.exception("get_factory failed")
        raise HTTPException(status_code=500, detail=f"factory: {exc}") from exc
    upper_code = code.upper()
    local_params = dict(params)
    symbol = local_params.pop("symbol", None)
    instrument = None
    if symbol:
        try:
            AssetClass = instrument_mod.AssetClass
            Instrument = instrument_mod.Instrument
            requested_asset_class = local_params.pop("asset_class", None)
            canonical_symbol = _canonical_route_symbol(symbol, requested_asset_class)
            ac_name = default_asset_class_name(canonical_symbol, requested_asset_class)
            ac = getattr(AssetClass, ac_name, AssetClass.EQUITY)
            instrument = Instrument(symbol=canonical_symbol, asset_class=ac)
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
    days = _history_days_from_params(params)
    interval = normalize_history_interval(params.get("interval") or params.get("resolution") or "1d")
    bars = parse_history_bars(
        params.get("bars") or params.get("bar_count") or params.get("tail") or params.get("limit"),
        default=DEFAULT_HISTORY_BARS,
    )
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    source_name = ""
    try:
        history = await fetch_longest_history(
            symbol=getattr(instrument, "symbol", ""),
            asset_class=str(asset_class).upper(),
            interval=interval,
            days=days,
            bars=bars,
        )
        if history.rows:
            FunctionResult = registry_mod.FunctionResult
            return FunctionResult(
                code=code,
                instrument=instrument,
                data={
                    "ohlcv": history.rows,
                    "bars": history.rows,
                    "rows": history.rows,
                    "status": "ok",
                    "resolution": interval,
                    "bar_count": len(history.rows),
                    "deep_history": True,
                    "winner": history.source,
                    "sources_considered": history.metadata.get(
                        "sources_considered", []
                    ),
                    "selection_reason": history.metadata.get(
                        "selection_reason", "oldest_first_bar"
                    ),
                    "winner_first_ts_ms": history.metadata.get(
                        "winner_first_ts_ms"
                    ),
                },
                sources=[history.source],
                warnings=history.warnings,
                metadata={"alias": "price_history", **history.metadata},
            )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"longest_history: {exc}")
    for name, adapter in adapter_candidates:
        if adapter is None:
            continue
        try:
            df = await adapter.fetch(data_source_mod.DataRequest(
                kind=data_source_mod.DataKind.OHLCV,
                instrument=instrument,
                start=datetime.now(timezone.utc) - timedelta(days=days),
                interval=interval,
                limit=bars,
                extra={"days": days, "timeout": 12},
            ))
            rows = _history_rows(df)
            if rows:
                source_name = name
                break
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{name}: {exc}")
    if not rows:
        warnings.append("no price history")
    FunctionResult = registry_mod.FunctionResult
    return FunctionResult(
        code=code,
        instrument=instrument,
        data={
            "ohlcv": rows,
            "bars": rows,
            "rows": rows,
            "winner": source_name or None,
            "sources_considered": [],
            "selection_reason": "adapter_fallback",
            "winner_first_ts_ms": None,
        },
        sources=[source_name] if source_name else [],
        warnings=warnings,
        metadata={
            "alias": "price_history",
            "days": days,
            "interval": interval,
            "bars_requested": bars,
            "bars_returned": len(rows),
            "deep_history": False,
            "selection_reason": "adapter_fallback",
        },
    )


def _history_days_from_params(params: dict[str, Any]) -> int:
    value = params.get("days") or _days_from_range(params.get("range"))
    try:
        days = int(float(value))
    except Exception:
        days = 365
    return max(1, min(365 * 50, days))


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
    """Resolve the asset-class name for ``symbol``.

    Honors an explicit ``requested`` override first, otherwise falls
    through the heuristic ladder: crypto → fx → commodity → index → bond
    → equity. Symbol aliases are resolved without a network call so this
    is safe to invoke on every request.
    """
    if requested:
        return str(requested).upper()
    resolved = resolve_crypto_symbol_alias(symbol, allow_network=False)
    if looks_like_crypto_symbol(resolved):
        return "CRYPTO"
    if looks_like_fx_symbol(resolved):
        return "FX"
    if looks_like_commodity_symbol(resolved):
        return "COMMODITY"
    if looks_like_index_symbol(resolved):
        return "INDEX"
    if looks_like_bond_symbol(resolved):
        return "BOND"
    return "EQUITY"


def looks_like_crypto_symbol(symbol: str | None) -> bool:
    """Return True for crypto tickers, e.g. ``BTC``, ``ETHUSDT``, ``BTC-USD``.

    Uses the canonical Binance/exchange suffix list and the bundled
    ``crypto_aliases.is_crypto_symbol`` knowledge so we treat ``BNB`` as
    crypto without needing to check it against every quote suffix.
    """
    if not symbol:
        return False
    value = resolve_crypto_symbol_alias(symbol, allow_network=False).upper().replace("-", "").replace("/", "")
    if crypto_alias_is_crypto_symbol(value):
        return True
    if value in CRYPTO_SYMBOLS:
        return True
    return any(
        value.endswith(suffix)
        and value[: -len(suffix)] in CRYPTO_SYMBOLS
        and len(value) > len(suffix)
        for suffix in CRYPTO_QUOTE_SUFFIXES
    )


def looks_like_fx_symbol(symbol: str | None) -> bool:
    """Return True for 6-char ISO currency pairs (``EURUSD``, ``GBPJPY``).

    Strips the ``=X`` Yahoo suffix and ``/``/``-`` separators so callers
    don't have to normalise upstream.
    """
    if not symbol:
        return False
    value = symbol.upper().replace("/", "").replace("-", "").removesuffix("=X")
    if len(value) != 6:
        return False
    return value[:3] in FX_CURRENCIES and value[3:] in FX_CURRENCIES


def looks_like_commodity_symbol(symbol: str | None) -> bool:
    """Return True for futures/spot commodity codes (``GC=F``, ``XAUUSD``)."""
    if not symbol:
        return False
    value = symbol.upper()
    if value.endswith("=F") and value[:-2] in COMMODITY_FUTURES:
        return True
    return value in {"XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD", "WTI", "BRENT"}


def looks_like_index_symbol(symbol: str | None) -> bool:
    """Return True for known equity index codes (``^GSPC``, ``^IXIC``)."""
    if not symbol:
        return False
    value = symbol.upper().lstrip("^")
    return value in INDEX_SYMBOLS


def looks_like_bond_symbol(symbol: str | None) -> bool:
    """Return True for known sovereign bond tickers (``US10Y``, ``DE10Y``)."""
    if not symbol:
        return False
    value = symbol.upper().replace("-", "")
    return value in BOND_SYMBOLS


# Per SEC-05: Pydantic request models live in `server_routes._models` so the
# route family files can import them without circular references. The
# legacy names are re-exported here for back-compat with `from
# showme.server import OrderRequest` style imports.
from showme.server_routes._models import (  # noqa: E402, F401
    AskBody,
    BestSymbolBody,
    FunctionIndexEntry,
    InstantBackfillBody,
    OrderRequest,
    ScannerRunBody,
    VeryfinderBatchRequest,
    WatchlistBody,
    XAnalyzeBody,
    XClassifyBody,
)


# Per ARCH-07 / PY-LINT-03 (R3A): agent-runtime helpers live in
# `server_routes._agent_runtime` so this module stays under 1,300 lines.
# Public symbols are re-exported here for backward compatibility.
from showme.server_routes._agent_runtime import (  # noqa: E402, F401
    AGENT_DEFAULT_CANDIDATES,
    AGENT_EXCLUDED_FUNCTIONS,
    AGENT_IGNORE_TERMS,
    AGENT_LOCAL_SIGNAL_CODES,
    AGENT_LOCAL_SIGNAL_PROFILES,
    AGENT_NEGATIVE_TERMS,
    AGENT_POSITIVE_TERMS,
    STANDALONE_DERIVATIVES,
    SYMBOL_ROUTE_CATEGORIES,
    SYMBOL_ROUTE_CODES,
    _agent_function_params,
    _agent_local_profile,
    _agent_numeric_signal,
    _agent_payload_score,
    _agent_probe_data_for_code,
    _agent_probe_payload,
    _agent_profile,
    _agent_scale_numeric,
    _agent_symbol_bias,
    _agent_text_signal,
    _canonical_route_symbol,
    _clamp,
    _collect_agent_signals,
    _default_route_symbol,
    _function_code_supports_asset,
    _function_entry_for_code,
    _function_usage,
    _parse_agent_candidates,
    _route_function_params,
    _route_uses_symbol,
    _run_best_symbol_agent,
    _run_best_symbol_agent_blocking,
    _standalone_function_defaults,
    _usage_example_params,
)


def _install_middlewares(app: FastAPI) -> None:
    """Mount CORS + body-size + auth middlewares.

    The auth-token contract is FROZEN:
        * ``SHOWME_AUTH_TOKEN`` unset -> middleware is a no-op.
        * Token set -> every ``/api/*`` request needs a matching
          ``X-ShowMe-Token`` (or Bearer authorization) except for the two
          exempt liveness probes.
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["tauri://localhost", "http://tauri.localhost",
                       "http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    # Per SEC-05 P1: cap inbound POST/PUT bodies so a local caller cannot
    # tip the worker pool over with a multi-megabyte JSON payload. 256 KB is
    # comfortably above every legitimate body in this app (largest is the
    # function-index POST which is small).
    max_body_size_bytes = int(os.environ.get("SHOWME_MAX_BODY_BYTES", "262144"))

    @app.middleware("http")
    async def body_size_limit_middleware(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH"}:
            cl = request.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > max_body_size_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            f"request body exceeds limit "
                            f"({cl} > {max_body_size_bytes} bytes)"
                        ),
                    },
                )
        return await call_next(request)

    # Auth middleware (per task spec). When SHOWME_AUTH_TOKEN is unset
    # (dev/test) the check is skipped entirely. Two exempt paths so the
    # Tauri shell + tray can probe sidecar liveness without the token.
    auth_exempt_paths = {"/api/health", "/api/x/health"}

    @app.middleware("http")
    async def auth_token_middleware(request: Request, call_next):
        expected = os.environ.get("SHOWME_AUTH_TOKEN")
        if (
            expected
            # CORS preflight requests do NOT carry auth headers — browsers
            # send them automatically before the real POST. Letting the
            # middleware 401 the preflight would kill every cross-origin
            # POST from the Tauri renderer (verified live on 2026-05-11).
            and request.method != "OPTIONS"
            and request.url.path.startswith("/api/")
            and request.url.path not in auth_exempt_paths
        ):
            provided = (
                request.headers.get("X-ShowMe-Token")
                or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            )
            # SEC-14: constant-time comparison. Plain ``!=`` leaks token
            # bytes through measurable latency (the sidecar listens on
            # 127.0.0.1 but co-resident processes can still observe sub-
            # microsecond timing). hmac.compare_digest pads both operands
            # to the same length and compares byte-by-byte without short-
            # circuiting.
            import hmac as _hmac
            if not _hmac.compare_digest(provided or "", expected):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "missing or invalid X-ShowMe-Token"},
                )
        return await call_next(request)


def _make_stream_hub_provider() -> Callable[[], Any]:
    """Return a lazy stream-hub provider.

    Per PERF-04 P1: prefer BinanceWsSource for realtime crypto ticks, but
    fall back to BinanceRestSource (5 s polling) on SSL / network failure.
    Some operator environments (corporate MITM proxies, custom root CAs,
    aggressive antivirus) can break Binance's WSS handshake even when
    plain HTTPS works — the live build saw exactly this on 2026-05-11.
    The hybrid source tries WSS first; if no tick arrives within 10 s OR
    the WSS leg raises, it switches to the REST poller for that channel.
    """
    state: dict[str, Any] = {"hub": None}

    def get_stream_hub() -> Any:
        from showme.streams import (
            BinanceHybridSource,
            PollingSource,
            StreamHub,
        )

        if state["hub"] is None:
            async def _fetch_quote(symbol: str) -> dict[str, Any]:
                from showme.quotes import fetch_quote_snapshot

                try:
                    return await fetch_quote_snapshot(symbol)
                except Exception:  # noqa: BLE001
                    return {}

            state["hub"] = StreamHub(
                crypto_factory=lambda s: BinanceHybridSource(s),
                polling_factory=lambda s: PollingSource(s, fetch=_fetch_quote, interval=5.0),
            )
        return state["hub"]

    # Per R4B: attach the closure-captured state dict so the FastAPI lifespan
    # shutdown branch can introspect "is a hub instance live?" without forcing
    # construction.
    get_stream_hub._state = state  # type: ignore[attr-defined]
    return get_stream_hub


async def _shutdown_cleanup(stream_hub_provider: Callable[[], Any]) -> None:
    """Graceful-shutdown helper called from the lifespan finally block.

    Each step is wrapped in try/except + ``LOG.exception`` so a failure in
    one cleanup does not block the others. None of the helpers are mandatory
    — we look them up by name and skip if absent.
    """
    # 1) Close an already-instantiated StreamHub, if one was ever built.
    try:
        hub_state = getattr(stream_hub_provider, "_state", None)
        hub_instance = hub_state.get("hub") if isinstance(hub_state, dict) else None
        if hub_instance is not None:
            close = getattr(hub_instance, "close", None) or getattr(hub_instance, "aclose", None)
            if close is not None:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
    except Exception:  # noqa: BLE001
        LOG.exception("stream hub shutdown failed")
    # 2) Flush order-history persistence, if the helper exists.
    try:
        order_history_mod = _safe_import("showme.engine.services.order_history")
        if order_history_mod is not None:
            flush = getattr(order_history_mod, "flush", None)
            if flush is not None:
                result = flush()
                if asyncio.iscoroutine(result):
                    await result
    except Exception:  # noqa: BLE001
        LOG.exception("order_history flush failed")
    # 3) Close any open broker connections via a registry hook, if exposed.
    try:
        broker_mod = _safe_import("showme.brokers")
        if broker_mod is not None:
            close_all = getattr(broker_mod, "close_all_brokers", None)
            if close_all is not None:
                result = close_all()
                if asyncio.iscoroutine(result):
                    await result
    except Exception:  # noqa: BLE001
        LOG.exception("broker connection shutdown failed")
    # 4) Close shared httpx.AsyncClient owned by the provider adapter layer
    #    so dangling connectors don't leak on shutdown.
    try:
        providers_mod = _safe_import("showme.providers")
        if providers_mod is not None:
            aclose_shared = getattr(providers_mod, "aclose_shared", None)
            if aclose_shared is not None:
                result = aclose_shared()
                if asyncio.iscoroutine(result):
                    await result
    except Exception:  # noqa: BLE001
        LOG.exception("provider httpx shutdown failed")
    # 5) Close the analytical DuckDB pool so the file lock releases cleanly.
    try:
        analytical_mod = _safe_import("showme.analytical")
        if analytical_mod is not None:
            close_fn = getattr(analytical_mod, "close", None)
            if close_fn is not None:
                close_fn()
    except Exception:  # noqa: BLE001
        LOG.exception("analytical pool shutdown failed")


def build_app(engine_root: Path | None) -> FastAPI:
    """Construct and wire the FastAPI app served by the showMe sidecar.

    ``engine_root`` is the location of the bundled function engine; passing
    ``None`` boots a stripped-down app suitable for tests (engine guards
    fail fast with HTTP 503 instead of crashing on missing imports).

    Reads:
        * ``SHOWME_AUTH_TOKEN``  — when set, every ``/api/*`` request
          (except ``/api/health`` and ``/api/x/health``) must include the
          matching ``X-ShowMe-Token`` header.
        * ``SHOWME_MAX_BODY_BYTES`` — body-size middleware ceiling
          (default 256 KB, per SEC-05).

    Per ARCH-07 / PY-LINT-03 (R3A): route handlers live in
    ``showme.server_routes`` (one file per family). This factory is now
    intentionally thin: middleware setup, shared singletons, then a
    single ``register_routes`` call wires the family routers onto the app.
    """
    from showme.server_routes import AppDeps, register_routes

    # Register every provider adapter (SEC EDGAR, FRED, TreasuryDirect, OpenFIGI,
    # Binance, yfinance, GDELT, RSS) with the global adapter REGISTRY. Adapter
    # constructors are network-free so this is safe to call before lifespan
    # startup. Importing the module triggers register_all_adapters() once.
    try:
        from showme.providers import seed_register  # noqa: F401
    except Exception as exc:  # noqa: BLE001 — non-fatal; log + continue
        LOG.warning("provider adapter registration skipped: %s", exc)

    # Per R4B: deps (boot_state, stream_hub provider) must be constructed
    # BEFORE FastAPI(lifespan=...) so the lifespan closure captures the
    # exact same singletons used by routes.
    boot_state: dict[str, Any] = {
        "engine_root": str(engine_root) if engine_root else None,
        "engine_attached": engine_root is not None,
    }
    get_stream_hub = _make_stream_hub_provider()
    deps = AppDeps(boot_state=boot_state, get_stream_hub=get_stream_hub)

    # PERF-09: kick off the function-index build BEFORE uvicorn accepts
    # requests. The lifespan-scheduled task (a few hundred ms later) would
    # race the first request and pay the 56s walk twice; this thread starts
    # immediately and the per-route caller blocks on _FUNCTION_INDEX_BUILD_LOCK
    # instead of re-walking.
    if boot_state["engine_attached"]:
        _kickoff_function_index_warmup()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Startup: prime function-factory in the background so the boot
        # path doesn't block on engine warmup.
        if boot_state.get("engine_attached"):
            async def _warm() -> None:
                try:
                    await asyncio.wait_for(_warm_showme_function_factory(), timeout=90)
                    boot_state["function_factory_warmed"] = True
                    boot_state.pop("function_factory_warm_error", None)
                except Exception as exc:  # noqa: BLE001
                    if not boot_state.get("function_factory_warmed"):
                        boot_state["function_factory_warmed"] = False
                        boot_state["function_factory_warm_error"] = str(exc) or type(exc).__name__
                    LOG.warning("function factory warmup failed: %r", exc)

            asyncio.create_task(_warm())

            # QA-fix: prime the function-index cache off-thread so the first
            # /api/function-index call doesn't block on engine warmup (Welcome
            # gauge "Loading…" hang). Non-fatal — handler will rebuild if this
            # task fails.
            async def _warm_function_index() -> None:
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(_load_function_index),
                        timeout=90,
                    )
                    boot_state["function_index_warmed"] = True
                    boot_state.pop("function_index_warm_error", None)
                except Exception as exc:  # noqa: BLE001
                    boot_state["function_index_warmed"] = False
                    boot_state["function_index_warm_error"] = str(exc) or type(exc).__name__
                    LOG.warning("function-index warmup failed: %r", exc)

            asyncio.create_task(_warm_function_index())

        # QA-fix: prime XAnalyzer.instance() so the first /api/x/health or
        # /api/x/symbol_chip call doesn't pay the ~2s RoBERTa cold-start cost
        # on the request thread (XSEN cold-start hang). The instance method
        # just returns a singleton; no model is loaded until analyze_topic
        # runs, but priming the singleton lets the worker thread page in
        # adjacent imports (transformers, torch) eagerly.
        async def _warm_x_analyzer() -> None:
            try:
                from showme.x_analysis import XAnalyzer

                await asyncio.wait_for(
                    asyncio.to_thread(XAnalyzer.instance),
                    timeout=60,
                )
                boot_state["x_analyzer_warmed"] = True
                boot_state.pop("x_analyzer_warm_error", None)
            except Exception as exc:  # noqa: BLE001
                boot_state["x_analyzer_warmed"] = False
                boot_state["x_analyzer_warm_error"] = str(exc) or type(exc).__name__
                LOG.warning("x_analyzer warmup failed: %r", exc)

        asyncio.create_task(_warm_x_analyzer())

        # FinBERT warmup — mirror the XAnalyzer pattern. The first call
        # cold-loads ProsusAI/finbert (~300 MB, ~3s on M-series), which
        # would otherwise block the first /api/fn/TOP request thread. We
        # detach it (no `await`) so the rest of lifespan keeps moving, and
        # we treat any failure as non-fatal — the news handlers degrade to
        # neutral-stamped sentiment if FinBERT can't load.
        async def _warm_finbert() -> None:
            try:
                from showme.finbert_analyzer import FinBertAnalyzer

                await asyncio.wait_for(
                    asyncio.to_thread(FinBertAnalyzer.instance),
                    timeout=90,
                )
                boot_state["finbert_warmed"] = True
                boot_state.pop("finbert_warm_error", None)
            except Exception as exc:  # noqa: BLE001
                boot_state["finbert_warmed"] = False
                boot_state["finbert_warm_error"] = str(exc) or type(exc).__name__
                LOG.warning("finbert warmup failed (handlers will stamp neutral): %r", exc)

        asyncio.create_task(_warm_finbert())

        # Whisper large-v3 warmup — mirrors the FinBERT pattern. Cold load
        # is heavy (~3 GB weights, multi-minute first download outside the
        # .app bundle). Fire-and-forget so the rest of lifespan keeps
        # moving; TRAN/TRQA/TSAR check ``WhisperAnalyzer.is_available()``
        # before relying on the singleton and surface a "warming, retry
        # in 30s" warning until this task completes. Load failures are
        # latched permanently in the singleton — the legacy transcription
        # service tiers continue to work in that case.
        async def _warm_whisper() -> None:
            try:
                from showme.whisper_analyzer import WhisperAnalyzer

                # The instance() call is the actual load; wrapping in
                # to_thread keeps the event loop free during the
                # transformers init + first weight materialisation.
                analyzer = await asyncio.wait_for(
                    asyncio.to_thread(WhisperAnalyzer.instance),
                    timeout=600,  # large-v3 first-download budget
                )
                if analyzer is None:
                    err = WhisperAnalyzer.load_error() or "unknown"
                    boot_state["whisper_warmed"] = False
                    boot_state["whisper_warm_error"] = err
                    LOG.warning("whisper warmup did not produce a singleton "
                                "(load_failed latch is on): %s", err)
                else:
                    boot_state["whisper_warmed"] = True
                    boot_state.pop("whisper_warm_error", None)
            except Exception as exc:  # noqa: BLE001
                boot_state["whisper_warmed"] = False
                boot_state["whisper_warm_error"] = str(exc) or type(exc).__name__
                LOG.warning("whisper warmup failed (TRAN/TRQA/TSAR will fall "
                            "back to the legacy tiered service): %r", exc)

        asyncio.create_task(_warm_whisper())
        # Sub-system D: spawn one asyncio.Task per enabled bot. Replay
        # happens here (inside the running loop) so the bots can actually
        # schedule themselves — build_app() runs synchronously and has no
        # loop available for asyncio.create_task().
        try:
            from showme.bots.lifespan import startup as bot_startup
            await bot_startup()
        except Exception as exc:  # noqa: BLE001 — non-fatal; log + continue
            LOG.warning("bot runner startup skipped: %s", exc)
        try:
            yield
        finally:
            # Shutdown: cancel bot tasks first so they stop touching the
            # broker registry, then close any live hub, flush helpers,
            # close broker connections. Each wrapped so a single failure
            # can't poison the rest of the cleanup chain.
            try:
                from showme.bots.lifespan import shutdown as bot_shutdown
                await bot_shutdown()
            except Exception:  # noqa: BLE001
                LOG.exception("bot runner shutdown failed")
            await _shutdown_cleanup(get_stream_hub)

    app = FastAPI(
        title="showMe sidecar",
        version="0.0.1",
        description="Localhost backend driving the showMe Tauri shell.",
        lifespan=lifespan,
    )
    _install_middlewares(app)

    register_routes(app, deps=deps)
    _install_openapi_security_schemes(app)

    # Sub-system A boot replay: rehydrate broker registry from the
    # CredentialStore so /api/broker/* works after a restart.
    try:
        from showme.brokers import CredentialStore, replay_stored_credentials
        replay_stored_credentials(CredentialStore.fresh())
    except Exception as exc:  # noqa: BLE001 — non-fatal; log + continue
        LOG.warning("credential replay skipped: %s", exc)
    return app



def _install_openapi_security_schemes(app: FastAPI) -> None:
    """Declare ``X-ShowMe-Token`` as a global apiKey security scheme.

    QA-fix: the generated ``/openapi.json`` previously reported
    ``securitySchemes: null`` even though every ``/api/*`` route is
    token-gated when ``SHOWME_AUTH_TOKEN`` is set. We now override
    ``FastAPI.openapi`` to:

    * Add a ``ShowMeToken`` apiKey-in-header scheme to
      ``components.securitySchemes``.
    * Apply that scheme as the default ``security`` requirement for every
      route EXCEPT the liveness probes (``/api/health``, ``/healthz``,
      ``/api/x/health``) and the docs/openapi endpoints themselves.

    The function caches the result on ``app.openapi_schema`` per FastAPI's
    convention so the cost only hits the first call.
    """
    from fastapi.openapi.utils import get_openapi

    exempt_paths = {
        "/api/health",
        "/api/x/health",
        "/healthz",
        "/docs",
        "/redoc",
        "/openapi.json",
    }

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {})
        components["securitySchemes"] = {
            "ShowMeToken": {
                "type": "apiKey",
                "in": "header",
                "name": "X-ShowMe-Token",
                "description": (
                    "Local sidecar auth token. Set via the SHOWME_AUTH_TOKEN env "
                    "var; the Tauri shell injects it as X-ShowMe-Token. Required "
                    "for every /api/* route except the exempt liveness probes."
                ),
            }
        }
        # Apply default security globally; per-path opt-out for exempt routes.
        schema["security"] = [{"ShowMeToken": []}]
        for path, item in schema.get("paths", {}).items():
            if path in exempt_paths:
                for method_name, op in item.items():
                    if isinstance(op, dict) and method_name in {
                        "get", "post", "put", "patch", "delete", "options", "head"
                    }:
                        op["security"] = []
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[assignment]


def function_warning_payload(code: str, params: dict[str, Any], exc: Exception) -> dict[str, Any]:
    return fallback_function_payload(code, params, str(exc) or type(exc).__name__, type(exc).__name__)


def _truthy_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


_REFERENCE_SOURCE_MARKERS = ("reference",)
_MODEL_SOURCE_MARKERS = ("_model",)
_OTHER_SYNTHETIC_MARKERS = (
    "template",
    "sample",
    "placeholder",
    "synthetic",
    "continuity",
    "_baseline",
    "_defaults",
    "auction_model",
    "auction_fallback",
    "tax_loss_model",
    "total_return_model",
    "briefing_model",
    "deterministic_tldr",
)


def _classify_source_state(source: Any) -> str:
    """Return one of: ``live``, ``synthetic``, ``reference``, ``model``.

    Used by ``enforce_live_or_label_synthetic`` so downstream UI can pill
    each row with its honest data state instead of being silently wiped.
    Order matters: ``reference`` is checked before ``model`` (so
    ``reference_*_model`` is treated as reference, the higher-fidelity
    label), and explicit synthetic markers win over a generic ``_model``
    suffix only for the strings already enumerated above.
    """
    text = str(source or "").lower().strip()
    if not text or text == "no_live_source":
        return "live" if not text else "synthetic"
    if any(marker in text for marker in _REFERENCE_SOURCE_MARKERS):
        return "reference"
    if any(marker in text for marker in _OTHER_SYNTHETIC_MARKERS):
        return "synthetic"
    if any(marker in text for marker in _MODEL_SOURCE_MARKERS):
        return "model"
    return "live"


def _summarize_source_states(sources: list[Any]) -> dict[str, int]:
    summary: dict[str, int] = {"live": 0, "synthetic": 0, "reference": 0, "model": 0}
    for source in sources:
        state = _classify_source_state(source)
        # Sources marked ``no_live_source`` with empty text return "live"
        # by accident; the explicit check above redirects truly-empty to
        # "live", but treat the literal sentinel as a non-counter.
        if str(source or "").strip().lower() == "no_live_source":
            continue
        summary[state] = summary.get(state, 0) + 1
    return summary


def enforce_live_or_label_synthetic(
    code: str, params: dict[str, Any], payload: Any
) -> Any:
    """Refactored sanitizer (was ``sanitize_function_payload``).

    Bug-fix 2026-05-24: the legacy implementation *dropped* every row
    whose only source matched ``reference_*`` / ``*_model`` / template
    markers, wiping WIRP / ECO / ECFC / GMM / CPF / OVDV / WCRS / PSC /
    every bond pane / BTMM warnings even when the engine had computed
    valid deterministic rows. The user-facing impact was a permanent
    ``provider_unavailable`` envelope with an empty Retry loop.

    New behavior:

    * Real provider failures (``metadata.exception_type``) still fall
      through to the existing ``fallback_function_payload`` envelope —
      these are honest broken-pipe cases, not deterministic computed
      data.
    * Otherwise rows are **kept**. Each source is classified into one of
      ``live`` / ``synthetic`` / ``reference`` / ``model`` and a single
      ``data_state`` label is stamped on the payload (worst-case wins:
      ``reference`` > ``model`` > ``synthetic`` > ``live``).
    * The ``warnings`` array is left intact — BTMM's ``live`` pill reads
      it to decide whether to flip to ``warn``.
    * A new top-level ``sanitizer_summary`` field reports counts so the
      UI can render an accurate per-pane pill.
    """
    if not isinstance(payload, dict):
        return payload

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []

    exception_type = metadata.get("exception_type")
    if exception_type:
        reason = str(exception_type)
        if warnings:
            reason = f"{reason}: {' | '.join(str(w) for w in warnings)}"
        return fallback_function_payload(
            code, params, reason, str(exception_type or "provider_unavailable")
        )

    # Classify sources and build a summary. The metadata "mode" / synthetic
    # flag still informs the dominant data_state but no longer wipes data.
    summary = _summarize_source_states(sources)
    metadata_mode = str(metadata.get("mode") or metadata.get("compatibility_mode") or "")
    metadata_synthetic = bool(metadata.get("synthetic")) or (
        bool(metadata_mode) and _classify_source_state(metadata_mode) != "live"
    )

    # Dominant data_state: reference > model > synthetic > live.
    if summary["reference"] > 0:
        data_state = "reference"
    elif summary["model"] > 0:
        data_state = "model"
    elif summary["synthetic"] > 0 or metadata_synthetic:
        data_state = "synthetic"
    else:
        data_state = "live"

    is_synthetic_like = data_state != "live"

    # Preserve warnings — BTMM and any other pane that reads warnings to
    # render a live/warn pill depends on them being there. We DO copy
    # warnings into provider_errors for the diagnostics drawer, but we no
    # longer clear payload["warnings"].
    if warnings:
        provider_errors = list(metadata.get("provider_errors") or [])
        provider_errors.extend(str(w) for w in warnings)
        metadata = {**metadata, "provider_errors": provider_errors}
        payload["metadata"] = metadata
        # NB: payload["warnings"] intentionally kept intact.

    if is_synthetic_like:
        provider_errors = list(metadata.get("provider_errors") or [])
        # Label the synthetic sources in provider_errors so the Raw
        # drawer still surfaces them — but do NOT wipe the data.
        labeled_sources = [str(s) for s in sources if _classify_source_state(s) != "live"]
        if labeled_sources:
            provider_errors.append(
                f"Non-live source labeled as data_state={data_state}: "
                + ", ".join(labeled_sources[:6])
            )
        metadata = {
            **metadata,
            "degraded": data_state in {"synthetic", "model"},
            "synthetic": data_state == "synthetic" or metadata_synthetic,
            "data_state": data_state,
            "original_sources": list(sources),
            "provider_errors": provider_errors,
        }
        payload["metadata"] = metadata

    # Always stamp top-level data_state + sanitizer_summary so the UI can
    # render the correct pill without scanning sources itself.
    payload["data_state"] = data_state
    payload["sanitizer_summary"] = summary

    return normalize_function_contract(code, params, payload)


# Deprecated: legacy name kept for backwards compatibility with import sites
# under ``server_routes/`` and the existing test suite. New callers should
# use ``enforce_live_or_label_synthetic``.
def sanitize_function_payload(code: str, params: dict[str, Any], payload: Any) -> Any:
    return enforce_live_or_label_synthetic(code, params, payload)


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
        canonical_symbol = _canonical_route_symbol(symbol, params.get("asset_class"))
        instrument = {
            "symbol": canonical_symbol,
            "asset_class": default_asset_class_name(canonical_symbol, params.get("asset_class")),
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
    symbol = _canonical_route_symbol(params.get("symbol") or params.get("topic") or "BTCUSDT", params.get("asset_class"))
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
    """Return the cached function index, building it on first call.

    PERF-09: holds _FUNCTION_INDEX_BUILD_LOCK across the heavy registration
    walk so concurrent first-callers (e.g. lifespan warmup vs the first
    /api/function-index request) pay the ~56s cost once, not twice.
    """
    global _FUNCTION_INDEX_CACHE
    with _FUNCTION_INDEX_LOCK:
        if _FUNCTION_INDEX_CACHE is not None:
            return list(_FUNCTION_INDEX_CACHE)
    with _FUNCTION_INDEX_BUILD_LOCK:
        # Double-check after acquiring the build lock — a sibling thread may
        # have populated the cache while we were waiting for the lock.
        with _FUNCTION_INDEX_LOCK:
            if _FUNCTION_INDEX_CACHE is not None:
                return list(_FUNCTION_INDEX_CACHE)
        return _build_function_index_locked()


def _build_function_index_locked() -> list[FunctionIndexEntry]:
    """Inner build path — assumes _FUNCTION_INDEX_BUILD_LOCK is held."""
    global _FUNCTION_INDEX_CACHE
    factory = _safe_import("showme.engine.services.function_factory")
    registry_mod = _safe_import("showme.engine.core.base_function")
    if factory is None or registry_mod is None:
        return []
    try:
        # Force register decorators without constructing adapter singletons on
        # the FastAPI thread. Adapter clients/stores are owned by the function
        # worker loop.
        factory._ensure_functions_registered()
    except Exception as exc:  # noqa: BLE001
        # Per ARCH-08 P0: registration failures must be fail-fast in strict
        # mode (default) so dropped functions are caught at boot rather than
        # silently absent from the catalog.
        if _env_truthy_default("SHOWME_STRICT_REGISTRATION", "1"):
            raise
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


def _kickoff_function_index_warmup() -> None:
    """PERF-09: warm the function index on a daemon thread.

    Called from build_app() so registration starts BEFORE uvicorn accepts
    requests — typically ~30s earlier than the lifespan-scheduled task.
    Idempotent: if the cache is already populated or a build is in flight,
    this returns quickly. The first /api/function-index request blocks on
    _FUNCTION_INDEX_BUILD_LOCK only if it arrives before this thread
    finishes, but it does NOT re-walk 112 modules.
    """
    def _run() -> None:
        try:
            _load_function_index()
        except Exception as exc:  # noqa: BLE001
            LOG.warning("function-index warmup thread failed: %r", exc)

    threading.Thread(
        target=_run,
        name="showme-function-index-warmup",
        daemon=True,
    ).start()


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
    # Per TEST-07 P1/P2: rotating file handler under <app_home>/logs +
    # millisecond timestamp + optional JSON-line format via $SHOWME_LOG_JSON.
    from showme.logging_setup import configure_logging, install_crash_hook
    configure_logging(args.log_level)
    install_crash_hook()
    app_home = prepare_writable_cwd() or ensure_app_home_env()
    if app_home:
        LOG.info("Using app home at %s", app_home)
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
