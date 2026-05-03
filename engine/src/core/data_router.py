"""Data router — re-export of BaseDataSource.DataRouter for spec compliance.

Plan EK D references ``src/core/data_router.py``. Keeping the symbol there
even though the implementation lives in ``base_data_source.py``.
"""

from src.core.base_data_source import (
    DataRouter,
    AllSourcesFailedError,
    BaseDataSource,
    DataRequest,
    DataKind,
    RateLimitError,
)

__all__ = [
    "DataRouter",
    "AllSourcesFailedError",
    "BaseDataSource",
    "DataRequest",
    "DataKind",
    "RateLimitError",
]
