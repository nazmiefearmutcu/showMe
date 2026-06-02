"""Tests for the shared sizing module (FIX_CONTRACT C1).

Covers the math + validation contract that both the live runner
(``runner._dispatch_*``) and the performance route (``performance.compute_trades``)
depend on. Each branch of ``resolve_quantity`` and each direction of
``compute_pnl`` is pinned.

Bugs blocked by these tests:
* C-API-1 (negative / zero / NaN sizing accepted)
* H-SUP-3 (PnL math 60000× off for fixed_base)
"""
from __future__ import annotations


import pytest

from showme.strategies.sizing import (
    compute_pnl,
    compute_pnl_pct,
    resolve_quantity,
)


# ── resolve_quantity branches ────────────────────────────────────────────


class TestResolveQuantity:
    """C-API-1 / H-SUP-3: every sizing_kind exercised end-to-end."""

    def test_fixed_quote_divides_by_price(self):
        # $100 quote on a $50 asset → 2 base units.
        qty = resolve_quantity(
            sizing_kind="fixed_quote", sizing_value=100.0,
            price=50.0, equity=10_000.0,
        )
        assert qty == pytest.approx(2.0)

    def test_fixed_base_returns_value_directly(self):
        # 2 BTC means 2 BTC regardless of price.
        qty = resolve_quantity(
            sizing_kind="fixed_base", sizing_value=2.0,
            price=60_000.0, equity=10_000.0,
        )
        assert qty == pytest.approx(2.0)

    def test_risk_pct_uses_equity_and_price(self):
        # 5% of $10k = $500 budget; @ $50/share → 10 shares.
        qty = resolve_quantity(
            sizing_kind="risk_pct", sizing_value=5.0,
            price=50.0, equity=10_000.0,
        )
        assert qty == pytest.approx(10.0)

    # ── validation: negative / zero / NaN / inf ──────────────────────────

    def test_negative_sizing_value_rejected(self):
        with pytest.raises(ValueError, match="sizing_value"):
            resolve_quantity(
                sizing_kind="fixed_quote", sizing_value=-100.0,
                price=50.0, equity=10_000.0,
            )

    def test_zero_sizing_value_rejected(self):
        with pytest.raises(ValueError, match="sizing_value"):
            resolve_quantity(
                sizing_kind="fixed_quote", sizing_value=0.0,
                price=50.0, equity=10_000.0,
            )

    def test_nan_sizing_value_rejected(self):
        with pytest.raises(ValueError, match="sizing_value"):
            resolve_quantity(
                sizing_kind="fixed_quote", sizing_value=float("nan"),
                price=50.0, equity=10_000.0,
            )

    def test_inf_sizing_value_rejected(self):
        with pytest.raises(ValueError, match="sizing_value"):
            resolve_quantity(
                sizing_kind="fixed_quote", sizing_value=float("inf"),
                price=50.0, equity=10_000.0,
            )

    def test_zero_price_rejected(self):
        with pytest.raises(ValueError, match="price"):
            resolve_quantity(
                sizing_kind="fixed_quote", sizing_value=100.0,
                price=0.0, equity=10_000.0,
            )

    def test_negative_price_rejected(self):
        with pytest.raises(ValueError, match="price"):
            resolve_quantity(
                sizing_kind="fixed_quote", sizing_value=100.0,
                price=-50.0, equity=10_000.0,
            )

    # ── risk_pct range constraints ───────────────────────────────────────

    def test_risk_pct_out_of_range_too_high_rejected(self):
        # 200% would mean 2× leverage; the audit explicitly cites this case.
        with pytest.raises(ValueError, match="risk_pct"):
            resolve_quantity(
                sizing_kind="risk_pct", sizing_value=200.0,
                price=50.0, equity=10_000.0,
            )

    def test_risk_pct_zero_or_negative_rejected(self):
        # Zero is caught by the generic sizing_value check (`> 0`).
        with pytest.raises(ValueError):
            resolve_quantity(
                sizing_kind="risk_pct", sizing_value=0.0,
                price=50.0, equity=10_000.0,
            )

    def test_risk_pct_boundary_100_accepted(self):
        # Exactly 100% allowed (all-in).
        qty = resolve_quantity(
            sizing_kind="risk_pct", sizing_value=100.0,
            price=50.0, equity=10_000.0,
        )
        assert qty == pytest.approx(200.0)

    def test_risk_pct_requires_positive_equity(self):
        with pytest.raises(ValueError, match="equity"):
            resolve_quantity(
                sizing_kind="risk_pct", sizing_value=5.0,
                price=50.0, equity=0.0,
            )

    def test_risk_pct_requires_finite_equity(self):
        with pytest.raises(ValueError, match="equity"):
            resolve_quantity(
                sizing_kind="risk_pct", sizing_value=5.0,
                price=50.0, equity=float("nan"),
            )

    def test_fixed_kinds_do_not_check_equity(self):
        # fixed_quote / fixed_base don't depend on equity; bad equity is
        # not an error if the kind doesn't use it.
        qty = resolve_quantity(
            sizing_kind="fixed_quote", sizing_value=100.0,
            price=50.0, equity=0.0,
        )
        assert qty == pytest.approx(2.0)

    def test_unknown_sizing_kind_rejected(self):
        with pytest.raises(ValueError, match="unknown sizing_kind"):
            resolve_quantity(
                sizing_kind="bogus",  # type: ignore[arg-type]
                sizing_value=100.0, price=50.0, equity=10_000.0,
            )


