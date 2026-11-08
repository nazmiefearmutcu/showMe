"""GREEKS#1 follow-up: the pane can reach the explicit rate units.

``rate_pct`` and ``rate_bps`` are per-position keys read by the handler
(``engine/functions/portfolio/greeks.py``), so the pane sends them inside the
``positions`` JSON. They are not top-level inputs, so no InputSpec is added for
them; the ``positions`` input must name them so a user can find the unit that
removes the decimal/percent guess.
"""

from __future__ import annotations

from showme.manifest import REGISTRY, load_seeds


def _positions_input():
    load_seeds()
    entry = REGISTRY.get("GREEKS")
    return next(i for i in entry.inputs if i.name == "positions")


def test_positions_input_names_the_explicit_rate_units() -> None:
    description = _positions_input().description
    assert "rate_pct" in description
    assert "rate_bps" in description


def test_positions_input_states_the_plain_rate_reading() -> None:
    description = _positions_input().description
    assert "decimal" in description
    assert "above 1" in description
