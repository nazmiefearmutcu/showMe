"""COUN must not invent reference values for an unknown country (G5 review).

``_country_profile_model`` used to return a generic reference profile (policy
rate 4%, inflation 3%, unemployment 6%, ...) for any country without a curated
profile. Those numbers were labelled ``country_reference_profile`` with only a
warning, so the Country Guide still showed invented figures as rows and cards.
The data policy forbids placeholder values for an unknown instrument. An
unknown country now returns no reference rows or cards and an explicit
``needs_input`` state with a reason. Curated countries keep their labelled
reference rows. The seed methodology must name the verified TR GDP id. All
providers are patched; no network is used.
"""

from __future__ import annotations

import asyncio

import showme.engine.functions.macro.coun as coun_mod
import showme.engine.functions.macro.ecst as ecst_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.macro.coun import COUNFunction
from showme.manifest.seeds.coun_seed import coun


def _run(coro):
    return asyncio.run(coro)


class _BtmmDown:
    def __init__(self, deps) -> None:
        self.deps = deps

    async def execute(self, **kwargs):
        raise RuntimeError("btmm offline (test)")


class _NoFred:
    async def series(self, sid, *args, **kwargs):
        raise RuntimeError(f"keyless FRED CSV unavailable for {sid!r}")

    async def info(self, sid):
        raise RuntimeError("info unavailable (test)")


def _patch_offline(monkeypatch) -> None:
    monkeypatch.setattr(coun_mod, "BTMMFunction", _BtmmDown)
    monkeypatch.setattr(
        ecst_mod,
        "fred_with_keyless_fallback",
        lambda deps_fred, client=None: _NoFred(),
    )


def test_unknown_country_serves_no_reference_numbers_offline(monkeypatch):
    _patch_offline(monkeypatch)
    result = _run(COUNFunction(FunctionDeps()).execute(country="ZZ"))

    data = result.data
    assert data["rows"] == [], "an unknown country must not get invented profile rows"
    assert data["cards"] == [], "an unknown country must not get invented cards"
    assert data["status"] == "needs_input"
    assert "ZZ" in data["reason"]
    assert data["next_actions"], "the honest state must name a next step"
    assert "country_reference_profile" not in result.sources
    assert result.metadata.get("country_known") is False


def test_unknown_country_live_serves_no_reference_numbers(monkeypatch):
    _patch_offline(monkeypatch)
    result = _run(
        COUNFunction(FunctionDeps()).execute(country="ZZ", live_macro=True)
    )

    data = result.data
    assert data["rows"] == []
    assert data["cards"] == []
    assert data["source_mode"] == "reference_country_profile"
    assert "country_reference_profile" not in result.sources


def test_curated_country_keeps_labelled_reference_rows(monkeypatch):
    _patch_offline(monkeypatch)
    result = _run(COUNFunction(FunctionDeps()).execute(country="US"))

    data = result.data
    assert data["rows"], "a curated country keeps its reference profile"
    assert all(row["source_mode"] == "country_reference_profile" for row in data["rows"])
    assert result.metadata.get("country_known") is True


def test_seed_methodology_names_verified_tr_gdp_series_only():
    methodology = coun.methodology
    assert "TURGDPRQDSMEI" not in methodology, "that id is HTTP 404 on FRED"
    assert "NGDPRSAXDCTRQ" in methodology
    assert "generic fallback" not in methodology, "unknown countries serve no reference values"
