"""Core interfaces for the Bloomberg-class ShowMe expansion.

Public API:
    - BaseDataSource, BaseAssetClass, BaseFunction, BaseAgent (ABCs)
    - Instrument, AssetClass (universal instrument model)
    - Quote, Trade, OrderBook, OrderBookLevel (market data primitives)
    - ReferenceData (instrument-level static data)
    - FunctionResult (function output envelope)
"""

from src.core.base_data_source import (
    BaseDataSource,
    DataRequest,
    DataSourceError,
    RateLimitError,
    AllSourcesFailedError,
)
from src.core.base_asset_class import BaseAssetClass
from src.core.base_function import BaseFunction, FunctionResult, FunctionRegistry
from src.core.base_agent import BaseAgent, AgentResult, AgentTask
from src.core.instrument import Instrument, AssetClass
from src.core.quote import Quote, Trade, OrderBook, OrderBookLevel
from src.core.refdata import ReferenceData

__all__ = [
    "BaseDataSource",
    "DataRequest",
    "DataSourceError",
    "RateLimitError",
    "AllSourcesFailedError",
    "BaseAssetClass",
    "BaseFunction",
    "FunctionResult",
    "FunctionRegistry",
    "BaseAgent",
    "AgentResult",
    "AgentTask",
    "Instrument",
    "AssetClass",
    "Quote",
    "Trade",
    "OrderBook",
    "OrderBookLevel",
    "ReferenceData",
]
