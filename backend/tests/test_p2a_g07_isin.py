"""P2A-G07 regression tests: ISIN (#4, #5, #6, #8).

All network access is patched: OpenFIGI and yfinance are fakes, and the
portfolio book is replaced with an in-memory fake. No sidecar, no port.
"""
from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.api import isin as isin_mod
from showme.manifest import REGISTRY, load_seeds


class _FakeOpenFIGI:
    def __init__(self, rows_per_call=None):
        self.calls: list[tuple[str, str]] = []
        self._rows = rows_per_call

    async def lookup_by(self, id_type, id_value):
        self.calls.append((id_type, id_value))
        if self._rows is not None:
            return list(self._rows)
        return []

    async def lookup_batch(self, jobs, *, max_wait_seconds):
        # ISIN batches identifiers into one OpenFIGI mapping request (ISIN#1).
        out = []
        for id_type, id_value in jobs:
            self.calls.append((id_type, id_value))
            out.append({"data": list(self._rows) if self._rows is not None else [], "warning": None})
        return out


def _figi_rows(count: int) -> list[dict]:
    return [
        {
            "figi": f"BBG{i:09d}",
            "ticker": "AAPL",
            "name": "APPLE INC",
            "marketSector": "Equity",
            "securityType": "Common Stock",
            "securityType2": "Common Stock",
            "exchCode": f"X{i}",
            "compositeFIGI": "BBG000B9XRY4",
            "shareClassFIGI": "BBG001S5N8V8",
        }
        for i in range(count)
    ]


def _isin_fn(openfigi):
    return isin_mod.ISINFunction(FunctionDeps(openfigi=openfigi))


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- ISIN #4


def test_isin_limit_caps_rows_and_summary_counts_every_exchange_match():
    fake = _FakeOpenFIGI(rows_per_call=_figi_rows(303))
    res = _run(_isin_fn(fake).execute(ids="US0378331005", limit=6))
    d = res.data
    group_matches = d["match_groups"][0]["matches"]
    # The pane counts match_groups (exchange-level, unsliced); the summary must agree.
    assert len(group_matches) == 303
    assert d["summary"]["matches"] == 303
    # The flat rows honour the per-input limit.
    assert len(d["rows"]) == 6
    assert d["summary"]["limit_per_input"] == 6


# ---------------------------------------------------------------- ISIN #5


def test_isin_forced_id_type_reaches_openfigi():
    fake = _FakeOpenFIGI(rows_per_call=_figi_rows(1))
    _run(_isin_fn(fake).execute(ids="037833100", id_type="ID_CUSIP"))
    assert fake.calls == [("ID_CUSIP", "037833100")]


def test_isin_seed_declares_only_inputs_the_handler_reads():
    load_seeds()
    names = {i.name for i in REGISTRY.get("ISIN").inputs}
    # provider_mode was declared but never read by the handler.
    assert "provider_mode" not in names
    assert {"ids", "id_type", "limit"} <= names


# ---------------------------------------------------------------- ISIN #6


def test_isin_bad_check_digit_is_reported_not_silently_ticker_queried():
    fake = _FakeOpenFIGI(rows_per_call=[])
    res = _run(_isin_fn(fake).execute(ids="US0378331006"))
    d = res.data
    assert d["status"] == "input_error"  # only invalid input, nothing to look up (merged with ISIN#1)
    # A malformed ISIN must not be sent to OpenFIGI as a TICKER.
    assert fake.calls == []
    group = d["match_groups"][0]
    assert group["id_type"] == "TICKER"
    assert "check digit" in (group.get("error") or "").lower()
    assert any("check digit" in w.lower() for w in res.warnings)


def test_isin_valid_isin_still_resolves_without_warning():
    fake = _FakeOpenFIGI(rows_per_call=_figi_rows(2))
    res = _run(_isin_fn(fake).execute(ids="US0378331005"))
    assert fake.calls == [("ID_ISIN", "US0378331005")]
    assert res.data["match_groups"][0]["id_type"] == "ID_ISIN"
    assert not any("check digit" in w.lower() for w in res.warnings)


# ---------------------------------------------------------------- ISIN #8


def test_isin_output_keys_match_the_seed_contract():
    load_seeds()
    spec = REGISTRY.get("ISIN")
    fake = _FakeOpenFIGI(rows_per_call=_figi_rows(2))
    res = _run(_isin_fn(fake).execute(ids="US0378331005"))
    d = res.data
    # Card slots read these top-level keys.
    for key in ("inputs_resolved", "inputs_failed", "data_mode", "as_of"):
        assert key in d, key
    assert d["data_mode"] == "live_official"
    assert d["inputs_resolved"] == 1 and d["inputs_failed"] == 0
    # Table columns read these row keys.
    row_keys = set(d["rows"][0].keys())
    for col in spec.table_schema.columns:
        assert col.key in row_keys, col.key


def test_isin_provider_unavailable_declares_its_data_mode(monkeypatch):
    res = _run(isin_mod.ISINFunction(FunctionDeps(openfigi=None)).execute(ids="AAPL"))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["data_mode"] in {"not_configured", "provider_unavailable"}


