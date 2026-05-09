"""Cron-style background job runner.

Job tipleri:
  - "tldr"       → scripts/run_tldr.py invoke
  - "brief"      → scripts/run_brief.py invoke
  - "ingest_13f" → scripts/ingest_13f.py invoke
  - "shell"      → arbitrary shell command (dikkat — sadece local)

State: ``runtime/jobs.sqlite`` + ``runtime/jobs.log`` (per-run output).
"""

from __future__ import annotations

import asyncio
import json
import shlex
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

_DB = Path("runtime/jobs.sqlite")
_LOG_DIR = Path("runtime/jobs")


def _db() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB))
    con.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            interval_seconds INTEGER NOT NULL,
            args TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            last_run_ts INTEGER DEFAULT 0,
            last_status TEXT DEFAULT '',
            created_at INTEGER NOT NULL
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_name TEXT NOT NULL,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            exit_code INTEGER,
            log_path TEXT
        )""")
    con.commit()
    return con


def list_jobs() -> list[dict[str, Any]]:
    con = _db()
    rows = con.execute("SELECT name, kind, interval_seconds, args, enabled, last_run_ts, last_status FROM jobs ORDER BY name").fetchall()
    con.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "name": r[0], "kind": r[1], "interval_seconds": r[2],
            "args": json.loads(r[3] or "{}"),
            "enabled": bool(r[4]),
            "last_run_ts": r[5],
            "last_status": r[6],
        })
    return out


def upsert_job(*, name: str, kind: str, interval_seconds: int = 3600,
               args: dict[str, Any] | None = None, enabled: bool = True) -> None:
    con = _db()
    con.execute(
        "INSERT INTO jobs(name, kind, interval_seconds, args, enabled, created_at) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(name) DO UPDATE SET kind=excluded.kind, "
        "interval_seconds=excluded.interval_seconds, args=excluded.args, "
        "enabled=excluded.enabled",
        [name, kind, int(interval_seconds), json.dumps(args or {}),
         1 if enabled else 0, int(time.time())],
    )
    con.commit(); con.close()


def delete_job(name: str) -> bool:
    con = _db()
    cur = con.execute("DELETE FROM jobs WHERE name = ?", [name])
    con.commit()
    n = cur.rowcount
    con.close()
    return n > 0


def list_runs(name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    con = _db()
    sql = "SELECT id, job_name, started_at, ended_at, exit_code, log_path FROM runs"
    params: list[Any] = []
    if name:
        sql += " WHERE job_name = ?"; params.append(name)
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [{"id": r[0], "job_name": r[1], "started_at": r[2],
             "ended_at": r[3], "exit_code": r[4], "log_path": r[5]} for r in rows]


_KIND_TO_CMD = {
    "tldr":              [sys.executable, "scripts/run_tldr.py"],
    "brief":             [sys.executable, "scripts/run_brief.py"],
    "ingest_13f":        [sys.executable, "scripts/ingest_13f.py"],
    "ingest_transcripts":[sys.executable, "scripts/ingest_transcripts.py"],
    "fundamentals":      [sys.executable, "scripts/refresh_fundamentals.py"],
    "ohlcv_refresh":     [sys.executable, "scripts/refresh_ohlcv.py"],
}


def _resolve_command(kind: str, args: dict[str, Any]) -> list[str]:
    if kind == "shell":
        cmd = args.get("cmd", "")
        return shlex.split(cmd)
    base = list(_KIND_TO_CMD.get(kind, []))
    for k, v in (args or {}).items():
        if v is True:
            base.append(f"--{k}")
        elif v is False or v is None:
            continue
        else:
            base += [f"--{k}", str(v)]
    return base


async def run_job(name: str) -> dict[str, Any]:
    con = _db()
    row = con.execute("SELECT kind, args FROM jobs WHERE name = ?", [name]).fetchone()
    if row is None:
        con.close()
        return {"error": f"unknown job {name}"}
    kind, args_json = row[0], json.loads(row[1] or "{}")
    cmd = _resolve_command(kind, args_json)
    if not cmd:
        con.close()
        return {"error": f"no command for kind {kind}"}
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOG_DIR / f"{name}-{int(time.time())}.log"
    started = int(time.time())
    cur = con.execute(
        "INSERT INTO runs(job_name, started_at, log_path) VALUES (?,?,?)",
        [name, started, str(log_path)],
    )
    run_id = cur.lastrowid
    con.commit(); con.close()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=open(log_path, "wb"),
        stderr=asyncio.subprocess.STDOUT,
    )
    rc = await proc.wait()
    ended = int(time.time())
    con = _db()
    con.execute(
        "UPDATE runs SET ended_at = ?, exit_code = ? WHERE id = ?",
        [ended, rc, run_id],
    )
    status = "ok" if rc == 0 else f"failed:{rc}"
    con.execute(
        "UPDATE jobs SET last_run_ts = ?, last_status = ? WHERE name = ?",
        [ended, status, name],
    )
    con.commit(); con.close()
    return {"job": name, "run_id": run_id, "exit_code": rc,
             "log_path": str(log_path),
             "duration_s": ended - started}


async def scheduler_loop(interval_seconds: int = 60) -> None:
    """Run as a background task; checks jobs once a minute."""
    while True:
        try:
            for job in list_jobs():
                if not job["enabled"]:
                    continue
                if (time.time() - (job["last_run_ts"] or 0)) >= job["interval_seconds"]:
                    try:
                        await run_job(job["name"])
                    except Exception:
                        continue
        except Exception:
            pass
        await asyncio.sleep(interval_seconds)
