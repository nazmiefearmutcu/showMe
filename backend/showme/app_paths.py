"""Central path helper for runtime, state, and cache files.

Per ARCH-09 P0: nothing in the engine should reach for a hardcoded
``Path("runtime/...")`` literal anymore — relative paths get resolved
against ``os.getcwd()``, which only happens to land in the right place
inside the PyInstaller bundle (where ``server.prepare_writable_cwd`` does
``os.chdir(app_home)``). In dev, in tests, and in any sub-process spawned
from a different cwd, those literals silently create a parallel runtime
tree.

Resolution order for ``app_home``:
  1. ``SHOWME_HOME`` env var (any platform, any caller).
  2. macOS default: ``~/Library/Application Support/showMe``.
  3. Linux / fallback: ``~/.local/share/showMe``.

Every accessor ensures the parent directory exists before returning so
callers can immediately ``open(..., "w")`` against the result.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _platform_default_home() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "showMe"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "showMe"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "showMe"


def app_home() -> Path:
    """Return the canonical showMe state root.

    Honors ``SHOWME_HOME`` if present so tests, dev shells, and packaged
    builds all agree.
    """
    raw = os.environ.get("SHOWME_HOME")
    if raw:
        return Path(raw).expanduser()
    return _platform_default_home()


def _ensure(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def runtime_path(name: str) -> Path:
    """Resolve a file under ``<app_home>/runtime/``.

    Use this everywhere the engine used to write ``Path("runtime/<name>")``.
    """
    return _ensure(app_home() / "runtime" / name)


def state_path(name: str) -> Path:
    """Resolve a file under ``<app_home>/state/`` (durable user data)."""
    return _ensure(app_home() / "state" / name)


def cache_path(name: str) -> Path:
    """Resolve a file under ``<app_home>/cache/`` (ephemeral, redownloadable)."""
    return _ensure(app_home() / "cache" / name)


__all__ = [
    "app_home",
    "runtime_path",
    "state_path",
    "cache_path",
]
