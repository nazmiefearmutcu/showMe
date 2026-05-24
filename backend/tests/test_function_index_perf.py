"""PERF-09: function-index cold-start must serialize concurrent first calls.

Regression tests for the build-lock + warmup kickoff that prevents two
concurrent first-callers (lifespan warmup vs first /api/function-index
request) from each paying the full 56s 112-module walk.
"""
from __future__ import annotations

import threading
import time

import pytest

from showme import server


@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset the module-level cache between tests."""
    server._FUNCTION_INDEX_CACHE = None
    yield
    server._FUNCTION_INDEX_CACHE = None


def test_concurrent_first_calls_serialize_on_build_lock(monkeypatch):
    """Two threads calling _load_function_index cold pay registration ONCE."""
    walks: list[float] = []

    def _slow_register() -> None:
        walks.append(time.monotonic())
        time.sleep(0.3)  # stand-in for the 56s real walk

    fake_factory = type(
        "F",
        (),
        {"_ensure_functions_registered": staticmethod(_slow_register)},
    )
    fake_registry_mod = type(
        "R",
        (),
        {
            "FunctionRegistry": type(
                "Reg",
                (),
                {
                    "codes": staticmethod(list),
                    "get": staticmethod(lambda c: None),
                },
            )
        },
    )

    def _safe_import(name: str):
        return {
            "showme.engine.services.function_factory": fake_factory,
            "showme.engine.core.base_function": fake_registry_mod,
        }.get(name)

    monkeypatch.setattr(server, "_safe_import", _safe_import)

    barrier = threading.Barrier(3)
    results: list[list] = []

    def _call():
        barrier.wait()
        results.append(server._load_function_index())

    threads = [threading.Thread(target=_call) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    # All three callers must get the same list; registration walked once.
    assert len(walks) == 1, (
        f"walked {len(walks)} times — build lock failed to serialize"
    )
    assert len(results) == 3, "not all threads returned a result"
    # Results are list copies but should be equal.
    assert all(r == results[0] for r in results)


def test_kickoff_function_index_warmup_populates_cache(monkeypatch):
    """_kickoff_function_index_warmup must populate the cache off-thread.

    Uses a minimal mock factory/registry so the build path actually
    completes — when _safe_import returns None the early-return in
    _build_function_index_locked skips cache population (correct: engine
    not attached → don't cache an empty result that won't get refreshed).
    """
    fake_factory = type(
        "F", (), {"_ensure_functions_registered": staticmethod(lambda: None)}
    )
    fake_registry_mod = type(
        "R",
        (),
        {
            "FunctionRegistry": type(
                "Reg",
                (),
                {
                    "codes": staticmethod(list),  # → empty list
                    "get": staticmethod(lambda c: None),
                },
            )
        },
    )

    def _safe_import(name: str):
        return {
            "showme.engine.services.function_factory": fake_factory,
            "showme.engine.core.base_function": fake_registry_mod,
        }.get(name)

    monkeypatch.setattr(server, "_safe_import", _safe_import)
    server._kickoff_function_index_warmup()
    # Give the daemon thread a beat to run.
    for _ in range(40):
        if server._FUNCTION_INDEX_CACHE is not None:
            break
        time.sleep(0.05)
    assert server._FUNCTION_INDEX_CACHE is not None, (
        "warmup thread did not populate cache within 2s"
    )


def test_warmup_thread_is_daemon():
    """The warmup thread must be daemon so it doesn't block app exit.

    We use a synchronization event so the thread doesn't terminate before
    we can inspect its daemon flag — without this, the early-return path
    runs to completion in microseconds and threading.enumerate() never
    sees it.
    """
    block = threading.Event()
    seen: list[threading.Thread] = []

    def _slow_safe_import(name: str):
        # Capture the thread on first call, then block so it stays alive.
        seen.append(threading.current_thread())
        block.wait(timeout=2.0)
        return None  # → _load_function_index returns [] without caching

    # Patch via setattr (not monkeypatch — we need precise lifecycle control).
    orig = server._safe_import
    server._safe_import = _slow_safe_import
    try:
        server._kickoff_function_index_warmup()
        # Wait for the thread to call _safe_import (proves it's alive).
        for _ in range(40):
            if seen:
                break
            time.sleep(0.05)
        assert seen, "warmup thread did not call _safe_import within 2s"
        worker = seen[0]
        assert worker.name == "showme-function-index-warmup"
        assert worker.daemon, "warmup thread must be daemon"
    finally:
        block.set()  # unblock the worker so it can exit cleanly
        server._safe_import = orig
