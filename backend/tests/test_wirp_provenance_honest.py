"""WIRP — provenance and warning wording on the keyless path must be honest.

* When every keyless leg fails, no source contributed, so ``sources`` must be
  empty rather than a status label (``provider_unavailable``) posing as a source.
* The warning must not assert an unverified claim about CME FedWatch access
  (no key requirement is verified in this repository); it states only what is
  wired here.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
import showme.engine.functions.macro.wirp as wirp_mod


def _run_fed(meetings=4):
    return asyncio.run(
        wirp_mod.WIRPFunction(FunctionDeps()).execute(central_bank="FED", meetings=meetings)
    )


def test_keyless_total_outage_lists_no_source(monkeypatch):
    async def _boom(url, timeout=8.0):
        raise OSError("fred down")

    async def _irx_down():
        return None, None

    monkeypatch.setattr(wirp_mod, "_fetch_fred_latest", _boom)
    monkeypatch.setattr(wirp_mod, "_fetch_irx_implied_rate", _irx_down)
    result = _run_fed()

    assert result.data["status"] == "provider_unavailable"
    assert result.sources == []
    assert result.data["provenance"] == {"sources": []}


def test_unavailable_warning_does_not_assert_unverified_key_requirement(monkeypatch):
    async def _ok_fred(url, timeout=8.0):
        return ("2026-09-10", 4.50 if "DFEDTARU" in url else 4.25 if "DFEDTARL" in url else 4.33)

    async def _irx():
        return 4.30, "2026-09-10"

    monkeypatch.setattr(wirp_mod, "_fetch_fred_latest", _ok_fred)
    monkeypatch.setattr(wirp_mod, "_fetch_irx_implied_rate", _irx)
    result = _run_fed()

    texts = [w.lower() for w in result.warnings]
    assert any("futures" in t for t in texts)
    assert not any("need a key" in t for t in texts), result.warnings
