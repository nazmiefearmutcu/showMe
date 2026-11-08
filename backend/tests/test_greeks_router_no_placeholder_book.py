"""T10 GREEKS: the router must not price a demo option book.

With the network cut, ``GREEKS`` called with no positions came back ``ok`` with
``spot=100`` because ``_route_function_params`` injected a hard-coded position
(spot 100, strike 105, vol 0.35, rate 0.04). That number is not the caller's
and not the market's. The honest answer for an empty book is the handler's
``input_required`` state with no priced rows.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.greeks import GREEKSFunction
from showme.server_routes._agent_runtime import _route_function_params


class _Deps(FunctionDeps):
    yfinance = None


def test_router_does_not_inject_a_demo_option_position() -> None:
    routed = _route_function_params("GREEKS", {})
    assert not routed.get("positions"), routed.get("positions")


def test_empty_book_through_router_is_input_required_with_no_priced_rows() -> None:
    routed = _route_function_params("GREEKS", {})
    routed.pop("__explicit_symbol", None)
    res = asyncio.run(GREEKSFunction(_Deps()).execute(**routed))
    assert res.data["status"] == "input_required"
    assert res.data["positions"] == []
    assert "spot" not in str(res.data.get("positions"))
