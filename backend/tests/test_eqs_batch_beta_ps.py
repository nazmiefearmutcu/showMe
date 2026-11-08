"""EQS#2 follow-up: beta and P/S come from the batch quote record when it carries them.

The batch adapter stores the full raw Yahoo v7 record per symbol, and the
screener already reads ``beta`` from it as a fallback. P/S was read only from
the REFDATA cache, so a symbol whose REFDATA call was cancelled lost a value the
batch record may already hold. The fallback must follow the same rule as beta:
REFDATA first, then the batch record, and never an invented value when neither
carries it. Industry is not in the batch record and stays REFDATA-only.
No network: the batch and REFDATA providers are in-test fakes.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.equity import eqs as eqs_mod

_UNIVERSE = ["BAT1", "BAT2", "BAT3"]


@pytest.fixture(autouse=True)
def _isolate_module_state(monkeypatch):
    eqs_mod._EQS_BATCH_CACHE.clear()
    eqs_mod._EQS_REFDATA_CACHE.clear()
    eqs_mod._SECURITY_MASTER_INDEX = None
    monkeypatch.setattr(eqs_mod, "_EQS_REFDATA_CURSOR", 0)
    monkeypatch.setattr(eqs_mod, "_EQS_REFDATA_ATTEMPTED", {}, raising=False)
    yield
    eqs_mod._EQS_BATCH_CACHE.clear()
    eqs_mod._EQS_REFDATA_CACHE.clear()


class _BatchWithBetaPs:
    """Batch record carries beta and P/S; REFDATA always fails (no cached value)."""

    def __init__(self, record: dict) -> None:
        self._record = record

    async def fetch_refdata_batch(self, symbols, **_kwargs):
        return {str(s).upper(): dict(self._record) for s in symbols}

    async def fetch(self, request):
        raise RuntimeError("refdata unavailable")


def _scan(provider, universe=_UNIVERSE):
    fn = eqs_mod.EQSFunction(deps=FunctionDeps(yfinance=provider))
    return asyncio.run(fn.execute(
        instrument=None,
        query="marketCap > 0",
        live_screen=True,
        universe=list(universe),
        refdata_screen_timeout=1.0,
    ))


def test_batch_record_supplies_beta_and_ps_when_refdata_is_missing() -> None:
    provider = _BatchWithBetaPs({
        "marketCap": 1.0e9, "trailingPE": 12.0, "priceToBook": 1.5,
        "dividendYield": 1.0, "beta": 1.2, "priceToSalesTrailing12Months": 3.4,
    })
    result = _scan(provider)
    rows = result.data.to_dict(orient="records")
    assert len(rows) == len(_UNIVERSE)
    for row in rows:
        assert row["beta"] == pytest.approx(1.2)
        assert row["ps"] == pytest.approx(3.4)
    coverage = result.metadata["enrichment_coverage"]
    assert coverage["beta"] == {"populated": len(_UNIVERSE), "of": len(_UNIVERSE)}
    assert coverage["ps"] == {"populated": len(_UNIVERSE), "of": len(_UNIVERSE)}


def test_absent_batch_fields_stay_null_and_are_reported() -> None:
    """No value is invented when the batch record carries neither field."""
    provider = _BatchWithBetaPs({
        "marketCap": 1.0e9, "trailingPE": 12.0, "priceToBook": 1.5, "dividendYield": 1.0,
    })
    result = _scan(provider)
    for row in result.data.to_dict(orient="records"):
        assert row.get("beta") is None
        assert row.get("ps") is None
    coverage = result.metadata["enrichment_coverage"]
    assert coverage["ps"]["populated"] == 0
    assert any(w.startswith("ps is empty for") for w in result.warnings)


def test_refdata_value_wins_over_batch_value_for_ps() -> None:
    """REFDATA stays the first source for P/S, as it already is for beta."""
    provider = _BatchWithBetaPs({
        "marketCap": 1.0e9, "trailingPE": 12.0, "priceToBook": 1.5,
        "dividendYield": 1.0, "beta": 1.2, "priceToSalesTrailing12Months": 3.4,
    })
    eqs_mod._refdata_cache_write("BAT1", {"ps": 2.0, "beta": 0.9})
    result = _scan(provider)
    by_symbol = {row["symbol"]: row for row in result.data.to_dict(orient="records")}
    assert by_symbol["BAT1"]["ps"] == pytest.approx(2.0)
    assert by_symbol["BAT1"]["beta"] == pytest.approx(0.9)
    assert by_symbol["BAT2"]["ps"] == pytest.approx(3.4)
