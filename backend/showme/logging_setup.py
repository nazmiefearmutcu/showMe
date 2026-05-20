"""Centralised logging + crash-hook setup for the sidecar.

Per TEST-07/PY-LINT-06:

* ``configure_logging(level, *, json_lines=False)`` installs a console
  formatter with a millisecond timestamp **and** a rotating file handler
  under ``<app_home>/logs/sidecar.log`` (10 MB × 5 backups). When
  ``$SHOWME_LOG_JSON=1`` (or ``json_lines=True``) the format flips to
  one-JSON-per-line so log shippers can parse it.
* ``install_crash_hook()`` writes any uncaught Python exception under
  ``<app_home>/logs/crash/<timestamp>.log`` so we have a stack trace
  after a hard fatal exit. The previous behavior dropped tracebacks the
  moment uvicorn exited.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType


_DEFAULT_FMT = (
    "%(asctime)s.%(msecs)03d [showme.sidecar] %(levelname)s %(name)s %(message)s"
)
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"
_MAX_FILE_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5


class _JsonLineFormatter(logging.Formatter):
    """Emit each log record as a JSON object on its own line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = "".join(traceback.format_exception(*record.exc_info))
        return json.dumps(payload, default=str)


def _build_console_handler(level: int, *, json_lines: bool) -> logging.Handler:
    handler = logging.StreamHandler(sys.stderr)
    if json_lines:
        handler.setFormatter(_JsonLineFormatter())
    else:
        handler.setFormatter(logging.Formatter(_DEFAULT_FMT, datefmt=_DEFAULT_DATEFMT))
    handler.setLevel(level)
    return handler


def _build_file_handler(log_dir: Path, level: int, *, json_lines: bool) -> logging.Handler:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "sidecar.log",
        maxBytes=_MAX_FILE_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    if json_lines:
        handler.setFormatter(_JsonLineFormatter())
    else:
        handler.setFormatter(logging.Formatter(_DEFAULT_FMT, datefmt=_DEFAULT_DATEFMT))
    handler.setLevel(level)
    return handler


def _resolve_log_dir() -> Path | None:
    raw = os.environ.get("SHOWME_HOME")
    if raw:
        return Path(raw).expanduser() / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "showMe" / "logs"
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(appdata) / "showMe" / "logs"
    xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg) / "showMe" / "logs"


def configure_logging(level: str = "info", *, json_lines: bool | None = None) -> None:
    """Install console + rotating-file handlers on the root logger.

    Idempotent: re-running replaces the previous showMe handlers without
    duplicating output.
    """
    if json_lines is None:
        json_lines = os.environ.get("SHOWME_LOG_JSON", "").strip().lower() in {"1", "true", "yes"}
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    # Drop any previous handlers we installed so re-init is safe (test runs).
    for handler in list(root.handlers):
        if getattr(handler, "_showme", False):
            root.removeHandler(handler)
    console = _build_console_handler(numeric_level, json_lines=json_lines)
    console._showme = True  # type: ignore[attr-defined]
    root.addHandler(console)
    log_dir = _resolve_log_dir()
    if log_dir is not None:
        try:
            file_handler = _build_file_handler(log_dir, numeric_level, json_lines=json_lines)
            file_handler._showme = True  # type: ignore[attr-defined]
            root.addHandler(file_handler)
        except OSError as exc:
            console.handle(
                logging.LogRecord(
                    name="showme.logging_setup",
                    level=logging.WARNING,
                    pathname=__file__,
                    lineno=0,
                    msg="rotating file handler unavailable: %s",
                    args=(exc,),
                    exc_info=None,
                )
            )
    root.setLevel(numeric_level)


def install_crash_hook(log_dir: Path | None = None) -> None:
    """Install ``sys.excepthook`` that drops a crash log under ``logs/crash/``.

    Per TEST-07 P1: previously an uncaught Python exception printed to
    stderr and disappeared once uvicorn exited. We now persist the
    traceback so post-mortem triage has something to read.
    """
    crash_dir = (log_dir or _resolve_log_dir() or Path.cwd() / "logs") / "crash"
    crash_dir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("showme.crash")

    previous_hook = sys.excepthook

    def hook(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:
        try:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            target = crash_dir / f"sidecar-{stamp}.log"
            with target.open("w", encoding="utf-8") as fh:
                fh.write(
                    f"# showMe sidecar crash report — {stamp}\n"
                    f"# pid={os.getpid()} platform={sys.platform}\n\n"
                )
                traceback.print_exception(exc_type, exc, tb, file=fh)
            log.error(
                "uncaught %s; crash log written to %s", exc_type.__name__, target,
            )
        except Exception:  # noqa: BLE001
            log.exception("failed to write crash report")
        previous_hook(exc_type, exc, tb)

    sys.excepthook = hook


__all__ = ["configure_logging", "install_crash_hook"]
