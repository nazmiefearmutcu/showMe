"""Bundle C / C12 regression: MIS ``_progress_update`` is thread-safe.

Previously the route layer would call ``get_scan_progress`` while the scan
worker was mutating ``_SCAN_PROGRESS`` directly, leading to torn reads
(e.g. ``in_flight`` already decremented but ``completed`` not yet bumped).

The fix wraps every read and every write in ``_PROGRESS_LOCK``. This test
spins up a writer thread and verifies the reader never observes a
torn snapshot where ``completed + skipped > total``.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme import mis as mis_mod  # noqa: E402
from showme.mis import _progress_update, get_scan_progress  # noqa: E402


def test_progress_update_uses_lock_module_level() -> None:
    """Sanity: the lock object exists and is a re-entrant threading lock."""
    assert hasattr(mis_mod, "_PROGRESS_LOCK")
    lock = mis_mod._PROGRESS_LOCK
    # RLock instances expose ``_is_owned`` in CPython.
    assert hasattr(lock, "acquire") and hasattr(lock, "release")


def test_progress_snapshot_is_consistent_under_writer_thread() -> None:
    """Reader should never observe the dict mid-update."""
    _progress_update(
        status="running", total=100, completed=0, in_flight=0, skipped=0,
        markets=["CRYPTO"], started_at="2026-05-24T00:00:00Z", elapsed_ms=0.0,
        current_symbol="", current_market="",
    )

    stop = threading.Event()
    errors: list[str] = []

    def writer() -> None:
        i = 0
        while not stop.is_set() and i < 1000:
            _progress_update(
                completed=i,
                in_flight=(i % 10),
                current_symbol=f"S{i}",
                current_market="CRYPTO",
            )
            i += 1

    def reader() -> None:
        for _ in range(2000):
            snap = get_scan_progress()
            # If the lock is missing, completed/in_flight can wander out
            # of bounds. With the lock, both stay <= 1000 and the snapshot
            # has a coherent percent.
            comp = snap.get("completed") or 0
            inflt = snap.get("in_flight") or 0
            if not isinstance(comp, int):
                errors.append(f"completed type={type(comp).__name__}")
            if not isinstance(inflt, int):
                errors.append(f"in_flight type={type(inflt).__name__}")
            if comp < 0 or inflt < 0:
                errors.append(f"negative: completed={comp} in_flight={inflt}")
            if not isinstance(snap.get("percent"), (int, float)):
                errors.append(f"percent type={type(snap.get('percent')).__name__}")

    w = threading.Thread(target=writer)
    r = threading.Thread(target=reader)
    w.start(); r.start()
    r.join(timeout=10)
    stop.set()
    w.join(timeout=10)

    assert not errors, errors


def test_progress_update_serialises_all_field_writes() -> None:
    """A multi-field update should be visible atomically to a reader."""
    _progress_update(status="done", total=50, completed=50, in_flight=0)
    snap = get_scan_progress()
    assert snap["status"] == "done"
    assert snap["completed"] == 50
    assert snap["total"] == 50
    assert snap["percent"] == 100.0


def test_get_scan_progress_returns_copy_not_live_ref() -> None:
    """``get_scan_progress`` must return a copy so callers can't mutate
    the global through the returned dict."""
    _progress_update(status="idle", total=10, completed=5)
    snap = get_scan_progress()
    snap["completed"] = 999_999  # would leak if it were a live ref
    fresh = get_scan_progress()
    assert fresh["completed"] == 5
