"""ALRT echoes only the parameters the caller sent (ALRT#6).

Regression: the router merged the generic agent defaults (default news query,
peer symbols, limit, days, range) into ALRT's routed params, so the envelope
inputEcho showed values the ALRT handler never reads (e.g. query
'bitcoin cryptocurrency' next to a caller's condition 'AAPL.price > 200').
"""

from __future__ import annotations

from showme import server


def test_alrt_routed_params_carry_only_caller_inputs() -> None:
    routed = server._route_function_params(
        "ALRT", {"condition": "AAPL.price > 200", "cooldown": "abc"}
    )
    visible = {k: v for k, v in routed.items() if not k.startswith("__")}
    assert visible == {"condition": "AAPL.price > 200", "cooldown": "abc"}


def test_alrt_routed_params_drop_generic_agent_defaults() -> None:
    routed = server._route_function_params("ALRT", {"condition": "AAPL.price > 200"})
    for key in ("query", "symbols", "limit", "days", "range", "topic", "interval", "timeout"):
        assert key not in routed, f"ALRT must not receive the generic default {key!r}"


def test_alrt_keeps_structured_inputs_the_caller_sent() -> None:
    routed = server._route_function_params(
        "ALRT", {"symbol": "AAPL", "field": "price", "direction": "above", "threshold": 200}
    )
    assert routed["symbol"] == "AAPL"
    assert routed["threshold"] == 200
    assert "symbols" not in routed
