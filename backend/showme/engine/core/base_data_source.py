"""BaseDataSource ABC — Strategy/Adapter pattern for every external feed.

Every adapter (yfinance, FRED, ECB, Binance, GDELT, etc.) inherits this
interface. The downstream code (functions, agents) holds a ``DataRouter``
of these and never sees vendor specifics.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Iterable

from showme.engine.core.instrument import Instrument


class DataKind(str, Enum):
    """What kind of payload a request asks for."""
    QUOTE = "QUOTE"
    OHLCV = "OHLCV"
    ORDERBOOK = "ORDERBOOK"
    TRADES = "TRADES"
    REFDATA = "REFDATA"
    FUNDAMENTALS = "FUNDAMENTALS"
    NEWS = "NEWS"
    ECON_SERIES = "ECON_SERIES"
    OPTIONS_CHAIN = "OPTIONS_CHAIN"
    HOLDINGS = "HOLDINGS"
    EVENTS = "EVENTS"
    SOCIAL = "SOCIAL"
    SATELLITE = "SATELLITE"
    WEATHER = "WEATHER"
    OTHER = "OTHER"


@dataclass
class DataRequest:
    """A typed request envelope handed to ``BaseDataSource.fetch``."""
    kind: DataKind
    instrument: Instrument | None = None
    symbols: list[str] = field(default_factory=list)
    start: datetime | None = None
    end: datetime | None = None
    interval: str | None = None      # "1m","1h","1d","1w","1mo"
    limit: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class DataSourceError(Exception):
    """Generic data-source failure."""


class RateLimitError(DataSourceError):
    """Raised when the upstream API rate limit is hit."""


class AllSourcesFailedError(DataSourceError):
    """Raised by ``DataRouter`` when every chained source failed."""


class BaseDataSource(ABC):
    """Abstract Strategy interface for any external data provider.

    Implementations MUST set ``name``, ``supported_kinds``, ``rate_limit_rps``.
    Optional ``stream()`` for WebSocket / SSE feeds.

    Health & rate-limit bookkeeping lives in this base class so children
    don't reimplement it.
    """
    name: str = "base"
    supported_kinds: tuple[DataKind, ...] = ()
    rate_limit_rps: float = 1.0      # requests-per-second budget
    timeout_seconds: float = 10.0
    requires_api_key: bool = False
    api_key_env: str | None = None   # env var that holds the key

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        if "rate_limit_rps" in self.config:
            self.rate_limit_rps = float(self.config["rate_limit_rps"])
        if "timeout_seconds" in self.config:
            self.timeout_seconds = float(self.config["timeout_seconds"])
        self._health = True
        self._last_failure: datetime | None = None
        self._call_log: deque[float] = deque(maxlen=int(max(self.rate_limit_rps, 1) * 60))
        self._consecutive_failures = 0

    # ─────────────────────── Public API ───────────────────────
    @abstractmethod
    async def fetch(self, request: DataRequest) -> Any:
        """Synchronous-style fetch. Returns a domain object: Quote, DataFrame,
        ReferenceData, OrderBook, list[Trade], list[News], etc.
        """
        ...

    async def stream(self, request: DataRequest) -> AsyncIterator[Any]:
        """Streaming endpoint. Default raises — sources that don't stream
        (REST-only) skip override.
        """
        raise NotImplementedError(f"{self.name} does not implement stream()")
        if False:  # pragma: no cover
            yield

    def supports(self, kind: DataKind) -> bool:
        return kind in self.supported_kinds

    @property
    def healthy(self) -> bool:
        return self._health

    @property
    def rate_limited(self) -> bool:
        """True if recent call density exceeds the rps budget."""
        now = time.monotonic()
        # purge entries older than 1 s
        while self._call_log and (now - self._call_log[0]) > 1.0:
            self._call_log.popleft()
        return len(self._call_log) >= self.rate_limit_rps

    # ─────────────────────── Hooks ───────────────────────
    def _record_call(self) -> None:
        self._call_log.append(time.monotonic())

    def _record_success(self) -> None:
        self._health = True
        self._consecutive_failures = 0

    def _record_failure(self, exc: Exception) -> None:
        self._consecutive_failures += 1
        self._last_failure = datetime.now(timezone.utc)
        if self._consecutive_failures >= 5:
            self._health = False  # circuit-breaker open

    async def throttle(self) -> None:
        """Block until the rate limit allows another call."""
        while self.rate_limited:
            await asyncio.sleep(1.0 / max(self.rate_limit_rps, 1))

    def __repr__(self) -> str:  # pragma: no cover
        kinds = ",".join(k.value for k in self.supported_kinds)
        return f"<{type(self).__name__} name={self.name} kinds={kinds} rps={self.rate_limit_rps}>"


class DataRouter:
    """Provider-chain router with automatic fallback (Spec EK D).

    Usage:
        router = DataRouter([primary, secondary, tertiary])
        result = await router.fetch(request)
    """

    def __init__(self, chain: Iterable[BaseDataSource]) -> None:
        self.chain: list[BaseDataSource] = list(chain)

    async def fetch(self, request: DataRequest) -> Any:
        last_err: Exception | None = None
        for src in self.chain:
            if not src.supports(request.kind):
                continue
            if not src.healthy:
                continue
            if src.rate_limited:
                continue
            try:
                src._record_call()
                timeout = float((request.extra or {}).get("timeout", src.timeout_seconds))
                result = await asyncio.wait_for(src.fetch(request), timeout=timeout)
                src._record_success()
                return result
            except (RateLimitError, asyncio.TimeoutError) as e:
                src._record_failure(e)
                last_err = e
                continue
            except Exception as e:
                src._record_failure(e)
                last_err = e
                continue
        raise AllSourcesFailedError(
            f"all {len(self.chain)} sources failed for {request.kind.value}"
        ) from last_err
