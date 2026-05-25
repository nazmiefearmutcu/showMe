"""showMe local analytical core.

Public surface of the analytical module — a DuckDB-backed persistence layer
and Polars-based fast tabular transforms. Used by the provider adapter
cache, the pane snapshot store, the audit log, and the research artifact
store.

Quick start
===========

>>> from showme.analytical import connection, write_cache, cache_key
>>> con = connection()
>>> key = cache_key("yfinance", "history", ticker="AAPL", interval="1d")
>>> # write_cache("yfinance", "history", key, payload=..., mode="LIVE", ...)
"""
from __future__ import annotations

from .audit import list_events, record_event
from .cache import (
    cache_key,
    dumps,
    evict_expired,
    loads,
    read_cache,
    write_cache,
)
from .duck import POOL, DuckPool, close, connection
from .frames import (
    correlation_matrix,
    join_asof,
    pct_change,
    rank_by,
    resample_ohlcv,
    rolling_mean,
    to_polars_from_arrow,
)
from .snapshots import get_snapshot, list_snapshots, save_snapshot

__all__ = [
    # duck
    "DuckPool",
    "POOL",
    "connection",
    "close",
    # cache
    "cache_key",
    "write_cache",
    "read_cache",
    "evict_expired",
    "dumps",
    "loads",
    # snapshots
    "save_snapshot",
    "get_snapshot",
    "list_snapshots",
    # audit
    "record_event",
    "list_events",
    # frames
    "to_polars_from_arrow",
    "resample_ohlcv",
    "join_asof",
    "rank_by",
    "pct_change",
    "rolling_mean",
    "correlation_matrix",
]
