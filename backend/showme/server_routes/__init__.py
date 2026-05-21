"""Route packages for the showMe sidecar.

Per ARCH-07 / PY-LINT-03: route handlers are split out of ``server.py``
into family files. Each family module exports a ``register(app, deps)``
function that mounts its routes onto the FastAPI app.

``AppDeps`` holds the small set of shared singletons (boot state, stream
hub provider) that the handlers used to capture via closure inside
``build_app``. Passing it explicitly keeps the family files importable on
their own and easier to test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import FastAPI


@dataclass
class AppDeps:
    """Shared mutable state injected into every route family."""

    boot_state: dict[str, Any] = field(default_factory=dict)
    get_stream_hub: Callable[[], Any] | None = None
    max_body_size_bytes: int = 262144
    ws_allowed_origins: set[str] = field(default_factory=lambda: {
        "tauri://localhost",
        "http://tauri.localhost",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    })
    auth_exempt_paths: set[str] = field(default_factory=lambda: {
        "/api/health",
        "/api/x/health",
    })


def register_routes(app: FastAPI, *, deps: AppDeps) -> None:
    """Mount every route family onto ``app`` using the shared ``deps``."""
    from . import (
        agent,
        ask,
        broker,
        exchange,
        function_index,
        health,
        instant,
        mis,
        portfolio,
        portfolio_aggregate,
        proxy,
        quote,
        scanner,
        state,
        veryfinder,
        watchlists,
        websocket,
        xai,
    )

    health.register(app, deps)
    function_index.register(app, deps)
    quote.register(app, deps)
    scanner.register(app, deps)
    mis.register(app, deps)
    portfolio.register(app, deps)
    portfolio_aggregate.register(app, deps)
    broker.register(app, deps)
    exchange.register(app, deps)
    instant.register(app, deps)
    xai.register(app, deps)
    agent.register(app, deps)
    ask.register(app, deps)
    state.register(app, deps)
    watchlists.register(app, deps)
    veryfinder.register(app, deps)
    websocket.register(app, deps)
    proxy.register(app, deps)


__all__ = ["AppDeps", "register_routes"]
