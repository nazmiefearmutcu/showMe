"""ESG#5-RQ: the ESG seed methodology must describe the proxy window the handler really uses.

The handler bounds every EDGAR full-text query to the last 3 years (proxy_window).
The seed's pane methodology said "recent 10-K filings", which does not name that
window. The seed text must state the window, and the handler's window must be
the one it names.
"""

from __future__ import annotations

from showme.engine.functions.equity import esg as esg_mod
from showme.manifest import REGISTRY, load_seeds


def _seed_methodology() -> str:
    load_seeds()
    return REGISTRY.get("ESG").methodology


def test_seed_methodology_names_the_proxy_window() -> None:
    text = _seed_methodology()
    # Red before the fix: the seed said only "recent 10-K filings".
    assert "last 3 years" in text
    assert "recent 10-K" not in text


def test_seed_window_matches_the_handler_window() -> None:
    assert esg_mod._PROXY_WINDOW_YEARS == 3
    assert "last 3 years" in esg_mod._PROXY_METHODOLOGY
    assert "last 3 years" in _seed_methodology()


def test_module_docstring_states_the_same_window() -> None:
    # ESG#5-RQ: the handler's own docs must not say "recent" for a bounded 3-year window.
    doc = esg_mod.__doc__ or ""
    assert "recent 10-K" not in doc
    assert "last three years" in doc
