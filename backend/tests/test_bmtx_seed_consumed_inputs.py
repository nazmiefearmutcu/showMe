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

# paper_mode is a declared invariant (BMTX is paper-safe by construction and
# test_wave2_portfolio_ext_seeds pins its default). provider_mode is a
# preference the handler does not switch on: OHLCV always comes from yfinance
# and the result's sources say so, so it cannot be mislabelled.
_NOT_READ_BY_DESIGN = {"paper_mode", "provider_mode"}


def test_every_seed_input_is_read_by_the_handler() -> None:
    src = Path(bmtx_module.__file__).read_text(encoding="utf-8")
    unread = [
        spec.name
        for spec in bmtx_manifest.inputs
        if spec.name not in _NOT_READ_BY_DESIGN and f'"{spec.name}"' not in src
    ]
    assert unread == [], f"seed declares inputs the handler ignores: {unread}"


def test_router_does_not_force_a_short_bmtx_window() -> None:
    from showme.server_routes._agent_runtime import _agent_function_params

    entry = SimpleNamespace(code="BMTX", category="portfolio", asset_classes=["EQUITY"])
    params = _agent_function_params(entry, {"symbol": "SPY", "asset_class": "EQUITY"})

    # Absent days lets the handler default (3 years of daily bars) apply.
    assert "days" not in params
