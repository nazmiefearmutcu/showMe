"""Seed modules for the FunctionManifest registry.

Each ``<code>_seed.py`` module imports the ``@manifest`` decorator and
registers a single FunctionManifest at import time. ``load_seeds()``
auto-discovers every ``*_seed.py`` in this package so the registry is
populated before any route handler asks for entries.

Auto-discovery means parallel agents can drop new seed files in this
directory without coordinating on an explicit import list — no merge
conflicts on __init__.py.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Iterable


def _discover_seed_modules() -> tuple[str, ...]:
    """Return every ``*_seed`` short name in this package."""
    found: list[str] = []
    for info in pkgutil.iter_modules(__path__):  # type: ignore[name-defined]
        if info.ispkg:
            continue
        if info.name.endswith("_seed"):
            found.append(info.name)
    return tuple(sorted(found))


def load_seeds(module_names: Iterable[str] | None = None) -> list[str]:
    """Import every seed module so its ``@manifest`` decorators run.

    Returns the list of fully qualified module names imported. Idempotent.
    If ``module_names`` is None, auto-discovers ``*_seed`` modules in this
    package.
    """
    names = tuple(module_names) if module_names is not None else _discover_seed_modules()
    loaded: list[str] = []
    for short in names:
        full = f"{__name__}.{short}"
        importlib.import_module(full)
        loaded.append(full)
    return loaded


__all__ = ["load_seeds"]
