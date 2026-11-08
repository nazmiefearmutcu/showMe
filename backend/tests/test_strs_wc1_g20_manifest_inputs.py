"""STRS#7 — every STRS manifest control the user can set must reach the engine.

The custom basket (portfolio_source=custom, positions) was offered but never read by
the handler; it is removed rather than left as a control that does nothing. The
horizon control is labelled as custom-only because named scenarios keep their own
catalog horizon. scenario_magnitudes is read as the scale factor.
"""

from __future__ import annotations

from pathlib import Path

from showme.manifest import REGISTRY, load_seeds

_STRS_SRC = Path(__file__).resolve().parents[1] / "showme" / "engine" / "functions" / "portfolio" / "strs.py"

# Inputs the handler does not read by name. Each is a documented limitation, not a
# silent control: propagation has one option that describes the engine's only method;
# provider_mode is not wired to the yfinance history path (residual, see the commit).
_DESCRIPTIVE_OR_RESIDUAL = {"propagation", "provider_mode"}


def _strs():
    load_seeds()
    return REGISTRY.get("STRS")


def test_custom_basket_controls_are_removed():
    names = {i.name for i in _strs().inputs}
    assert "positions" not in names, names
    assert "portfolio_source" not in names, names
    assert "portfolio_source" not in (_strs().defaults or {})


def test_horizon_control_says_it_applies_to_custom_shocks_only():
    horizon = next(i for i in _strs().inputs if i.name == "horizon_days")
    desc = horizon.description.lower()
    assert "custom" in desc, horizon.description
    assert "named" in desc or "catalog" in desc, horizon.description


def test_every_manifest_input_is_read_by_the_handler_or_is_declared_residual():
    src = _STRS_SRC.read_text(encoding="utf-8")
    unread = []
    for item in _strs().inputs:
        if item.name in _DESCRIPTIVE_OR_RESIDUAL:
            continue
        if f'params.get("{item.name}"' not in src and f'params["{item.name}"]' not in src:
            unread.append(item.name)
    assert not unread, f"STRS manifest controls the handler never reads: {unread}"


def test_scenario_magnitudes_is_read_as_the_scale_factor():
    src = _STRS_SRC.read_text(encoding="utf-8")
    assert '"scenario_magnitudes"' in src
