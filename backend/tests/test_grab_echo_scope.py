"""GRAB echoes only the parameters the caller sent.

Regression for GRAB#3: the router merged the generic agent defaults (default
news query, peer symbols, limit, timeouts) into GRAB's routed params, so the
envelope inputEcho showed values the GRAB handler never reads.
"""

from __future__ import annotations

from showme import server


def test_grab_routed_params_carry_only_caller_inputs() -> None:
    routed = server._route_function_params("GRAB", {"target": "current_pane"})
    visible = {k: v for k, v in routed.items() if not k.startswith("__")}
    assert visible == {"target": "current_pane"}


def test_grab_routed_params_drop_generic_news_and_peer_defaults() -> None:
    routed = server._route_function_params("GRAB", {})
    for key in ("query", "symbols", "limit", "days", "range", "topic", "live", "timeout"):
        assert key not in routed, f"GRAB must not receive the generic default {key!r}"


def test_grab_keeps_explicit_recipient_and_send() -> None:
    routed = server._route_function_params("GRAB", {"recipient": "a@example.com", "send": True})
    assert routed["recipient"] == "a@example.com"
    assert routed["send"] is True
