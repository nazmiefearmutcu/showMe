"""DAPI truth checks (p2a-g11): no placeholder base URL, OpenAPI-form proxy path."""
from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.api.dapi import DAPI_CURATED_ROUTES, DAPIFunction


def _run() -> dict:
    return asyncio.run(DAPIFunction(FunctionDeps()).execute()).data


def test_base_url_is_not_a_literal_placeholder() -> None:
    summary = _run()["summary"]
    base = summary.get("base_url")
    # The backend does not know the bound port; it must say so instead of
    # serving a template string that copy-as-curl would turn into a broken URL.
    assert base is None or "<sidecar-port>" not in str(base)
    assert "<sidecar-port>" not in str(summary)


def test_curated_proxy_path_uses_openapi_form() -> None:
    proxy = [r for r in DAPI_CURATED_ROUTES if r["path"].startswith("/api/proxy/")]
    assert proxy, "proxy row missing"
    # OpenAPI (and the drift audit) render the catch-all as {path}; the
    # Starlette converter form {path:path} made exact comparisons fail.
    assert all(":path}" not in r["path"] for r in proxy)


def test_no_startup_wiring_is_claimed_for_route_provider() -> None:
    # Nothing under backend assigns deps.dapi_route_provider, so the module and
    # seed must not say server.py wires it at startup (the pre-fix wording).
    # Pre-fix dapi.py line 5 read "(set by server.py at startup)"; this fails on it.
    from pathlib import Path

    from showme.engine.functions.api import dapi as dapi_module
    from showme.manifest.seeds import dapi_seed

    module_text = Path(dapi_module.__file__).read_text(encoding="utf-8")
    seed_text = Path(dapi_seed.__file__).read_text(encoding="utf-8")
    assert "server.py" not in module_text
    assert "server.py" not in seed_text
    methodology = _run()["methodology"]
    assert "server.py" not in methodology
    assert "nothing assigns it" in methodology
