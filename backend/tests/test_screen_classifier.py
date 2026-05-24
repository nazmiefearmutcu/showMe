"""B7 regression: ``_asset_for_screen_symbol`` + ``_quote_row`` arithmetic.

Bugs fixed:

* operator precedence on the USD suffix check — the length guard never
  blocked plain ``USDT``/``USDC``-suffix symbols, but ``USD``-only suffix
  was the only one gated, leaving e.g. ``"FX-USD"`` ambiguous;
* bare ``SPX`` / ``NDX`` / ``SPY`` got dragged into EQUITY; whitelist them;
* divide-by-zero / coercion-to-zero in ``_quote_row`` was inventing fake
  ``-100%`` drops when ``close_prev`` was ``None``.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from showme.engine.core.instrument import AssetClass
from showme.engine.core.quote import Quote
from showme.engine.functions.screen._funcs import _asset_for_screen_symbol, _quote_row


# ── classifier ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("symbol,expected", [
    ("SPX", AssetClass.INDEX),
    ("NDX", AssetClass.INDEX),
    ("DJI", AssetClass.INDEX),
    ("RUT", AssetClass.INDEX),
    ("VIX", AssetClass.INDEX),
    ("^GSPC", AssetClass.INDEX),
    ("SPY", AssetClass.ETF),
    ("QQQ", AssetClass.ETF),
    ("IWM", AssetClass.ETF),
    ("DIA", AssetClass.ETF),
    ("BTCUSDT", AssetClass.CRYPTO),
    ("ETHUSDC", AssetClass.CRYPTO),
    ("ABCUSD", AssetClass.CRYPTO),  # len>3, USD suffix
    ("USD", AssetClass.EQUITY),     # len==3, must NOT match CRYPTO
    ("EURUSD=X", AssetClass.FX),
    ("GC=F", AssetClass.COMMODITY),
    ("AAPL", AssetClass.EQUITY),
])
def test_b7_classifier_routes_each_symbol_correctly(symbol, expected):
    assert _asset_for_screen_symbol(symbol) == expected


# ── _quote_row arithmetic ──────────────────────────────────────────────────

class _FakeProvider:
    def __init__(self, quote: Quote | None):
        self._quote = quote

    async def fetch(self, request):
        return self._quote


def _quote(**kwargs) -> Quote:
    return Quote(symbol=kwargs.pop("symbol", "X"),
                 timestamp=datetime.now(tz=timezone.utc),
                 **kwargs)


async def test_b7_quote_row_no_fake_minus_100_when_prev_is_none():
    """Old code: ``(last/0 - 1)*100 = -100%``. New code: ``None``."""
    q = _quote(last=100.0, close_prev=None, volume_24h=50.0)
    row = await _quote_row(_FakeProvider(q), "AAPL", AssetClass.EQUITY, 4.0)
    assert row is not None
    assert row["change_pct"] is None
    assert row["change"] is None


async def test_b7_quote_row_dollar_volume_none_when_volume_missing():
    q = _quote(last=100.0, close_prev=95.0, volume_24h=None)
    row = await _quote_row(_FakeProvider(q), "AAPL", AssetClass.EQUITY, 4.0)
    assert row is not None
    assert row["dollar_volume"] is None


async def test_b7_quote_row_computes_change_pct_correctly():
    q = _quote(last=110.0, close_prev=100.0,
               volume_24h=1_000_000.0, high_24h=112.0, low_24h=108.0)
    row = await _quote_row(_FakeProvider(q), "AAPL", AssetClass.EQUITY, 4.0)
    assert row is not None
    assert row["change_pct"] == pytest.approx(10.0)
    assert row["change"] == pytest.approx(10.0)
    assert row["dollar_volume"] == pytest.approx(110_000_000.0)
    assert row["range_pct"] == pytest.approx(4.0 / 110.0 * 100.0)


async def test_b7_quote_row_range_pct_none_when_high_or_low_missing():
    q = _quote(last=100.0, close_prev=95.0, volume_24h=1_000_000.0,
               high_24h=None, low_24h=99.0)
    row = await _quote_row(_FakeProvider(q), "AAPL", AssetClass.EQUITY, 4.0)
    assert row is not None
    assert row["range_pct"] is None


async def test_b7_quote_row_zero_prev_close_does_not_explode():
    """``prev == 0`` would have divided by zero. Now ⇒ None."""
    q = _quote(last=100.0, close_prev=0.0, volume_24h=1_000_000.0)
    row = await _quote_row(_FakeProvider(q), "AAPL", AssetClass.EQUITY, 4.0)
    assert row is not None
    assert row["change_pct"] is None
    assert row["change"] is None
