"""Async throttle / rate-limit decorator for adapters.

Thread-safe-ish (single event loop). Each ``@throttle(rps=1)`` wrapper
shares state per decorated callable. Intended for rate-friendly adapters.

For more sophisticated bucket strategies (token-bucket, leaky-bucket per
endpoint), wrap the adapter's HTTP client instead.
"""

from __future__ import annotations

import asyncio
import functools
import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


def throttle(rps: float) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator: ensure decorated coroutine is called at most ``rps`` times/sec."""
    if rps <= 0:
        raise ValueError("rps must be > 0")
    interval = 1.0 / rps

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        last_call: list[float] = [0.0]
        lock = asyncio.Lock()

        @functools.wraps(fn)
        async def wrapper(*args: object, **kwargs: object) -> T:
            async with lock:
                now = time.monotonic()
                wait = (last_call[0] + interval) - now
                if wait > 0:
                    await asyncio.sleep(wait)
                last_call[0] = time.monotonic()
            return await fn(*args, **kwargs)

        return wrapper

    return decorator


class TokenBucket:
    """Async token bucket — useful when an adapter has bursty needs.

    Example:
        bucket = TokenBucket(rate=5, capacity=10)
        await bucket.acquire()
    """

    def __init__(self, rate: float, capacity: int) -> None:
        self.rate = rate
        self.capacity = capacity
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                wait = (tokens - self._tokens) / self.rate
                await asyncio.sleep(wait)


class CircuitBreaker:
    """Open-circuit after N consecutive failures, half-open after cooldown."""

    def __init__(self, threshold: int = 5, cooldown: float = 30.0) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at >= self.cooldown:
            self.opened_at = None
            self.failures = 0
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()
