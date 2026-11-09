"""P2A-G12 findings: TAUC / EREV / DDM / PCAS honesty and contract fixes.

All tests are offline: every provider is an injected fake.
"""
from __future__ import annotations

import asyncio
from typing import Any

import numpy as np

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument


# ─────────────────────────────────────────────────────────────────────────
# TAUC#3 — security_type filter must run before the row limit
# ─────────────────────────────────────────────────────────────────────────


class _AuctionsFake:
    """Mimics the adapter: honours ``limit`` by truncating the raw list."""

    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows
        self.limits_seen: list[Any] = []

    async def upcoming(self, *, horizon_days: int = 30, limit: int | None = None) -> list[dict[str, Any]]:
        self.limits_seen.append(limit)
        return self.rows if limit is None else self.rows[:limit]

    async def recent(self, *, days: int = 30, limit: int | None = None) -> list[dict[str, Any]]:
        self.limits_seen.append(limit)
        return self.rows if limit is None else self.rows[:limit]


_MIXED_ROWS = [
    {"security_type": "Bill", "term": "13-Week", "auction_date": "2026-11-10", "offering_amount": 70e9},
    {"security_type": "Bill", "term": "26-Week", "auction_date": "2026-11-10", "offering_amount": 75e9},
    {"security_type": "Note", "term": "2-Year", "auction_date": "2026-11-12", "offering_amount": 69e9},
    {"security_type": "Note", "term": "5-Year", "auction_date": "2026-11-13", "offering_amount": 70e9},
    {"security_type": "Bond", "term": "30-Year", "auction_date": "2026-11-15", "offering_amount": 25e9},
]


def test_tauc_security_filter_applied_before_limit() -> None:
    from showme.engine.functions.bond.tauc import TAUCFunction

    adapter = _AuctionsFake(_MIXED_ROWS)
    result = asyncio.run(
        TAUCFunction(FunctionDeps(treasury_auctions=adapter)).execute(
            security_type="Note", limit=2
        )
    )
    types = [row["security_type"] for row in result.data["rows"]]
    # Two Notes exist in the window, so a limit of 2 must return both.
    assert types == ["Note", "Note"]
    assert result.data["n"] == 2


def test_tauc_template_security_filter_applied_before_limit() -> None:
    from showme.engine.functions.bond.tauc import TAUCFunction

    result = asyncio.run(
        TAUCFunction(FunctionDeps()).execute(live_auctions=False, security_type="Bond", limit=1)
    )
    assert [row["security_type"] for row in result.data["rows"]] == ["Bond"]


# ─────────────────────────────────────────────────────────────────────────
# TAUC#4 — manifest default for live_auctions must match the handler
# ─────────────────────────────────────────────────────────────────────────


def _manifest(code: str):
    from showme.manifest.registry import REGISTRY
    from showme.manifest.seeds import load_seeds

    load_seeds()
    return REGISTRY.get(code)


def test_tauc_manifest_default_live_matches_handler() -> None:
    from showme.engine.functions.bond.tauc import TAUCFunction

    adapter = _AuctionsFake(_MIXED_ROWS)
    # No live flag supplied: the handler goes live (it is the keyless default).
    result = asyncio.run(TAUCFunction(FunctionDeps(treasury_auctions=adapter)).execute())
    assert result.sources == ["treasurydirect"]

    tauc = _manifest("TAUC")
    assert tauc.defaults["live_auctions"] is True, (
        "manifest says live_auctions defaults to False but the handler goes live when it is absent"
    )
    assert "opt-in" not in tauc.methodology.lower()


# ─────────────────────────────────────────────────────────────────────────
# EREV#2 — missing coverage and a single period must not read as a real zero
# EREV#1/#3 — methodology is recommendation buckets, not EPS estimates
# ─────────────────────────────────────────────────────────────────────────


class _FinnhubFake:
    def __init__(self, recs: list[dict[str, Any]]):
        self.recs = recs

    async def recommendations(self, symbol: str) -> list[dict[str, Any]]:
        return self.recs


def _bucket(period: str, sb=0, b=0, h=0, s=0, ss=0) -> dict[str, Any]:
    return {"period": period, "strongBuy": sb, "buy": b, "hold": h, "sell": s, "strongSell": ss}


def _erev(recs):
    from showme.engine.functions.equity.erev import EREVFunction

    aapl = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(
        EREVFunction(FunctionDeps(finnhub=_FinnhubFake(recs))).execute(instrument=aapl)
    )


def test_erev_single_period_velocity_is_null_not_zero() -> None:
    res = _erev([_bucket("2026-09-01", sb=5, b=3, h=2)])
    assert res.data["status"] == "ok"
    assert res.data["velocity_avg"] is None
    assert res.data["revisions"] == []


