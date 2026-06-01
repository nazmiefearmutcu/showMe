"""De-garbage test for WIRP — World Interest Rate Probability.

WIRP previously returned a hardcoded reference probability table (the
``_probability_rows`` constants such as 0.18/0.72/0.10 for FED) because the
``cme_fedwatch`` adapter was never wired. It now computes Fed cut/hold/hike
probabilities from genuinely live, keyless market data:

* current target range  → FRED DFEDTARU / DFEDTARL CSV
* effective funds rate   → FRED DFF CSV
* implied near-term rate → 13-week T-bill (^IRX) via yfinance

These tests assert the live happy path when the network is available and fall
back cleanly to the honest provider_unavailable shape when it is not. The pure
CME-FedWatch bucket math is also exercised deterministically (offline-safe).
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.macro.wirp import (
    WIRPFunction,
    _bucket_probabilities,
    _live_fed_rows,
)

# The old hardcoded reference table that we must NOT regress to.
_OLD_CONSTANTS = {
    (0.18, 0.72, 0.10),
    (0.28, 0.62, 0.10),
    (0.36, 0.55, 0.09),
    (0.42, 0.50, 0.08),
    (0.45, 0.48, 0.07),
}

_OK_SET = {"ok", "empty", "provider_unavailable"}


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Pure bucket math — deterministic, offline-safe
# --------------------------------------------------------------------------- #
def test_bucket_probabilities_sum_to_one_and_lean_correctly():
    # A clear cut is priced (move well below -12.5 bp).
    cut, hold, hike = _bucket_probabilities(move_bp=-40.0, sigma_bp=12.5)
    assert abs(cut + hold + hike - 1.0) < 1e-9
    assert cut > hold > hike
    # A clear hike.
    cut, hold, hike = _bucket_probabilities(move_bp=40.0, sigma_bp=12.5)
    assert abs(cut + hold + hike - 1.0) < 1e-9
    assert hike > hold > cut
    # No move → hold dominates and is symmetric.
    cut, hold, hike = _bucket_probabilities(move_bp=0.0, sigma_bp=12.5)
    assert abs(cut + hold + hike - 1.0) < 1e-9
    assert hold > cut and hold > hike
    assert abs(cut - hike) < 1e-9


def test_live_fed_rows_are_derived_not_constants():
    rows = _live_fed_rows(target_mid=4.50, implied_rate=4.05, meetings_limit=4)
    assert rows, "expected forward meeting rows"
    for row in rows:
        triple = (
            round(row["cut_25bp"], 2),
            round(row["hold"], 2),
            round(row["hike_25bp"], 2),
        )
        assert triple not in _OLD_CONSTANTS, "must not regress to the old table"
        total = row["cut_25bp"] + row["hold"] + row["hike_25bp"]
        assert abs(total - 1.0) < 1e-6
        assert row["source_mode"] == "live_fed_funds_futures"
        expected = round((-25 * row["cut_25bp"]) + (25 * row["hike_25bp"]), 2)
        assert row["implied_change_bp"] == expected
    # Implied rate below target ⇒ a cut is priced for the near meeting.
    assert rows[0]["cut_25bp"] > rows[0]["hike_25bp"]


# --------------------------------------------------------------------------- #
# Live integration — network-guarded
# --------------------------------------------------------------------------- #
def test_wirp_fed_live_or_graceful():
    fn = WIRPFunction(FunctionDeps())
    result = _run(fn.execute(central_bank="FED", meetings=4))
    data = result.data

    assert data["status"] in _OK_SET
    assert data["methodology"]
    assert "field_dictionary" in data
    # Never the old canned-table source mode.
    assert data["source_mode"] != "reference_rate_probability_table"
    assert "reference_rate_probability_table" not in result.sources

    if data["status"] == "ok":
        # Live path: real, non-constant rows from fred + yfinance.
        assert data["data_mode"] == "live_official"
        assert "fred" in result.sources and "yfinance" in result.sources
        rows = data["rows"]
        assert rows
        for row in rows:
            triple = (
                round(row["cut_25bp"], 2),
                round(row["hold"], 2),
                round(row["hike_25bp"], 2),
            )
            assert triple not in _OLD_CONSTANTS
            total = row["cut_25bp"] + row["hold"] + row["hike_25bp"]
            assert abs(total - 1.0) < 1e-6
        # The live anchor must expose the market inputs that drove the result.
        anchor = data["anchor"]
        assert anchor.get("implied_near_term_rate") is not None
        assert anchor.get("current_target_mid") is not None
    else:
        # Offline: honest provider_unavailable, no synthetic probabilities.
        assert data["data_mode"] == "provider_unavailable"
        assert data["rows"] == []
        assert any(
            "unavailable" in w.lower() or "no usable" in w.lower()
            for w in result.warnings
        )


def test_wirp_non_fed_is_honestly_unavailable():
    fn = WIRPFunction(FunctionDeps())
    result = _run(fn.execute(central_bank="ECB", meetings=4))
    # No keyless implied-rate source for ECB ⇒ honest provider_unavailable,
    # never the old canned ECB table (0.22/0.68/0.10 ...).
    assert result.data["status"] == "provider_unavailable"
    assert result.data["data_mode"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.warnings


def test_wirp_offline_branch_is_graceful(monkeypatch):
    """Simulate a *total* network outage on the live path; assert no fabricated rows.

    The live path is now resilient: a FRED target range alone (or an ^IRX
    implied rate alone) is enough to build honest rows, and only a genuine
    outage of BOTH the FRED target range AND the implied near-term rate
    downgrades to provider_unavailable. So this test downs both legs to
    exercise the true total-outage branch.
    """
    import showme.engine.functions.macro.wirp as wirp_mod

    async def _boom(*_a, **_k):
        raise OSError("simulated network down")

    async def _irx_down(*_a, **_k):
        return None, None

    monkeypatch.setattr(wirp_mod, "_fetch_fred_latest", _boom)
    monkeypatch.setattr(wirp_mod, "_fetch_irx_implied_rate", _irx_down)
    fn = WIRPFunction(FunctionDeps())  # no cme_fedwatch adapter
    result = _run(fn.execute(central_bank="FED", meetings=4))

    assert result.data["status"] == "provider_unavailable"
    assert result.data["data_mode"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert "reference_rate_probability_table" not in result.sources
    assert any("unavailable" in w.lower() for w in result.warnings)
