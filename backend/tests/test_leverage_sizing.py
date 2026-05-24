"""Q4 audit C5: leverage threads into sizing math.

Before this fix, "5% risk_pct" at 20× leverage was 5% NOTIONAL, not 5%
of equity × 20× leverage. resolve_quantity now accepts ``leverage`` and
``risk_per_trade`` sizing kind (Van Tharp R-multiple).
"""
from __future__ import annotations

import pytest

from showme.strategies.sizing import resolve_quantity


class TestLeverageOnRiskPct:
    def test_leverage_1x_unchanged(self):
        # 5% of $10k = $500 budget @ $50 → 10 shares (same as old behaviour).
        qty = resolve_quantity(
            sizing_kind="risk_pct", sizing_value=5.0,
            price=50.0, equity=10_000.0, leverage=1.0,
        )
        assert qty == pytest.approx(10.0)

    def test_leverage_20x_multiplies_notional(self):
        # Same 5% but 20× → effective notional = $500 × 20 = $10000 @ $50 → 200 shares.
        qty = resolve_quantity(
            sizing_kind="risk_pct", sizing_value=5.0,
            price=50.0, equity=10_000.0, leverage=20.0,
        )
        assert qty == pytest.approx(200.0)

    def test_leverage_default_is_1x(self):
        # No leverage kwarg = 1× (backward compat).
        qty = resolve_quantity(
            sizing_kind="risk_pct", sizing_value=5.0,
            price=50.0, equity=10_000.0,
        )
        assert qty == pytest.approx(10.0)


class TestRiskPerTrade:
    def test_van_tharp_basic_with_enough_leverage(self):
        # 2% risk of $10k = $200. SL 1% on $100 entry → stop distance = $1.
        # van-tharp qty = $200 / $1 = 200 shares.
        # Notional = 200 * $100 = $20k. Need leverage >= 2× to allow this.
        qty = resolve_quantity(
            sizing_kind="risk_per_trade", sizing_value=2.0,
            price=100.0, equity=10_000.0, stop_loss_pct=1.0, leverage=2.0,
        )
        assert qty == pytest.approx(200.0)

    def test_van_tharp_clamped_by_default_1x_leverage(self):
        # Without explicit leverage, 1× clamps notional ≤ $10k → 100 shares.
        qty = resolve_quantity(
            sizing_kind="risk_per_trade", sizing_value=2.0,
            price=100.0, equity=10_000.0, stop_loss_pct=1.0,
        )
        assert qty == pytest.approx(100.0)

    def test_van_tharp_clamps_when_position_too_big(self):
        # SL = 0.1% on $100 → stop distance = $0.1. risk = $200 / $0.1 = 2000 shares.
        # leverage 1× caps notional at $10k → max qty = 100. CLAMPED.
        qty = resolve_quantity(
            sizing_kind="risk_per_trade", sizing_value=2.0,
            price=100.0, equity=10_000.0, stop_loss_pct=0.1, leverage=1.0,
        )
        assert qty == pytest.approx(100.0)

    def test_van_tharp_requires_stop_loss(self):
        with pytest.raises(ValueError, match="stop_loss_pct"):
            resolve_quantity(
                sizing_kind="risk_per_trade", sizing_value=2.0,
                price=100.0, equity=10_000.0,
            )

    def test_van_tharp_rejects_zero_stop_loss(self):
        with pytest.raises(ValueError, match="stop_loss_pct"):
            resolve_quantity(
                sizing_kind="risk_per_trade", sizing_value=2.0,
                price=100.0, equity=10_000.0, stop_loss_pct=0.0,
            )

    def test_van_tharp_rejects_oversized_risk(self):
        with pytest.raises(ValueError, match="risk_per_trade"):
            resolve_quantity(
                sizing_kind="risk_per_trade", sizing_value=101.0,
                price=100.0, equity=10_000.0, stop_loss_pct=1.0,
            )


class TestLeverageValidation:
    def test_negative_leverage_rejected(self):
        with pytest.raises(ValueError, match="leverage"):
            resolve_quantity(
                sizing_kind="risk_pct", sizing_value=5.0,
                price=50.0, equity=10_000.0, leverage=-1.0,
            )

    def test_zero_leverage_rejected(self):
        with pytest.raises(ValueError, match="leverage"):
            resolve_quantity(
                sizing_kind="risk_pct", sizing_value=5.0,
                price=50.0, equity=10_000.0, leverage=0.0,
            )

    def test_nan_leverage_rejected(self):
        with pytest.raises(ValueError, match="leverage"):
            resolve_quantity(
                sizing_kind="risk_pct", sizing_value=5.0,
                price=50.0, equity=10_000.0, leverage=float("nan"),
            )
