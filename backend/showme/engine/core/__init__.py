"""Core interfaces for the Bloomberg-class ShowMe expansion.

Public API:
    - BaseDataSource, BaseAssetClass, BaseFunction, BaseAgent (ABCs)
    - Instrument, AssetClass (universal instrument model)
    - Quote, Trade, OrderBook, OrderBookLevel (market data primitives)
    - ReferenceData (instrument-level static data)
    - FunctionResult (function output envelope)
"""

from showme.engine.core.base_data_source import (
    BaseDataSource,
    DataRequest,
    DataSourceError,
    RateLimitError,
    AllSourcesFailedError,
)
from showme.engine.core.base_asset_class import BaseAssetClass
from showme.engine.core.base_function import BaseFunction, FunctionResult, FunctionRegistry
from showme.engine.core.base_agent import BaseAgent, AgentResult, AgentTask
from showme.engine.core.instrument import Instrument, AssetClass
from showme.engine.core.quote import Quote, Trade, OrderBook, OrderBookLevel
from showme.engine.core.refdata import ReferenceData

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
