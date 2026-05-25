"""DataMode enum + ProviderAdapter ABC + AdapterError exception.

This module defines the contract every provider adapter in
``showme.providers`` must satisfy. The interface is deliberately small:
adapters expose a set of named capabilities, report their authentication +
quota + latency state, and resolve to a canonical ``DataMode`` so the rest
of the app can decide what badge / disclaimer to render.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar, Literal

__all__ = ["DataMode", "ProviderAdapter", "AdapterError"]


class DataMode(str, Enum):
    """Canonical effective-data-source state for any adapter.

    Values are strings so the enum serialises straight through to JSON
    without a custom encoder. The exact string spellings are part of the
    public contract — see ``test_data_mode_values_stable``.
    """

    LIVE_OFFICIAL = "live_official"
    LIVE_EXCHANGE = "live_exchange"
    DELAYED_REFERENCE = "delayed_reference"
    MODELED = "modeled"
    CACHED_SNAPSHOT = "cached_snapshot"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    NOT_CONFIGURED = "not_configured"


class AdapterError(RuntimeError):
    """Raised by adapters when an upstream call fails in a structured way.

    Adapters MUST set ``self._last_error`` to the underlying exception
    (this one or the original) so ``mode()`` can resolve to
    ``provider_unavailable`` on subsequent reads.
    """


_AuthState = Literal["ok", "missing_key", "invalid_key", "not_required"]


class ProviderAdapter(ABC):
    """Abstract base for every upstream-data adapter."""

    name: ClassVar[str]
    nominal_mode: ClassVar[DataMode] = DataMode.LIVE_OFFICIAL

    def __init__(self) -> None:
        # State carried across calls. Subclasses MUST update these from
        # inside their request methods (success -> _last_latency_ms set,
        # _last_error cleared; failure -> _last_error set).
        self._last_latency_ms: int | None = None
        self._last_error: Exception | None = None

    # ---- contract -----------------------------------------------------

    @abstractmethod
    def capabilities(self) -> set[str]:
        """Named capabilities this adapter exposes.

        e.g. ``{"company_submissions", "xbrl_facts"}`` for SEC EDGAR.
        """

    def auth_state(self) -> _AuthState:
        """Default 'not_required'; override if adapter needs credentials."""
        return "not_required"

    def quota_state(self) -> dict[str, Any]:
        """Best-effort remaining requests / reset window. Empty when unknown."""
        return {}

    def last_latency_ms(self) -> int | None:
        """Latency of most recent successful upstream call, ms."""
        return self._last_latency_ms

    def mode(self) -> DataMode:
        """Resolve the current effective DataMode.

        Resolution order:
          1. If ``auth_state()`` indicates a credential problem
             (``missing_key`` / ``invalid_key``) → ``NOT_CONFIGURED``.
          2. Else if the most recent call recorded an error
             (``self._last_error is not None``) → ``PROVIDER_UNAVAILABLE``.
          3. Else the adapter's nominal mode (defaults to ``LIVE_OFFICIAL``).
        """
        auth = self.auth_state()
        if auth in ("missing_key", "invalid_key"):
            return DataMode.NOT_CONFIGURED
        if self._last_error is not None:
            return DataMode.PROVIDER_UNAVAILABLE
        return self.nominal_mode

    # ---- helpers for subclasses --------------------------------------

    def _record_success(self, latency_ms: int) -> None:
        """Record a successful upstream call. Clears any prior error."""
        self._last_latency_ms = int(latency_ms)
        self._last_error = None

    def _record_failure(self, exc: Exception) -> None:
        """Record a failed upstream call. ``mode()`` will flip to UNAVAILABLE."""
        self._last_error = exc