def test_erev_zero_analyst_period_has_null_average() -> None:
    res = _erev([
        _bucket("2026-08-01", sb=4, b=2, h=1, s=0, ss=0),
        _bucket("2026-09-01"),  # no analysts this month
    ])
    latest = res.data["trend"][-1]
    assert latest["n"] == 0
    assert latest["avg"] is None, "zero coverage must not be a neutral 0.0 consensus"
    assert res.data["velocity_avg"] is None
    assert res.data["revisions"][0]["delta_avg"] is None


def test_erev_all_zero_feed_is_empty_not_ok() -> None:
    res = _erev([_bucket("2026-08-01"), _bucket("2026-09-01")])
    assert res.data["status"] == "empty"
    assert res.data["velocity_avg"] is None
    assert res.data["current_score"]["avg"] is None


def test_erev_methodology_describes_recommendations_not_eps() -> None:
    res = _erev([_bucket("2026-08-01", sb=1), _bucket("2026-09-01", sb=2)])
    text = res.data["methodology"]
    assert "recommendation" in text.lower()
    # The disclaimer may name EPS, but the methodology must not claim EPS data.
    assert "eps estimate" not in text.lower()
    assert "eps revision" not in text.lower()
    from showme.engine.functions.equity import erev as erev_mod

    doc = erev_mod.__doc__ or ""
    for claim in ("EPS/revenue revisions", "EPS estimate trend", "EPS estimate revisions"):
        assert claim not in doc
        assert claim not in erev_mod.EREVFunction.description


# ─────────────────────────────────────────────────────────────────────────
# DDM#5 — manifest output contract and inputs must match the handler
# ─────────────────────────────────────────────────────────────────────────

_SHELL_SLOTS = {"data_mode", "as_of"}


def test_ddm_manifest_contract_matches_payload() -> None:
    from showme.engine.functions.equity.dcf import DDMFunction

    ddm_instr = Instrument(symbol="MSFT", asset_class=AssetClass.EQUITY)
    res = asyncio.run(
        DDMFunction(FunctionDeps()).execute(
            instrument=ddm_instr, dividend_ttm=3.0, required_return=0.09, growth_rate=0.03
        )
    )
    payload = res.data
    assert payload["status"] == "ok"

    ddm = _manifest("DDM")
    missing = [k for k in ddm.output_contract.must_have if k not in payload]
    assert not missing, f"DDM must_have not produced by handler: {missing}"
    for slot in ddm.card_schema.slots:
        if slot.key in _SHELL_SLOTS:
            continue
        assert slot.key in payload, f"DDM card slot {slot.key!r} has no matching payload key"
    for name in ("upside_pct",):
        assert name not in ddm.field_dict, "DDM does not compute upside_pct; the pane computes premium"


def test_ddm_manifest_inputs_are_the_ones_the_handler_reads() -> None:
    ddm = _manifest("DDM")
    input_names = {spec.name for spec in ddm.inputs}
    # The handler reads required_return and growth_rate (and the pane sends them).
    assert "required_return" in input_names
    assert "growth_rate" in input_names
    assert "discount_rate" not in input_names, "discount_rate is silently ignored by the handler"


# ─────────────────────────────────────────────────────────────────────────
# PCAS#2 — the +k sigma shock direction must not depend on the SVD sign
# ─────────────────────────────────────────────────────────────────────────


def _factor_panel(sign: float, seed: int = 7) -> "np.ndarray":
    rng = np.random.default_rng(seed)
    common = rng.normal(size=(160, 1))
    betas = np.array([[1.0, 0.8, 0.6, 0.4, 0.2]])
    return sign * (common @ betas + 0.15 * rng.normal(size=(160, 5)))


def test_pca_component_sign_is_normalised() -> None:
    from showme.engine.services import pca_stress

    for sign in (1.0, -1.0):
        dec = pca_stress.pca_decompose(_factor_panel(sign))
        for row in dec["loadings"]:
            assert row.sum() >= 0, "each component must have a non-negative net loading"


def test_pca_shock_direction_is_invariant_to_svd_sign(monkeypatch) -> None:
    from showme.engine.services import pca_stress

    rets = _factor_panel(-1.0)
    ref = pca_stress.factor_shock(rets, pc_index=0, k_sigma=3.0)["asset_returns"]

    orig_svd = np.linalg.svd

    def _flipped(a, full_matrices=True, **kw):
        u, s, vt = orig_svd(a, full_matrices=full_matrices, **kw)
        return -u, s, -vt

    monkeypatch.setattr(np.linalg, "svd", _flipped)
    flipped = pca_stress.factor_shock(rets, pc_index=0, k_sigma=3.0)["asset_returns"]
    assert np.allclose(ref, flipped), "same book and window must give the same +k P&L"


def test_pca_plus_k_is_a_gain_for_a_long_book_in_both_regimes() -> None:
    from showme.engine.services import pca_stress

    weights = np.full(5, 0.2)
    for sign in (1.0, -1.0):
        out = pca_stress.apply_to_portfolio(weights, _factor_panel(sign), pc_index=0, k_sigma=3.0)
        assert out["portfolio_return"] > 0, (
            f"+3 sigma on PC1 must not flip sign with the data sign (sign={sign})"
        )
