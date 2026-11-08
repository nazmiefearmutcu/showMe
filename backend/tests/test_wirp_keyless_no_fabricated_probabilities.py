"""WIRP — the keyless path must not turn a T-bill basis into hike/cut odds.

With no CME FedWatch adapter, the only keyless inputs are the FRED target
range, EFFR and the 13-week T-bill yield (^IRX). A T-bill yield minus the
policy target is a bill basis, not a market policy-rate expectation, so the
handler must not derive a hike/cut distribution from it, must not label the
result as fed funds futures, and must report provider_unavailable with the
real anchor values it did obtain.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
import showme.engine.functions.macro.wirp as wirp_mod


def _patch_live_legs(monkeypatch, *, irx=4.30):
    async def _fake_fred(url, timeout=8.0):
        if "DFEDTARU" in url:
            return ("2026-09-10", 4.50)
        if "DFEDTARL" in url:
            return ("2026-09-10", 4.25)
        return ("2026-09-10", 4.33)

    async def _fake_irx():
        return irx, "2026-09-10"

    monkeypatch.setattr(wirp_mod, "_fetch_fred_latest", _fake_fred)
    monkeypatch.setattr(wirp_mod, "_fetch_irx_implied_rate", _fake_irx)


def _run_fed(meetings=4):
    return asyncio.run(
        wirp_mod.WIRPFunction(FunctionDeps()).execute(central_bank="FED", meetings=meetings)
    )


def test_keyless_tbill_basis_yields_no_hike_cut_rows(monkeypatch):
    _patch_live_legs(monkeypatch, irx=4.30)
    result = _run_fed()
    data = result.data

    assert data["status"] == "provider_unavailable"
    assert data["data_mode"] == "provider_unavailable"
    assert data["rows"] == []
    assert data["source_mode"] == "provider_unavailable"
    assert "live_fed_funds_futures" not in str(data)
    assert "live_official" != data["data_mode"]
    assert any("futures" in w.lower() for w in result.warnings)


def test_keyless_anchor_reports_tbill_as_basis_not_policy_rate(monkeypatch):
    _patch_live_legs(monkeypatch, irx=4.30)
    anchor = _run_fed().data["anchor"]

    assert anchor["current_target_mid"] == 4.375
    assert anchor["current_target_upper"] == 4.5
    assert anchor["current_target_lower"] == 4.25
    assert anchor["effr"] == 4.33
    assert anchor["tbill_13w_pct"] == 4.3
    assert anchor["tbill_minus_target_mid_bp"] == -7.5
    # The old key implied a policy-rate expectation; it must be gone.
    assert "implied_near_term_rate" not in anchor
    assert "not a market policy-rate expectation" in anchor["basis_note"].lower()


def test_keyless_tbill_without_target_does_not_stand_in_for_target(monkeypatch):
    async def _no_fred(url, timeout=8.0):
        raise OSError("fred down")

    async def _irx():
        return 4.30, "2026-09-10"

    monkeypatch.setattr(wirp_mod, "_fetch_fred_latest", _no_fred)
    monkeypatch.setattr(wirp_mod, "_fetch_irx_implied_rate", _irx)
    data = _run_fed().data

    assert data["status"] == "provider_unavailable"
    assert data["anchor"].get("current_target_mid") is None
    assert data["rows"] == []


def test_cme_adapter_still_produces_probabilities(monkeypatch):
    class _Cme:
        async def probabilities(self):
            return {
                "meetings": [
                    {"date": "2026-06-17", "ranges": {"4.25-4.50": 80.0, "4.00-4.25": 20.0}},
                ]
            }

    deps = FunctionDeps()
    deps.cme_fedwatch = _Cme()
    result = asyncio.run(wirp_mod.WIRPFunction(deps=deps).execute(central_bank="FED", meetings=2))
    assert result.data["status"] == "ok"
    assert result.data["source_mode"] == "cme_fedwatch"
    assert result.data["rows"]
