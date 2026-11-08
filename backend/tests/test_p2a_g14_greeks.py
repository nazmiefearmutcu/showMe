"""P2A G14 — GREEKS reports every default it applies and describes the shipped handler.

GREEKS#2: a missing contract multiplier silently became 100 with no
assumption, and the row showed contract_size as None.
GREEKS#3: a missing dividend yield silently became 0 with no assumption, and
the methodology did not state that the model is European closed-form.
GREEKS#4: the seed methodology and semantic tests still described defaults
(vol=0.30, T=30d) that the handler no longer applies.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from showme.engine.functions.portfolio.greeks import GREEKSFunction
from showme.engine.functions.portfolio.greeks import _methodology as handler_methodology
from showme.engine.services import greeks as svc
from showme.manifest import REGISTRY, load_seeds


class _Deps:
    yfinance = None
    fred = None


def _run(**params):
    return asyncio.run(GREEKSFunction(_Deps()).execute(**params))


def _entry():
    load_seeds()
    return REGISTRY.get("GREEKS")


# ---- GREEKS#2: contract multiplier default is reported -------------------

def test_missing_contract_size_is_reported_as_default_100() -> None:
    g = svc.position_greeks({"kind": "call", "spot": 100, "strike": 100,
                             "vol": 0.2, "T": 0.5, "quantity": 1})
    assert g["contract_size"] == 100
    assert g["contract_size_source"] == "default_100"
    assert any("contract_size=default 100" in a for a in g["assumptions_used"])


def test_supplied_contract_size_and_dividend_yield_are_not_reported_as_defaults() -> None:
    g = svc.position_greeks({"kind": "call", "spot": 100, "strike": 100, "vol": 0.2,
                             "T": 0.5, "quantity": 1, "contract_size": 100, "q": 0.01})
    assert g["contract_size_source"] == "input"
    assert g["q_source"] == "input"
    assert "assumptions_used" not in g


def test_handler_row_shows_the_multiplier_it_applied() -> None:
    expiry = (date.today() + timedelta(days=182)).isoformat()
    res = _run(positions=[{"symbol": "AAPL", "kind": "call", "quantity": 10,
                           "spot": 250.0, "strike": 240.0, "expiry": expiry,
                           "vol": 0.25, "rate": 0.04}])
    row = res.data["positions"][0]
    assert row["contract_size"] == 100
    assert row["contract_size_source"] == "default_100"
    assert any("contract_size=default 100" in a for a in res.data["assumptions_used"])


# ---- GREEKS#3: dividend yield default is reported; model is labelled European

def test_missing_dividend_yield_is_reported_as_default_zero() -> None:
    g = svc.position_greeks({"kind": "put", "spot": 100, "strike": 95, "vol": 0.2,
                             "T": 0.5, "quantity": 1, "contract_size": 100})
    assert g["q"] == 0.0
    assert g["q_source"] == "default_0"
    assert any("q=default 0" in a for a in g["assumptions_used"])


def test_methodology_states_european_exercise() -> None:
    assert "European" in handler_methodology()


# ---- GREEKS#4: seed text and semantic tests match the shipped handler ----

def test_seed_methodology_does_not_describe_removed_defaults() -> None:
    text = _entry().methodology
    assert "vol=0.30" not in text
    assert "T=30d" not in text
    assert "European" in text
    assert "expiry" in text.lower()


def test_seed_semantic_tests_match_current_handler() -> None:
    names = {t.name for t in _entry().semantic_tests}
    assert "greeks_missing_vol_and_T_reported_in_assumptions_used" not in names
    assert "greeks_missing_expiry_is_input_error" in names
    assert "greeks_missing_multiplier_and_dividend_reported" in names


def test_handler_refuses_missing_expiry_as_the_seed_now_states() -> None:
    res = _run(positions=[{"kind": "put", "spot": 100, "strike": 95, "quantity": 1,
                           "vol": 0.3, "rate": 0.04}])
    assert res.data["status"] == "input_error"
    assert "expiry" in res.data["reason"]
