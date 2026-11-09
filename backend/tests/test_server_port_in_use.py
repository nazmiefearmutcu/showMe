"""Sidecar must fail fast and honestly when an explicit --port is taken.

Before 2026-11-07 ``showme.server --port N`` printed ``SIDECAR_PORT=N``
*before* binding, started the full lifespan (bot runner included) and only
then died inside uvicorn with a raw Winsock 10048 message. Anything reading
the discovery line would talk to whichever process really owned port N.
And with ``SO_REUSEADDR`` on Windows a bind can even succeed on a port
another socket already holds.

Contract now: the explicit port is bound up front (exclusively on Windows);
if it is taken, no ``SIDECAR_PORT=`` line is printed, the exit code is
non-zero, and one stderr line names the port, the owning PID when it can
be found, and suggests ``--port 0``.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from showme import server

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def occupied_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform == "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


def test_pick_port_raises_typed_error_for_taken_port(occupied_port):
    with pytest.raises(server.PortInUseError) as excinfo:
        server._pick_port(occupied_port, host="127.0.0.1")
    message = str(excinfo.value)
    assert str(occupied_port) in message
    assert "--port 0" in message


def test_pick_port_binds_free_explicit_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    free = probe.getsockname()[1]
    probe.close()
    port, sock = server._pick_port(free, host="127.0.0.1")
    try:
        assert port == free
        assert sock is not None  # explicit ports are now pre-bound too
    finally:
        sock.close()


def test_pick_port_zero_still_reserves_ephemeral_port():
    port, sock = server._pick_port(0, host="127.0.0.1")
    try:
        assert port > 0
        assert sock is not None
    finally:
        sock.close()


@pytest.mark.skipif(sys.platform != "win32", reason="owner lookup uses netstat -ano (Windows)")
def test_port_owner_lookup_finds_this_process(occupied_port):
    owner = server._describe_port_owner(occupied_port)
    assert owner is not None
    assert str(os.getpid()) in owner


def test_cli_exits_nonzero_without_discovery_line(occupied_port, tmp_path):
    env = dict(os.environ)
    env["SHOWME_HOME"] = str(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "showme.server", "--port", str(occupied_port)],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode != 0
    assert "SIDECAR_PORT=" not in proc.stdout
    assert str(occupied_port) in proc.stderr
    assert "--port 0" in proc.stderr
    assert "10048" not in proc.stderr  # no raw Winsock text
