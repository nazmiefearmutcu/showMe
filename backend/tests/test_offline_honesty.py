"""T10 offline honesty ratchet (``showme/audit/offline.py``).

With every outbound connection refused no function may claim live data, show
placeholder values, name a fake source or crash. The audit runs in a
subprocess (fresh singletons, its own throw-away SHOWME_HOME, bots off) and
its per-function red counts are compared with ``tests/_offline_baseline.json``:
counts may only go down. When fixes lower them, refresh the baseline with::

    SHOWME_UPDATE_OFFLINE_BASELINE=1 pytest tests/test_offline_honesty.py

which refuses to raise any count.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from showme.audit import gate, offline

BACKEND = Path(__file__).resolve().parents[1]


def test_network_cut_refuses_outbound_and_keeps_loopback():
    with offline.network_cut():
        with pytest.raises(OSError):
            socket.create_connection(("example.com", 443), timeout=3)
        with pytest.raises(OSError):
            socket.create_connection(("93.184.215.14", 443), timeout=3)
        a, b = socket.socketpair()  # asyncio's self-pipe on Windows
        a.close()
        b.close()
        asyncio.run(asyncio.sleep(0))
        assert os.environ["HTTPS_PROXY"] == offline.DEAD_PROXY
    assert socket.getaddrinfo("localhost", 80)
    assert os.environ.get("HTTPS_PROXY") != offline.DEAD_PROXY


def test_asyncio_connections_to_ip_literals_are_refused():
    """IP literals skip DNS; asyncio's sock_connect must still refuse them."""

    async def connect() -> None:
        await asyncio.open_connection("93.184.215.14", 443)

    with offline.network_cut():
        with pytest.raises(OSError):
            asyncio.run(asyncio.wait_for(connect(), 5))


def test_grade_flags_a_live_claim_and_a_crash():
    from datetime import datetime, timezone

    from showme.audit import truth

    cfg = truth.load_config()
    now = datetime.now(timezone.utc)
    live = {"status": "ok", "data_state": "live", "sources": ["yfinance"], "asOf": now.isoformat(),
            "data": {"rows": [{"x": 1.0}]}}
    rules = {f.rule for f in offline.grade("XYZ", "equity", {}, 200, live, 0.1, cfg=cfg, now=now, budget=8)}
    assert "offline_live_claim" in rules
    honest = {"status": "provider_unavailable", "reason": "network down", "nextAction": "Retry when online.",
              "data": {}}
    assert not [f for f in offline.grade("XYZ", "equity", {}, 200, honest, 0.1, cfg=cfg, now=now, budget=8)
                if f.severity == "red"]
    crash = offline.grade("XYZ", "equity", {}, 500, "Internal Server Error", 0.1, cfg=cfg, now=now, budget=8)
    assert [f.rule for f in crash] == ["offline_crash"]


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    out = tmp_path_factory.mktemp("offline") / "report.json"
    home = tmp_path_factory.mktemp("offline-home")
    env = dict(os.environ, SHOWME_DISABLE_BOTS="1",
               PYTHONPATH=os.pathsep.join(filter(None, [str(BACKEND), os.environ.get("PYTHONPATH")])))
    proc = subprocess.run(
        [sys.executable, "-m", "showme.audit.offline", "--json", str(out), "--home", str(home)],
        cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1500,
    )
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(out.read_text(encoding="utf-8"))


def test_offline_run_covers_every_function_and_the_cut_holds(report):
    leaks = [stack for stack, verdict in report["probe"].items() if verdict == "LEAK"]
    assert not leaks, f"the network cut leaked through {leaks}: {report['probe']}"
    assert len(report["functions"]) >= 141


def test_no_new_offline_honesty_findings(report):
    current = offline.to_counts(report)
    updating = os.environ.get("SHOWME_UPDATE_OFFLINE_BASELINE") == "1"
    baseline = offline.load_baseline()
    if baseline is None:
        if not updating:
            pytest.fail(f"{offline.BASELINE_PATH} is missing; seed it deliberately with "
                        "SHOWME_UPDATE_OFFLINE_BASELINE=1 (deleting it must not reset the ratchet)")
        offline.write_baseline(current)
        baseline = current
    elif updating:
        offline.write_baseline(gate.lowered_baseline(current, baseline))
        baseline = offline.load_baseline()
    rises = gate.regressions(current, baseline)
    assert not rises, (
        "functions that now claim live data, show placeholders or crash with the network cut "
        "(fix them; the baseline only goes down):\n  " + "\n  ".join(rises)
    )
