"""/api/fn route policy: agent-probe values never stand in for a caller choice.

The agent profile probes functions cheaply (limit 6, days 120, range 3M, the
symbol's peer group, a news query, a 3 s fetch budget). Routed through
/api/fn those values overrode each function's own defaults: GMM cut to six
countries, SECF showed 6 of 81 matches, READ was filtered to crypto peers,
FXH ran 120 days, PCAS dropped positions, ICX never read a sector. The route
now keeps only per-code values and what the caller sends, and reports what it
filled in as routeDefaults instead of echoing it as the caller's input.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.function_contracts import normalize_function_contract
from showme.server import unavailable_function_data
from showme.server_routes._agent_runtime import (
    _PROBE_ONLY_KEYS,
    _PROBE_TIMEOUT_KEYS,
    _agent_function_params,
    _function_entry_for_code,
    _route_function_params,
)


def _route(code: str, **params):
    return _route_function_params(code, dict(params))


@pytest.mark.parametrize("code", ["SECF", "GMM", "BQL", "FXH", "PCAS", "READ", "CORR", "HVT"])
def test_probe_window_size_text_and_peer_keys_are_not_injected(code: str) -> None:
    routed = _route(code)
    for key in _PROBE_ONLY_KEYS:
        if key in ("query",) and code in {"BQL", "SECF"}:
            continue  # per-code values (BQL builds a query from the symbol, SECF a search term)
        assert key not in routed, f"{code}: probe {key}={routed.get(key)!r} injected"


def test_caller_values_still_win() -> None:
    routed = _route("SECF", query="apple", limit=40)
    assert routed["query"] == "apple"
    assert routed["limit"] == 40
    assert "query" not in routed["__route_defaults"]
    assert "limit" not in routed["__route_defaults"]


def test_gmm_and_pcas_keep_their_own_fetch_budget() -> None:
    for code in ("GMM", "PCAS"):
        routed = _route(code)
        for key in _PROBE_TIMEOUT_KEYS:
            assert key not in routed, f"{code}: probe {key} injected"
    # Other functions keep the bounded probe budget unless the caller sends one.
    assert _route("HVT")["timeout"] == 3
    assert _route("HVT", timeout=9)["timeout"] == 9


def test_read_gets_no_peer_filter_query_or_limit() -> None:
    routed = _route("READ")
    assert "symbols" not in routed
    assert "query" not in routed
    assert "limit" not in routed


def test_bql_universe_falls_back_to_the_instrument_not_a_peer_list() -> None:
    routed = _route("BQL", symbol="AAPL", query="get(close) with(period=1mo) by(date)")
    assert "symbols" not in routed
    assert routed["symbol"] == "AAPL"


def test_reference_request_is_not_overruled_by_probe_live() -> None:
    routed = _route("CSRC", reference=True)
    assert "live" not in routed
    assert _route("CSRC")["live"] is True
    assert _route("CSRC", reference=True, live=True)["live"] is True


def test_icx_sector_is_reachable() -> None:
    routed = _route("ICX", sector="Energy")
    assert "index" not in routed
    assert routed["sector"] == "Energy"
    assert _route("ICX", index="NDX")["index"] == "NDX"
    # No routed index default: the handler picks index vs sector from its inputs.
    assert "index" not in _route("ICX")


def test_icx_handler_reads_a_sector_and_an_index_code_query() -> None:
    from showme.engine.functions.screen.icx import ICXFunction

    fn = ICXFunction()
    sector = asyncio.run(fn.execute(sector="Energy", quotes=False))
    assert sector.data["summary"]["sector"] == "Energy"
    assert "index" not in sector.data or not sector.data.get("index")
    by_query = asyncio.run(fn.execute(query="NDX", quotes=False))
    assert str(by_query.data.get("index", "")).upper() == "NDX"
    sector_query = asyncio.run(fn.execute(query="Energy", quotes=False))
    assert sector_query.data["summary"]["sector"] == "Energy"


def test_per_code_values_that_bound_cost_survive() -> None:
    # BMTX#5 sends an explicit bounded window on purpose.
    assert _route("BMTX")["days"] == 120
    # SAT derives its date window from the per-code days.
    sat = _route("SAT")
    assert sat["date_from"] and sat["date_to"]


def test_removed_per_code_defaults() -> None:
    assert "wacc_range" not in _route("DCFS") and "g_range" not in _route("DCFS")
    assert "growth_rate" not in _route("DDM")
    assert "universe" not in _route("FSRC")
    btfw = _route("BTFW")
    assert "days" not in btfw
    assert btfw["strategy"] == "sma_crossover"


def test_awareness_codes_get_only_caller_inputs() -> None:
    # The Awareness news/calendar functions adopted this policy (no legacy exemption):
    # neither the generic probe values nor their per-code probe query/limit reach them.
    for code in ("NI", "TOP", "CN", "ECO", "TRDH"):
        routed = _route(code)
        for key in ("limit", "query", "topic", "days", "range", "interval", "symbols"):
            assert key not in routed, (code, key, routed.get(key))
    routed = _route("NI", topic="FED", limit=5)
    assert routed["topic"] == "FED" and routed["limit"] == 5


def test_agent_probe_profile_is_unchanged_for_the_agent() -> None:
    entry = _function_entry_for_code("GMM")
    params = _agent_function_params(entry, {"symbol": "AAPL", "asset_class": "EQUITY"})
    assert params["limit"] == 6 and params["days"] == 120 and params["timeout"] == 3


def test_route_defaults_are_listed_and_not_echoed() -> None:
    routed = _route("FTS", symbol="AAPL")
    assert "query" in routed["__route_defaults"]
    assert "symbol" not in routed["__route_defaults"]
    payload = normalize_function_contract("FTS", routed, {"data": {"rows": []}, "sources": []})
    assert "query" not in payload["inputEcho"]
    assert payload["routeDefaults"]["query"] == routed["query"]
    assert payload["inputEcho"]["symbol"] == "AAPL"


def test_caller_inputs_are_echoed_without_route_defaults() -> None:
    routed = _route("SECF", query="apple")
    payload = normalize_function_contract("SECF", routed, {"data": {"rows": []}, "sources": []})
    assert payload["inputEcho"]["query"] == "apple"
    assert "limit" not in payload["inputEcho"]
    assert "days" not in payload["inputEcho"]


def test_fallback_requested_echo_excludes_route_defaults() -> None:
    routed = _route("ISIN", isins="US0378331005")
    data = unavailable_function_data("ISIN", routed, reason="function timed out after 14s")
    requested = data["requested"]
    for key in ("query", "limit", "range", "days"):
        if key in routed.get("__route_defaults", []):
            assert key not in requested, f"route default {key} echoed as requested"


def test_ovme_reports_an_assumed_contract_type() -> None:
    from showme.engine.functions.derivative.ovme import OVMEFunction

    routed = _route("OVME", spot=100, strike=100, years_to_expiry=0.5, vol=0.2)
    assert routed["type"] == "CALL" and "type" in routed["__route_defaults"]
    params = {k: v for k, v in routed.items() if k not in ("symbol", "asset_class")}
    result = asyncio.run(OVMEFunction().execute(**params))
    assert result.data["type_source"] == "default"
    assert "type=CALL" in result.data["assumed_defaults"]
    assert any("assumed" in w and "type=CALL" in w for w in result.warnings)
    explicit = asyncio.run(OVMEFunction().execute(spot=100, strike=100, years_to_expiry=0.5, vol=0.2,
                                                  type="PUT", rate=0.04, div_yield=0.01))
    assert explicit.data["type_source"] == "input"
    assert explicit.data["assumed_defaults"] == []
