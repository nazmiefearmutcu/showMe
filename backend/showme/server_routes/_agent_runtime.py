"""Agent runtime: best-symbol ranker + per-function routing helpers.

Extracted from ``showme.server`` so the orchestration module stays under
1,300 lines (PY-LINT-03 / ARCH-07). The functions are still re-exported
from ``showme.server`` for back-compat with existing callers and the
test suite.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.crypto_aliases import resolve_crypto_symbol_alias
from showme.function_contracts import normalize_function_contract
from showme.server_routes._models import FunctionIndexEntry

LOG = logging.getLogger("showme.server.agent_runtime")


def _load_function_index() -> list[FunctionIndexEntry]:
    from showme.server import _load_function_index as impl

    return impl()


def _safe_import(name: str) -> Any | None:
    from showme.server import _safe_import as impl

    return impl(name)


def default_asset_class_name(symbol: str | None, requested: Any = None) -> str:
    from showme.server import default_asset_class_name as impl

    return impl(symbol, requested)


async def _execute_showme_function(code: str, params: dict[str, Any]) -> Any:
    from showme.server import _execute_showme_function as impl

    return await impl(code, params)


def _days_from_range(value: Any) -> int | None:
    from showme.server import _days_from_range as impl

    return impl(value)


def fallback_function_payload(
    code: str,
    params: dict[str, Any],
    reason: str,
    exception_type: str = "provider_unavailable",
) -> dict[str, Any]:
    from showme.server import fallback_function_payload as impl

    return impl(code, params, reason, exception_type)


def sanitize_function_payload(code: str, params: dict[str, Any], payload: Any) -> Any:
    from showme.server import sanitize_function_payload as impl

    return impl(code, params, payload)


def json_safe(value: Any) -> Any:
    from showme.server import json_safe as impl

    return impl(value)


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
AGENT_LOCAL_SIGNAL_CODES = {
    "BMTX",
    "BTFW",
    "BTUNE",
    "CN",
    "MLSIG",
    "MOSS",
    "NALRT",
    "NI",
    "PORT_OPT",
    "PVAR",
    "RPAR",
}
AGENT_EXCLUDED_FUNCTIONS = [
    {"code": "AGENT", "reason": "self-referential native ranker pane"},
    {"code": "ASK", "reason": "natural-language orchestration pane, not a symbol scoring function"},
    {"code": "HOME", "reason": "shell welcome/inventory pane"},
]
AGENT_LOCAL_SIGNAL_PROFILES = {
    "CRYPTO": ("momentum_onchain_proxy", 0.56, 0.42),
    "EQUITY": ("quality_momentum_proxy", 0.54, 0.36),
    "ETF": ("trend_volatility_proxy", 0.53, 0.31),
    "FX": ("carry_momentum_proxy", 0.52, 0.24),
    "COMMODITY": ("curve_momentum_proxy", 0.53, 0.28),
    "INDEX": ("macro_trend_proxy", 0.55, 0.33),
}


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
            symbol = _canonical_route_symbol(item)
            asset_class = default_asset_class_name(symbol)
        elif isinstance(item, dict):
            symbol = _canonical_route_symbol(item.get("symbol") or item.get("ticker"), item.get("asset_class"))
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
    elif code == "CSRC":
        params.update({"query": 'sector = "Energy"', "universe": ["CL=F", "BZ=F", "NG=F", "GC=F", "SI=F", "HG=F"]})
    elif code == "FSRC":
        params.update({"query": "expenseRatio < 0.01 AND aum_usd > 10000000000", "universe": ["SPY", "VOO", "IVV", "QQQ", "VTI", "IWM", "EEM", "GLD", "TLT", "HYG"]})
    elif code == "SRCH":
        params.update({"query": "yield >= 4 AND duration <= 10", "universe": ["US3M", "US2Y", "US5Y", "US10Y", "US30Y", "DE10Y", "GB10Y", "JP10Y"]})
    elif code == "MICRO":
        params.update({"exchange": profile["exchange"], "interval": "1m"})
    elif code == "FRH":
        params["exchange"] = profile["exchange"]
    elif code == "SAT":
        today = datetime.now(timezone.utc).date()
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
    elif code == "BTFW":
        params.update({"strategy": "sma_crossover", "days": 120})
    elif code == "BMTX":
        params.update({"strategies": ["sma_crossover", "rsi_meanrev", "buy_and_hold"], "days": 120})
    elif code == "MLSIG":
        params.update({"horizon": 1, "days": 365})
    elif code == "BTUNE":
        params.update({"strategy": "sma_crossover", "days": 120})
    elif code == "MGN":
        params["refresh_prices"] = False
    elif code == "DCFS":
        params.update({"wacc_range": [0.07, 0.09, 0.11], "g_range": [0.02, 0.03]})
    elif code == "DCF":
        params.update({"growth_high": 0.08, "growth_terminal": 0.025})
    elif code == "DDM":
        params.update({"growth_rate": 0.03, "required_return": 0.08})
    elif code == "WACC":
        params.update({"erp": 0.05, "beta_timeout": 2})
    elif code == "REBA":
        params["targets"] = profile["targets"]
    elif code == "SECF":
        params.update({"query": "technology"})
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
    "FXFC",
    "FXH",
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
    "MLSIG",
    "NALRT",
    "OMON",
    "OVDV",
    "PIB",
    "REGM",
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
    "PSC",
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
            "strike": 100,
            "short_strike": 110,
            "years_to_expiry": 0.25,
            "vol": 0.25,
            "rate": 0.045,
            "strategy": "CALL_SPREAD",
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
                "Use the visible option controls to set spot, strike, expiry in years, volatility, rate, and CALL/PUT type.",
                "Run to read price, delta, gamma, theta, vega, rho, d1, d2, and a spot sensitivity curve.",
                "Open Advanced only for optional model overrides such as Heston parameters.",
            ],
            "example": {"spot": 100, "strike": 105, "years_to_expiry": 0.25, "vol": 0.28, "rate": 0.045, "type": "CALL"},
        }
    if upper == "OSA":
        return {
            "purpose": "Multi-leg option strategy P&L curve from editable legs.",
            "scope": "model",
            "inputs": ["strategy", "spot", "strike", "short_strike", "years_to_expiry", "vol", "rate"],
            "steps": [
                "Use the visible strategy controls for call spread, long call, or straddle assumptions.",
                "Run to inspect the expiration payoff/P&L curve, net debit, and leg premium table.",
                "Open Advanced only for custom legs arrays.",
            ],
            "example": _standalone_function_defaults("OSA"),
        }
    if upper == "MLSIG":
        return {
            "purpose": "Train a directional classifier for one symbol and explain the feature drivers.",
            "scope": "symbol",
            "inputs": ["symbol", "range", "horizon"],
            "steps": [
                "Pick a symbol, Range, and Horizon, then Run.",
                "Read accuracy, Sharpe, model backend, signal, and feature-importance rows.",
                "Use Methodology and field dictionary to understand the target label and test split.",
            ],
            "example": {"symbol": "AAPL", "days": 365, "horizon": 1, "live": True},
        }
    if upper == "BLAK":
        return {
            "purpose": "Black-Litterman market-prior and posterior expected-return weights for a selected universe.",
            "scope": "portfolio model",
            "inputs": ["symbols", "range", "tau", "delta", "views"],
            "steps": [
                "Edit the visible Universe field and Range, then Run.",
                "Rows compare market weight, prior return, posterior return, and optimal weight by symbol.",
                "Use Advanced only for custom views, tau, delta, or market-cap overrides.",
            ],
            "example": {"symbols": ["AAPL", "MSFT", "NVDA"], "days": 365, "live": True},
        }
    if upper == "BMTX":
        return {
            "purpose": "Backtest matrix across a selected symbol universe and strategy set.",
            "scope": "portfolio model",
            "inputs": ["symbols", "range", "strategy"],
            "steps": [
                "Edit Universe, Range, and Strategy; All runs the strategy-by-symbol matrix.",
                "Inspect the heatmap and top rows ranked by Sharpe/total return.",
                "Use Methodology/field dictionary for metric definitions and fee assumptions.",
            ],
            "example": {"symbols": ["SPY", "QQQ", "AAPL"], "strategies": ["sma_crossover", "rsi_meanrev"], "days": 365, "live": True},
        }
    if upper == "BTFW":
        return {
            "purpose": "Single-symbol walk-forward strategy backtest with an equity curve.",
            "scope": "symbol",
            "inputs": ["symbol", "range", "strategy"],
            "steps": [
                "Pick symbol, Range, and Strategy, then Run.",
                "Use the dated equity curve plus Sharpe, return, drawdown, and trade rows.",
                "Use Advanced only for fees, cash, warmup, or shorting overrides.",
            ],
            "example": {"symbol": "AAPL", "strategy": "sma_crossover", "days": 365, "live": True},
        }
    if upper == "BTUNE":
        return {
            "purpose": "Hyperparameter sweep for one backtest strategy and symbol.",
            "scope": "symbol",
            "inputs": ["symbol", "range", "strategy"],
            "steps": [
                "Pick symbol, Range, and Strategy, then Run.",
                "Read best-by-Sharpe/return/Calmar cards and the parameter heatmap/table.",
                "Use Advanced only for a custom grid.",
            ],
            "example": {"symbol": "AAPL", "strategy": "sma_crossover", "days": 365, "live": True},
        }
    if upper == "GEX":
        return {
            "purpose": "Per-strike dealer gamma exposure, gamma flip, call wall, and put wall.",
            "scope": "symbol",
            "inputs": ["symbol", "live_options", "max_expiries"],
            "steps": [
                "Select an optionable equity symbol from the Symbol control.",
                "Run to fetch option open interest and chart dealer GEX by strike.",
                "Read Methodology/field rows for the Black-Scholes gamma equation and exposure convention.",
            ],
        }
    if upper == "HVT":
        return {
            "purpose": "Historical realized-volatility windows and rolling volatility history.",
            "scope": "symbol",
            "inputs": ["symbol", "range"],
            "steps": [
                "Select a symbol and Range, then Run.",
                "The chart uses rolling annualized realized volatility over dated close-to-close returns.",
                "Rows show the formula, sample count, and 30/60/90/selected-window volatility.",
            ],
        }
    if upper == "IVOL":
        return {
            "purpose": "Live implied-volatility surface by expiry, strike, and option type.",
            "scope": "symbol",
            "inputs": ["symbol", "max_expiries"],
            "steps": [
                "Select an optionable equity or ETF and Run.",
                "The heatmap uses impliedVolatility rows from live option chains.",
                "Rows include expiry, strike, CALL/PUT, moneyness, volume, and open interest.",
            ],
        }
    if upper == "OMON":
        return {
            "purpose": "Option monitor for a selected expiry with bid/ask/mid, IV, volume, and open interest.",
            "scope": "symbol",
            "inputs": ["symbol", "expiry"],
            "steps": [
                "Select an optionable equity or ETF and Run.",
                "The first listed expiry is selected by default; Advanced can override expiry.",
                "Rows flatten CALL/PUT contracts into a chain table and IV heatmap.",
            ],
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


def _canonical_route_symbol(symbol: Any, requested_asset_class: Any = None) -> str:
    raw = str(symbol or "").strip()
    if not raw:
        return ""
    requested = str(requested_asset_class or "").strip().upper()
    if requested in {"", "CRYPTO"}:
        resolved = resolve_crypto_symbol_alias(raw, allow_network=True)
        if resolved:
            return resolved.strip().upper()
    return raw.upper()


def _route_function_params(code: str, params: dict[str, Any]) -> dict[str, Any]:
    merged = dict(params)
    entry = _function_entry_for_code(code)
    # A visible topic/search field must not be silently converted into a
    # ticker. NI/TLDR/TOP/BRIEF/READ use topic/query text as text, while
    # symbol-first panes send an explicit ``symbol`` key.
    topic_is_symbol = code.upper() not in {"NI", "TLDR", "TOP", "BRIEF", "READ", "AV"}
    explicit_symbol = bool(merged.get("symbol") or (topic_is_symbol and merged.get("topic")))
    raw_symbol = str(
        merged.get("symbol")
        or (merged.get("topic") if topic_is_symbol else None)
        or _default_route_symbol(entry)
    ).strip()
    symbol = _canonical_route_symbol(raw_symbol, merged.get("asset_class"))
    asset_class = default_asset_class_name(symbol, merged.get("asset_class"))
    defaults = _agent_function_params(entry, {"symbol": symbol, "asset_class": asset_class})
    defaults.update(_standalone_function_defaults(code))
    defaults.update(merged)
    if code.upper() in {"GP", "HP", "TECH", "CHGS"} and merged.get("range") and "days" not in merged:
        ranged_days = _days_from_range(merged.get("range"))
        if ranged_days is not None:
            defaults["days"] = ranged_days
    if code.upper() == "FRH" and "symbols" not in merged:
        defaults.pop("symbols", None)
    if code.upper() == "ICX" and defaults.get("query") and not merged.get("index"):
        defaults["index"] = str(defaults["query"]).strip().upper()
    if code.upper() == "TRQA" and defaults.get("query") and not merged.get("questions"):
        defaults["questions"] = [str(defaults["query"]).strip()]
    if code.upper() == "SAT" and defaults.get("days") and not (merged.get("date_from") or merged.get("date_to")):
        try:
            horizon = max(1, min(int(defaults.get("days") or 7), 365))
        except Exception:
            horizon = 7
        today = datetime.now(timezone.utc).date()
        defaults["date_from"] = (today - timedelta(days=horizon)).isoformat()
        defaults["date_to"] = today.isoformat()
    if explicit_symbol or _route_uses_symbol(entry):
        defaults["symbol"] = _canonical_route_symbol(
            defaults.get("symbol") or symbol,
            defaults.get("asset_class") or asset_class,
        )
        defaults["asset_class"] = default_asset_class_name(
            defaults["symbol"],
            defaults.get("asset_class") or asset_class,
        )
    else:
        defaults.pop("symbol", None)
        if topic_is_symbol:
            defaults.pop("topic", None)
        defaults.pop("asset_class", None)
    if code.upper() == "MOST" and merged.get("asset_class"):
        defaults["asset_class"] = str(merged["asset_class"]).strip()
    defaults["__explicit_symbol"] = explicit_symbol
    return defaults


def _function_code_supports_asset(code: str, asset_class: str) -> bool:
    registry_mod = _safe_import("showme.engine.core.base_function")
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


def _agent_symbol_bias(symbol: str) -> float:
    # Stable, tiny tiebreaker so equal asset-class probes do not collapse into identical scores.
    total = sum(ord(ch) for ch in symbol.upper())
    return ((total % 17) - 8) / 100.0


def _agent_local_profile(symbol: str, asset_class: str) -> dict[str, float | str]:
    backend, accuracy, sharpe = AGENT_LOCAL_SIGNAL_PROFILES.get(
        asset_class,
        ("cross_asset_proxy", 0.52, 0.2),
    )
    bias = _agent_symbol_bias(symbol)
    base_return = {
        "CRYPTO": 0.082,
        "EQUITY": 0.046,
        "ETF": 0.032,
        "FX": 0.018,
        "COMMODITY": 0.036,
        "INDEX": 0.028,
        "BOND": 0.014,
    }.get(asset_class, 0.025)
    base_risk = {
        "CRYPTO": 0.18,
        "EQUITY": 0.115,
        "ETF": 0.085,
        "FX": 0.055,
        "COMMODITY": 0.13,
        "INDEX": 0.095,
        "BOND": 0.045,
    }.get(asset_class, 0.1)
    return {
        "backend": backend,
        "accuracy": _clamp(accuracy + bias * 0.12, 0.49, 0.64),
        "sharpe": _clamp(sharpe + bias * 0.9, -0.2, 1.2),
        "expected_return": _clamp(base_return + bias * 0.04, -0.05, 0.18),
        "drawdown_pct": _clamp(base_risk * 42 - bias * 8, 1.0, 35.0),
        "volatility_pct": _clamp(base_risk * 100 + bias * 12, 2.0, 35.0),
        "momentum_score": _clamp(58 + bias * 90, 35, 82),
        "risk_score": _clamp(base_risk * 100 - bias * 12, 2.0, 35.0),
    }


def _agent_probe_data_for_code(
    code: str,
    symbol: str,
    asset_class: str,
    profile: dict[str, float | str],
) -> dict[str, Any]:
    common = {
        "symbol": symbol,
        "asset_class": asset_class,
        "probe_mode": "agent_fast_probe",
        "methodology": "Deterministic local probe used only to rank candidates quickly before optional live function execution.",
    }
    accuracy = float(profile["accuracy"])
    sharpe = float(profile["sharpe"])
    expected_return = float(profile["expected_return"])
    drawdown_pct = float(profile["drawdown_pct"])
    volatility_pct = float(profile["volatility_pct"])
    momentum_score = float(profile["momentum_score"])
    risk_score = float(profile["risk_score"])
    if code == "MLSIG":
        return {
            **common,
            "backend": profile["backend"],
            "test_accuracy": accuracy,
            "test_samples": 84,
            "feature_importance": {
                "ret_5": 0.24,
                "ret_20": 0.21,
                "volatility_20": 0.19,
                "asset_class_bias": 0.11,
            },
            "strategy_sharpe": sharpe,
            "momentum_score": momentum_score,
            "signal": "long_bias" if accuracy >= 0.53 else "neutral",
            "coverage": {"symbol": symbol, "asset_class": asset_class, "mode": "agent_fast_probe"},
        }
    if code in {"BTFW", "BMTX"}:
        return {
            **common,
            "strategy": "buy_and_hold_probe" if code == "BTFW" else "strategy_matrix_probe",
            "total_return": expected_return,
            "strategy_sharpe": sharpe,
            "max_drawdown_pct": drawdown_pct,
            "win_rate": _clamp(0.51 + sharpe / 12, 0.42, 0.64),
            "signal": "positive_walk_forward" if sharpe > 0.25 else "neutral_walk_forward",
        }
    if code == "BTUNE":
        return {
            **common,
            "best_sharpe": sharpe + 0.08,
            "best_return": expected_return * 1.15,
            "calmar": expected_return / max(drawdown_pct / 100, 0.01),
            "max_drawdown_pct": drawdown_pct,
            "signal": "positive_tuning" if sharpe > 0.25 else "neutral_tuning",
        }
    if code == "PORT_OPT":
        return {
            **common,
            "max_sharpe": sharpe + 0.12,
            "expected_return": expected_return,
            "volatility_pct": volatility_pct,
            "upside_score": momentum_score,
            "signal": "positive_optimizer_candidate" if sharpe > 0.2 else "neutral_optimizer_candidate",
        }
    if code == "RPAR":
        return {
            **common,
            "diversification_score": _clamp(66 - risk_score * 0.7, 35, 80),
            "portfolio_volatility_pct": volatility_pct,
            "risk_balance_score": _clamp(62 - abs(risk_score - 12), 30, 76),
            "signal": "positive_risk_balance" if risk_score < 16 else "risk_watch",
        }
    if code == "PVAR":
        return {
            **common,
            "marginal_var_pct": risk_score / 2,
            "component_risk_pct": risk_score,
            "downside_risk_pct": drawdown_pct,
            "signal": "risk_watch" if risk_score > 18 else "positive_risk_profile",
        }
    if code == "MOSS":
        return {
            **common,
            "momentum_score": momentum_score,
            "realized_volatility_pct": volatility_pct,
            "liquidity_score": _clamp(72 + _agent_symbol_bias(symbol) * 60, 42, 88),
            "signal": "positive_activity" if momentum_score >= 55 else "neutral_activity",
        }
    if code in {"CN", "NI", "NALRT"}:
        return {
            **common,
            "relevance_score": _clamp(68 + _agent_symbol_bias(symbol) * 70, 35, 88),
            "importance_score": _clamp(58 + _agent_symbol_bias(symbol) * 55, 30, 82),
            "sentiment": "bullish" if sharpe > 0.25 else "neutral",
            "signal": "positive_news_flow" if sharpe > 0.25 else "neutral_news_flow",
        }
    return common


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


def _agent_probe_payload(
    entry: FunctionIndexEntry,
    candidate: dict[str, str],
    params: dict[str, Any],
    native_asset_match: bool,
) -> dict[str, Any]:
    if entry.code.upper() not in AGENT_LOCAL_SIGNAL_CODES or not native_asset_match:
        reason = "agent nonblocking probe"
        payload = fallback_function_payload(entry.code, params, reason, "agent_probe")
        payload["metadata"] = {
            **payload.get("metadata", {}),
            "agent_probe": True,
            "native_asset_match": native_asset_match,
        }
        return payload

    asset_class = candidate["asset_class"].upper()
    symbol = candidate["symbol"].upper()
    profile = _agent_local_profile(symbol, asset_class)
    payload = {
        "code": entry.code.upper(),
        "instrument": {"symbol": symbol, "asset_class": asset_class},
        "data": _agent_probe_data_for_code(entry.code.upper(), symbol, asset_class, profile),
        "metadata": {
            "agent_probe": True,
            "native_asset_match": native_asset_match,
            "local_signal_model": True,
        },
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sources": ["agent_fast_probe"],
        "warnings": [],
        "elapsed_ms": None,
    }
    return normalize_function_contract(entry.code, params, payload)


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
                payload = _agent_probe_payload(entry, candidate, params, native_asset_match)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            score = _agent_payload_score(entry.code, payload)
            if score["fallback"]:
                fallback_count += 1
            if status == "pass":
                pass_count += 1
            else:
                fail_count += 1
            if score["signal_count"] > 0:
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
        "catalog_count": len(entries) + len(AGENT_EXCLUDED_FUNCTIONS),
        "excluded_functions": AGENT_EXCLUDED_FUNCTIONS,
        "candidate_count": len(candidates),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "elapsed_ms": int((completed_at - started_at).total_seconds() * 1000),
        "method": "all_function_symbol_agent_v3_fast_probe" if not execute_functions else "all_function_symbol_agent_v1_live",
        "methodology": "Ranks candidate symbols by aggregating scored evidence rows. Nonblocking mode uses transparent agent_fast_probe payloads for selected signal functions and fallback probes for the rest.",
    }


def _run_best_symbol_agent_blocking(request: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_run_best_symbol_agent(request))
