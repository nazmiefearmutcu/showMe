"""Provider-response cache backed by ``cache.provider_responses``.

The cache is keyed by ``(provider, op, input_hash)`` where ``input_hash`` is a
SHA-1 of the JSON-canonical input. Payloads are arbitrary Python objects
serialized via ``pickle`` (per the spec) but every read/write goes through
the ``dumps``/``loads`` helpers so the wire format can be swapped to msgpack
without churning call sites.

SECURITY NOTE on pickle: this cache is strictly an in-process write-then-read
store for *our own* provider responses (TTL-bounded, on the local DuckDB file
that only the user's process can open). It must NOT be used as an interop
format with anything we don't fully control — pickle deserialization is
arbitrary-code execution if a hostile blob ever lands in the table.

TTL is enforced at read time — expired rows return ``None`` and are eligible
for sweep via :func:`evict_expired`. ``ttl_seconds=None`` means "never expire".
"""
from __future__ import annotations

import hashlib
import json
import pickle  # noqa: S403 - local-only cache of our own writes; see module docstring.
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .duck import connection


def dumps(obj: Any) -> bytes:
    """Serialize an arbitrary Python object for cache storage."""
    return pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)


def loads(blob: bytes) -> Any:
    """Inverse of :func:`dumps`. Only call on bytes this module produced."""
    return pickle.loads(blob)  # noqa: S301 - see module docstring.


def cache_key(provider: str, op: str, **kwargs: Any) -> str:
    """Stable SHA-1 of the canonical JSON of ``kwargs``.

    Returns just the hash hex (40 chars). ``provider`` and ``op`` are NOT
    folded into the hash because they live in their own primary-key columns.
    """
    # ``sort_keys=True`` + ``default=str`` makes the hash deterministic across
    # dict-iteration order and tolerant of common non-JSON types (datetime,
    # Decimal, UUID, ...).
    canonical = json.dumps(kwargs, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def write_cache(
    provider: str,
    op: str,
    input_hash: str,
    payload: bytes,
    mode: str,
    ttl_seconds: Optional[int],
    latency_ms: Optional[int],
) -> None:
    """Upsert a row into the cache table.

    ``payload`` is taken as opaque bytes — callers should run it through
    :func:`dumps` first if they have a Python object.
    """
    now = _utcnow()
    expires_at = now + timedelta(seconds=ttl_seconds) if ttl_seconds else None
    con = connection()
    # DuckDB lacks "ON CONFLICT DO UPDATE" parity with PG; use delete+insert
    # within an implicit transaction so concurrent writers don't double-insert.
    con.execute(
        "DELETE FROM cache.provider_responses "
        "WHERE provider = ? AND op = ? AND input_hash = ?",
        [provider, op, input_hash],
    )
    con.execute(
        "INSERT INTO cache.provider_responses "
        "(provider, op, input_hash, payload, mode, created_at, expires_at, latency_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [provider, op, input_hash, payload, mode, now, expires_at, latency_ms],
    )


def read_cache(
    provider: str,
    op: str,
    input_hash: str,
) -> Optional[tuple[bytes, str, Optional[int]]]:
    """Return ``(payload, mode, latency_ms)`` if the row is present and fresh.

    Returns ``None`` if the row is absent OR expired. Expired rows are
    *not* deleted on read (so the eviction sweep stays predictable for
    metrics); use :func:`evict_expired` to actually remove them.
    """
    con = connection()
    row = con.execute(
        "SELECT payload, mode, latency_ms, expires_at "
        "FROM cache.provider_responses "
        "WHERE provider = ? AND op = ? AND input_hash = ?",
        [provider, op, input_hash],
    ).fetchone()
    if row is None:
        return None
    payload, mode, latency_ms, expires_at = row
    if expires_at is not None and expires_at <= _utcnow():
        return None
    return (bytes(payload), mode, latency_ms)


def evict_expired() -> int:
    """Delete every row whose ``expires_at`` is in the past, return count."""
    con = connection()
    # DuckDB DELETE returns affected rows via ``.fetchone()`` only when we
    # use ``RETURNING`` — easiest portable shape is count→delete.
    count_row = con.execute(
        "SELECT COUNT(*) FROM cache.provider_responses "
        "WHERE expires_at IS NOT NULL AND expires_at <= ?",
        [_utcnow()],
    ).fetchone()
    deleted = int(count_row[0]) if count_row else 0
    if deleted:
        con.execute(
            "DELETE FROM cache.provider_responses "
            "WHERE expires_at IS NOT NULL AND expires_at <= ?",
            [_utcnow()],
        )
    return deleted


__all__ = [
    "dumps",
    "loads",
    "cache_key",
    "write_cache",
    "read_cache",
    "evict_expired",
]
