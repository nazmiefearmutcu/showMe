"""AdapterRegistry — keyed lookup + ordered fallback chains.

Adapters register themselves by ``name`` (a stable, lowercase key like
``"sec_edgar"``). Callers can ask for one by name or build a chain to try
several in priority order.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator

from .base import DataMode, ProviderAdapter

__all__ = ["AdapterRegistry", "REGISTRY", "chain"]


class AdapterRegistry:
    """In-memory mapping of ``name → adapter instance``."""

    def __init__(self) -> None:
        self._by_name: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> ProviderAdapter:
        """Register an adapter. Re-registering with the same name overwrites.

        Returns the adapter so callers can write
        ``adapter = REGISTRY.register(SecEdgarAdapter())``.
        """
        if not getattr(adapter, "name", None):
            raise ValueError(
                f"adapter of type {type(adapter).__name__} has empty name"
            )
        self._by_name[adapter.name] = adapter
        return adapter

    def get(self, name: str) -> ProviderAdapter | None:
        return self._by_name.get(name)

    def all(self) -> list[ProviderAdapter]:
        """Return a stable-ordered snapshot list."""
        return list(self._by_name.values())

    def names(self) -> list[str]:
        return list(self._by_name.keys())

    def clear(self) -> None:
        """Test helper — drop every registration. Production should not call."""
        self._by_name.clear()


# Module-level singleton. Adapters call ``REGISTRY.register(...)`` from
# their seed module; the rest of the app reads via ``REGISTRY.get(...)``.
REGISTRY = AdapterRegistry()


def chain(primary: str, fallbacks: Iterable[str]) -> Iterator[ProviderAdapter]:
    """Yield adapters by name in priority order, skipping NOT_CONFIGURED ones.

    Resolution rule: the primary is yielded even when its mode is
    ``NOT_CONFIGURED`` (so the caller can log the missing-key reason
    before falling back). Fallback adapters are skipped if they're
    ``NOT_CONFIGURED`` — there's no point trying them, they can't
    possibly succeed without configuration.
    """
    primary_adapter = REGISTRY.get(primary)
    if primary_adapter is not None:
        yield primary_adapter
    for name in fallbacks:
        adapter = REGISTRY.get(name)
        if adapter is None:
            continue
        if adapter.mode() == DataMode.NOT_CONFIGURED:
            continue
        yield adapter