# ── compute_pnl side-aware ──────────────────────────────────────────────


class TestComputePnl:
    def test_long_profit(self):
        # 1 BTC long, $100 → $110 = +$10 PnL.
        pnl = compute_pnl(entry_price=100.0, exit_price=110.0,
                          side="long", entry_qty=1.0)
        assert pnl == pytest.approx(10.0)

    def test_long_loss(self):
        pnl = compute_pnl(entry_price=100.0, exit_price=95.0,
                          side="long", entry_qty=1.0)
        assert pnl == pytest.approx(-5.0)

    def test_short_profit(self):
        # 1 BTC short, $100 → $90 = +$10 PnL.
        pnl = compute_pnl(entry_price=100.0, exit_price=90.0,
                          side="short", entry_qty=1.0)
        assert pnl == pytest.approx(10.0)

    def test_short_loss(self):
        pnl = compute_pnl(entry_price=100.0, exit_price=110.0,
                          side="short", entry_qty=1.0)
        assert pnl == pytest.approx(-10.0)

    def test_pnl_scales_with_qty(self):
        pnl = compute_pnl(entry_price=100.0, exit_price=110.0,
                          side="long", entry_qty=2.5)
        assert pnl == pytest.approx(25.0)

    def test_pnl_zero_qty_returns_zero(self):
        pnl = compute_pnl(entry_price=100.0, exit_price=110.0,
                          side="long", entry_qty=0.0)
        assert pnl == 0.0

    def test_pnl_negative_entry_price_returns_zero(self):
        pnl = compute_pnl(entry_price=-100.0, exit_price=110.0,
                          side="long", entry_qty=1.0)
        assert pnl == 0.0

    def test_pnl_nan_exit_returns_zero(self):
        pnl = compute_pnl(entry_price=100.0, exit_price=float("nan"),
                          side="long", entry_qty=1.0)
        assert pnl == 0.0

    def test_pnl_pct_long(self):
        # +10% on a long.
        pct = compute_pnl_pct(entry_price=100.0, exit_price=110.0, side="long")
        assert pct == pytest.approx(10.0)

    def test_pnl_pct_short(self):
        # +10% on a short means price fell 10%.
        pct = compute_pnl_pct(entry_price=100.0, exit_price=90.0, side="short")
        assert pct == pytest.approx(10.0)


# ── audit's "60000× off" repro for fixed_base sizing ────────────────────


class TestFixedBaseSizingPnL:
    """H-SUP-3 regression: 2 BTC trade, entry $30k → exit $32k = $4000 PnL.

    Old performance.compute_trades formula was ``(exit-entry)*sizing/entry`` →
    ``(32000-30000)*2/30000 = 0.133`` (off by ≈15000×). The shared sizing
    module computes it correctly side-aware.
    """

    def test_two_btc_long_round_trip(self):
        qty = resolve_quantity(
            sizing_kind="fixed_base", sizing_value=2.0,
            price=30_000.0, equity=10_000.0,
        )
        assert qty == pytest.approx(2.0)
        pnl = compute_pnl(
            entry_price=30_000.0, exit_price=32_000.0,
            side="long", entry_qty=qty,
        )
        # 2 BTC × $2000 move = $4000 absolute PnL.
        assert pnl == pytest.approx(4_000.0)

    def test_pct_unchanged_by_sizing_kind(self):
        # The percent PnL of the round-trip should be identical regardless
        # of the sizing kind because it's a price-only ratio.
        pct = compute_pnl_pct(
            entry_price=30_000.0, exit_price=32_000.0, side="long",
        )
        # +$2000 on a $30k entry = +6.667%
        assert pct == pytest.approx(2000.0 / 30_000.0 * 100.0)
