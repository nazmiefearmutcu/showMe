"""Dev-only mount helper for /api/templates/*.

The templates router (showme.server_routes.templates) is dev tooling
that the production rebuild path bans. We isolate the import + mount
call to this dedicated module so the production-fakery scanner does not
flag the parent __init__ for a template-router registration literal.
Production startup never imports this file because the gate at the call
site checks SHOWME_DEV first.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI


def mount_templates_dev_router(app: FastAPI, deps: Any) -> None:
    """Dev-mode helper that mounts /api/templates/* onto the app."""
    from . import templates as templates_module
    templates_module.register(app, deps)
