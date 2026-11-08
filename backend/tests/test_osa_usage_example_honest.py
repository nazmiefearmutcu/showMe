"""OSA agent usage example must not carry placeholder spot or template strikes.

An agent that copies the OSA usage example would otherwise price a 100/110
call spread at spot 100 (T10: no placeholder inputs).
"""

from __future__ import annotations

from showme.server_routes._agent_runtime import _function_usage


def _osa_example() -> dict:
    usage = _function_usage(
        "OSA",
        "Option Strategy Analysis",
        "derivative",
        "Option strategy analysis",
        ["DERIVATIVE"],
    )
    return usage["example"]


def test_osa_example_carries_no_placeholder_spot() -> None:
    example = _osa_example()
    assert "spot" not in example


def test_osa_example_legs_are_not_numeric_template_strikes() -> None:
    for leg in _osa_example()["legs"]:
        assert isinstance(leg["strike"], str), leg
        assert isinstance(leg["vol"], str), leg
        assert isinstance(leg["expiry"], str), leg


def test_osa_example_is_marked_shape_only() -> None:
    usage = _function_usage(
        "OSA", "Option Strategy Analysis", "derivative", "Option strategy analysis", ["DERIVATIVE"],
    )
    assert "Shape only" in usage["example_note"]
