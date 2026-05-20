"""Utility helper functions for the trading bot.

Per PY-LINT-02 cleanup, the unused ``timestamp_now``, ``round_down``,
``safe_float`` and ``format_price`` helpers were dropped — none had any
remaining callers.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any


def datetime_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def iso_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime_now().isoformat()


def pct_change(old_val: float, new_val: float) -> float:
    """Return the fractional change ``(new - old) / |old|`` (0.0 when ``old == 0``)."""
    if old_val == 0:
        return 0.0
    return (new_val - old_val) / abs(old_val)


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp ``value`` to the inclusive ``[min_val, max_val]`` interval."""
    return max(min_val, min(max_val, value))


def retry_with_backoff(
    func,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
) -> Any:
    """Execute ``func`` with exponential backoff up to ``max_retries`` attempts.

    Re-raises the final exception if all attempts fail.
    """
    last_exception: Exception | None = None
    for attempt in range(max_retries):
        try:
            return func()
        except exceptions as e:
            last_exception = e
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                time.sleep(delay)
    raise last_exception  # type: ignore[misc]
