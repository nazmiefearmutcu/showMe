"""BMTX#5 regression: every seed-declared input is read, and the router keeps the handler window.

The seed previously declared strategy_id, walk_forward_windows and frequency,
which the handler never read, and the router forced days=120 onto BMTX
(about 25 holdout bars). Declared inputs must now be consumed by the handler.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import showme.engine.functions.portfolio.bmtx as bmtx_module
from showme.manifest.seeds.bmtx_seed import bmtx as bmtx_manifest

def test_every_seed_input_is_read_by_the_handler() -> None:
    # No allowlist: a declared control the handler never reads is a fake control.
    src = Path(bmtx_module.__file__).read_text(encoding="utf-8")
    unread = [
        spec.name
        for spec in bmtx_manifest.inputs
        if f'"{spec.name}"' not in src
    ]
    assert unread == [], f"seed declares inputs the handler ignores: {unread}"


def test_router_sends_an_explicit_bounded_bmtx_window() -> None:
    from showme.server_routes._agent_runtime import _agent_function_params

    entry = SimpleNamespace(code="BMTX", category="portfolio", asset_classes=["EQUITY"])
    params = _agent_function_params(entry, {"symbol": "SPY", "asset_class": "EQUITY"})

    # The handler default is 3 years of daily bars, whose compute exceeds the
    # live budget on a universe. The router sends a bounded window explicitly
    # (oos_windows reports the test-slice size it yields).
    assert params["days"] == 120
