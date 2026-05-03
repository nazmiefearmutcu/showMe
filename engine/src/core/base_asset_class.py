"""BaseAssetClass ABC — per-asset-class behavior contract.

Each asset class (crypto, equity, bond, fx, commodity, ...) provides:
  - A registry of indicators applicable to it
  - A signal/consensus pipeline (or a stub if not signal-based)
  - A list of supported BaseFunction codes
  - Default data-source chain (primary, secondary, tertiary)

The existing ShowMe code becomes ``CryptoAssetClass`` — a thin adapter sitting
on top of the legacy modules without relocating their files.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable

from src.core.instrument import AssetClass, Instrument


class BaseAssetClass(ABC):
    """Per-asset-class facade over data, signal, function pipelines."""
    asset_class: AssetClass

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    @abstractmethod
    def supports_instrument(self, instrument: Instrument) -> bool: ...

    @abstractmethod
    def list_functions(self) -> list[str]:
        """List of BaseFunction codes that work for this asset class."""
        ...

    @abstractmethod
    def list_indicators(self) -> list[str]: ...

    @abstractmethod
    def default_data_source_chain(self, kind: str) -> list[str]:
        """Return ordered adapter ``name`` strings for a data kind."""
        ...

    def list_brokers(self) -> list[str]:
        """Brokers/exchanges that can route orders for this asset class."""
        return []

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AssetClass {self.asset_class.value}>"
