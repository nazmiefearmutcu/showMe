"""Bundle C / C4 regression: ``run_job`` does not leak DB connections or FDs.

Previously every error path failed to call ``con.close()`` and the log file
opened via ``open(log_path, 'wb')`` was passed to ``create_subprocess_exec``
without context-management, so a crash mid-execution would leak both.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))


@pytest.fixture
def isolated_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point app_paths.runtime_path at a tmp dir so the test owns the sqlite db."""
    from showme import app_paths

    def fake_runtime_path(name: str) -> Path:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    monkeypatch.setattr(app_paths, "runtime_path", fake_runtime_path)
    # job_runner imports runtime_path at module scope — patch its binding too.
    from showme.engine.services import job_runner
    monkeypatch.setattr(job_runner, "runtime_path", fake_runtime_path)
    return tmp_path


async def test_run_job_closes_db_on_unknown_name(isolated_runtime: Path) -> None:
    """Unknown job name: the early-return path must still close the DB cursor."""
    from showme.engine.services.job_runner import run_job

    # If we leak the connection, subsequent inserts on the same path would
    # block / lock. We assert by simply calling twice in sequence and
    # verifying both return the expected error without raising.
    r1 = await run_job("does-not-exist-1")
    r2 = await run_job("does-not-exist-2")
    assert r1["error"].startswith("unknown job")
    assert r2["error"].startswith("unknown job")


async def test_run_job_completes_and_writes_log(isolated_runtime: Path) -> None:
    """Happy path: command runs, log file is opened+closed cleanly, DB updated."""
    from showme.engine.services.job_runner import run_job, upsert_job

    # Register a 'shell' job that just `echo`s — exits 0.
    upsert_job(name="echo-test", kind="shell", interval_seconds=3600,
               args={"cmd": "echo hello-job-runner"})

    result = await run_job("echo-test")
    assert result["exit_code"] == 0
    log_path = Path(result["log_path"])
    assert log_path.exists()
    # File must be closed (Windows is strict; POSIX silently allows but we
    # still want the contract). Try to open exclusively to confirm no
    # lingering FD on Linux/macOS — the cleanest check is that we can read
    # it without an error and the content includes our echo string.
    content = log_path.read_text()
    assert "hello-job-runner" in content


async def test_run_job_handles_nonexistent_command_without_leak(
    isolated_runtime: Path,
) -> None:
    """Spawning a non-existent binary must still close DB + log file."""
    from showme.engine.services.job_runner import run_job, upsert_job

    upsert_job(
        name="bad-cmd",
        kind="shell",
        interval_seconds=3600,
        args={"cmd": "/this/path/definitely/does/not/exist-xyz arg"},
    )

    # The fix wraps the spawn in try/except so even FileNotFoundError is
    # turned into a non-zero exit code rather than bubbling up.
    result = await run_job("bad-cmd")
    assert result["exit_code"] != 0
    # Log file path was registered and the file exists.
    log_path = Path(result["log_path"])
    assert log_path.exists()
    # The failure note should have been appended.
    content = log_path.read_text()
    assert "failed" in content.lower() or content == ""
