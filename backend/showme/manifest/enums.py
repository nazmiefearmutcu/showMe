"""Enumerations for the FunctionManifest contract.

These enums are the canonical vocabulary shared across backend handlers,
frontend controls, and tests. Both the Python and TypeScript halves of
the contract are generated from the same schema spec — keep the string
values stable.
"""
from __future__ import annotations

from enum import Enum


class Category(str, Enum):
    """High-level functional grouping for a manifest entry."""

    PORTFOLIO = "portfolio"
    TRADE_EXECUTION = "trade_execution"
    API_DEV = "api_dev"
    BONDS_RATES = "bonds_rates"
    CHARTS_TECH = "charts_tech"
    COMMS_PEOPLE = "comms_people"
    COMMODITIES = "commodities"
    DERIVATIVES = "derivatives"
    EQUITIES = "equities"
    FX = "fx"
    MACRO = "macro"
    NEWS_INTEL = "news_intel"
    SCREENING = "screening"
    MISC = "misc"


class AssetClass(str, Enum):
    """Asset classes a function may operate on."""

    EQUITY = "equity"
    ETF = "etf"
    CRYPTO = "crypto"
    FX = "fx"
    COMMODITY = "commodity"
    BOND = "bond"
    RATE = "rate"
    INDEX = "index"
    OPTION = "option"
    FUTURE = "future"


class DataMode(str, Enum):
    """Provider data mode — what shape of data a chain actually returned."""

    LIVE_OFFICIAL = "live_official"
    LIVE_EXCHANGE = "live_exchange"
    DELAYED_REFERENCE = "delayed_reference"
    MODELED = "modeled"
    CACHED_SNAPSHOT = "cached_snapshot"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    NOT_CONFIGURED = "not_configured"


class ControlKind(str, Enum):
    """Frontend control widget kinds for `InputSpec`."""

    SYMBOL_PICKER = "symbol_picker"
    BENCHMARK_PICKER = "benchmark_picker"
    DATE_RANGE = "date_range"
    HORIZON = "horizon"
    SCENARIO = "scenario"
    PROVIDER_MODE = "provider_mode"
    NUMBER = "number"
    TEXT = "text"
    SELECT = "select"
    MULTISELECT = "multiselect"
    BOOLEAN = "boolean"
    MODEL_ASSUMPTION = "model_assumption"
    CONSTRAINT_SET = "constraint_set"


class ChartKind(str, Enum):
    """Chart rendering grammar — drives the frontend chart factory."""

    TIME_SERIES_LINE = "time_series_line"
    TIME_SERIES_CANDLES = "time_series_candles"
    OHLCV = "ohlcv"
    HEATMAP = "heatmap"
    SURFACE = "surface"
    FRONTIER = "frontier"
    TENOR_CURVE = "tenor_curve"
    DEPTH_LADDER = "depth_ladder"
    PAYOFF = "payoff"
    RISK_CONTRIBUTION_BAR = "risk_contribution_bar"
    ATTRIBUTION_BAR = "attribution_bar"
    BAR_LADDER = "bar_ladder"
    SCATTER = "scatter"
    DISTRIBUTION = "distribution"


__all__ = [
    "Category",
    "AssetClass",
    "DataMode",
    "ControlKind",
    "ChartKind",
]
