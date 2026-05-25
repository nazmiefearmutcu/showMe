"""Process-wide registry for FunctionManifest entries.

Seed modules under ``manifest.seeds.*`` register themselves at import
time via the ``@manifest(...)`` decorator (or directly via
``REGISTRY.register(...)``). The FastAPI router and tests then read
through ``REGISTRY``.
"""
from __future__ import annotations

from typing import Callable

from .spec import FunctionManifest


class ManifestRegistry:
    """Insertion-ordered, code-keyed registry. Duplicate codes raise."""

    def __init__(self) -> None:
        self._by_code: dict[str, FunctionManifest] = {}

    def register(self, manifest: FunctionManifest) -> FunctionManifest:
        """Register ``manifest``. Raises ``ValueError`` on duplicate code."""
        code = manifest.code
        if code in self._by_code:
            raise ValueError(f"manifest already registered for code={code!r}")
        self._by_code[code] = manifest
        return manifest

    def get(self, code: str) -> FunctionManifest:
        """Return the manifest for ``code``. Raises ``KeyError`` if missing."""
        try:
            return self._by_code[code]
        except KeyError as exc:
            raise KeyError(f"no manifest registered for code={code!r}") from exc

    def all(self) -> list[FunctionManifest]:
        """Return every registered manifest in registration order."""
        return list(self._by_code.values())

    def codes(self) -> list[str]:
        """Return every registered code in registration order."""
        return list(self._by_code.keys())

    def clear(self) -> None:
        """Drop every registered manifest. Tests use this to isolate state."""
        self._by_code.clear()

    def __contains__(self, code: object) -> bool:
        return isinstance(code, str) and code in self._by_code

    def __len__(self) -> int:
        return len(self._by_code)


# Module-level singleton — seed modules import and use this.
REGISTRY = ManifestRegistry()


def manifest(*, registry: ManifestRegistry | None = None) -> Callable[
    [Callable[[], FunctionManifest]], FunctionManifest
]:
    """Decorator helper. Wrap a zero-arg factory returning a manifest.

    Usage::

        @manifest()
        def gp() -> FunctionManifest:
            return FunctionManifest(code="GP", ...)

    The decorator calls the factory once at import time, registers the
    returned manifest, and replaces the symbol with the manifest itself
    (so ``from .seeds._example_gp import gp`` yields the manifest).
    """
    target = registry if registry is not None else REGISTRY

    def _wrap(factory: Callable[[], FunctionManifest]) -> FunctionManifest:
        built = factory()
        if not isinstance(built, FunctionManifest):
            raise TypeError(
                f"@manifest factory {factory.__name__!r} returned "
                f"{type(built).__name__}, expected FunctionManifest",
            )
        target.register(built)
        return built

    return _wrap


__all__ = ["ManifestRegistry", "REGISTRY", "manifest"]
