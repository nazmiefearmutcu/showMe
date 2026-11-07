#!/usr/bin/env python3
"""Boot the showMe sidecar on an OS-picked port and verify it answers.

Checks: the process prints ``SIDECAR_PORT=<p>``, ``/api/health`` returns
``ok: true`` and ``/api/function-index`` lists at least ``--min-functions``
entries. Exit code 0 on success, 1 on any failure.

The helpers (:func:`start_sidecar`, :func:`stop_sidecar`, :func:`get_json`)
are reused by the strict function audit so it can (re)start its own sidecar
without ever touching a fixed port.

Usage::

    backend/.venv/Scripts/python.exe scripts/sidecar_smoke.py [--min-functions 141]
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_PYTHON = BACKEND / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


class SidecarError(RuntimeError):
    """The sidecar failed to start or to answer."""


def _pump(stream, sink: "queue.Queue[str]", log: list[str]) -> None:
    for line in iter(stream.readline, ""):
        log.append(line)
        sink.put(line)
    stream.close()


def start_sidecar(
    python: Path | str = DEFAULT_PYTHON,
    *,
    timeout: float = 180.0,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.Popen, int, list[str]]:
    """Start ``showme.server --port 0``; return ``(process, port, output_log)``.

    ``output_log`` keeps accumulating the merged stdout/stderr lines for as
    long as the process lives (useful for diagnosing a later crash).
    """
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if extra_env:
        env.update(extra_env)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    proc = subprocess.Popen(
        [str(python), "-m", "showme.server", "--port", "0"],
        cwd=BACKEND,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    lines: "queue.Queue[str]" = queue.Queue()
    log: list[str] = []
    threading.Thread(target=_pump, args=(proc.stdout, lines, log), daemon=True).start()
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise SidecarError(f"sidecar exited with {proc.returncode}:\n{''.join(log[-40:])}")
            try:
                line = lines.get(timeout=0.5)
            except queue.Empty:
                continue
            if line.startswith("SIDECAR_PORT="):
                return proc, int(line.split("=", 1)[1].strip()), log
        raise SidecarError(f"no SIDECAR_PORT line within {timeout:.0f}s:\n{''.join(log[-40:])}")
    except BaseException:
        # Never leave a half-started sidecar behind (timeout, Ctrl+C, bad port line).
        stop_sidecar(proc)
        raise


def stop_sidecar(proc: subprocess.Popen, *, grace: float = 10.0) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=grace)


def get_json(url: str, *, timeout: float = 30.0) -> tuple[int, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, body


def wait_healthy(base: str, *, timeout: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            status, body = get_json(f"{base}/api/health", timeout=10)
            last = body
            if status == 200 and isinstance(body, dict) and body.get("ok"):
                return body
        except (OSError, ValueError) as exc:  # ValueError: non-JSON body
            last = repr(exc)
        time.sleep(1.0)
    raise SidecarError(f"/api/health not ok within {timeout:.0f}s: {last}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--python", default=str(DEFAULT_PYTHON))
    parser.add_argument("--min-functions", type=int, default=141)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args(argv)

    started = time.monotonic()
    try:
        proc, port, log = start_sidecar(args.python, timeout=args.timeout)
    except SidecarError as exc:
        print(f"FAIL start: {exc}", file=sys.stderr)
        return 1
    base = f"http://127.0.0.1:{port}"
    try:
        health = wait_healthy(base, timeout=args.timeout)
        status, index = get_json(f"{base}/api/function-index", timeout=60)
        if status != 200 or not isinstance(index, list):
            print(f"FAIL function-index: http {status}: {str(index)[:300]}", file=sys.stderr)
            return 1
        if len(index) < args.min_functions:
            print(f"FAIL function-index: {len(index)} < {args.min_functions} entries", file=sys.stderr)
            return 1
        elapsed = time.monotonic() - started
        print(
            f"OK sidecar port={port} health.ok={health.get('ok')} "
            f"functions={len(index)} boot={elapsed:.1f}s"
        )
        return 0
    except (SidecarError, OSError, ValueError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    finally:
        stop_sidecar(proc)


if __name__ == "__main__":
    sys.exit(main())
