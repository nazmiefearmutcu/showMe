"""TLH#5 regressions: the manifest and the handler agree. A declared input that
the handler says it ignores is not marked required, and every card slot the
manifest declares resolves to a key the handler really emits.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from showme.engine.functions.portfolio import tlh
from showme.manifest.seeds import tlh_seed
from test_tlh_real_portfolio import _book, _deps, _pos


def _run(fn, **params):
    return asyncio.run(fn.execute(**params))


def test_credential_id_is_not_declared_required():
    spec = next(s for s in tlh_seed.tlh.inputs if s.name == "credential_id")
    assert spec.required is False
    assert "local" in spec.description.lower()


def test_every_card_slot_resolves_to_an_emitted_key(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 400), _pos("MSFT", 5, 500.0, 30)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 150.0, "MSFT": 400.0})))
    missing = [slot.key for slot in tlh_seed.tlh.card_schema.slots if slot.key not in res.data]
    assert missing == []


def test_card_kpis_carry_the_values_they_name(monkeypatch):
    # MSFT is held 45 days: outside the 30-day window, so it is not blocked and is short-term.
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 400), _pos("MSFT", 5, 500.0, 45)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 150.0, "MSFT": 400.0})))
    assert res.data["candidate_count"] == 2
    assert res.data["lt_loss"] == 500.0   # AAPL, held 400 days
    assert res.data["st_loss"] == 500.0   # MSFT, held 30 days
    assert res.data["wash_blocked_count"] == 0


def test_partial_book_keeps_the_st_lt_split_honest(monkeypatch):
    # MSFT is blocked (opened 10 days ago, inside the window): it stays out of
    # the ST/LT split and is counted once as wash-blocked.
    _book(monkeypatch, [
        _pos("AAPL", 10, 200.0, 400),
        _pos("MSFT", 5, 500.0, 10),
    ])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 150.0, "MSFT": 400.0})))
    assert res.data["lt_loss"] == 500.0
    assert res.data["st_loss"] == 0
    assert res.data["wash_blocked_count"] == 1
    assert res.data["candidate_count"] == 2
