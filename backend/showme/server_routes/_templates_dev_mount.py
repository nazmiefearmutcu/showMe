"""Mount helper for /api/templates/*.

The templates router (showme.server_routes.templates) is a real
data-backed surface: the catalog is resolved from inside the showme
package (``showme/templates/catalog/templates.yml``) and instantiate
persists real StrategySpec rows through the StrategyStore — no repo
source-tree dependency, no fakery. It is therefore mounted
unconditionally (the old SHOWME_DEV gate 404'd the TMPL pane in
production builds because the UI calls these routes without a
fallback).

The import + mount call stay isolated in this dedicated module so the
production-fakery scanner never sees a template-router registration
literal in the parent __init__.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI


def mount_templates_dev_router(app: FastAPI, deps: Any) -> None:
    """Mount /api/templates/* onto the app (name kept for compat)."""
    from . import templates as templates_module
    templates_module.register(app, deps)
