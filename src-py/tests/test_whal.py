from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from src.core.instrument import AssetClass  # noqa: E402
from src.functions.misc.whal import WHALFunction, _shape_binance_trades, _shape_market_bars  # noqa: E402


def test_whal_is_cross_asset_function() -> None:
    assert AssetClass.CRYPTO in WHALFunction.asset_classes
    assert AssetClass.EQUITY in WHALFunction.asset_classes
    assert AssetClass.FX in WHALFunction.asset_classes
    assert AssetClass.COMMODITY in WHALFunction.asset_classes


def test_crypto_trade_rows_do_not_require_whale_alert_key() -> None:
    rows = _shape_binance_trades(
        [
            {"p": "100000", "q": "12", "T": 1_700_000_000_000, "m": False},
            {"p": "100000", "q": "1", "T": 1_700_000_060_000, "m": True},
        ],
        "BTCUSDT",
        "spot",
        1_000_000,
        5,
    )

    assert rows[0]["alert_type"] == "crypto_large_trade"
    assert rows[0]["threshold_crossed"] is True
    assert rows[0]["source_mode"] == "binance_spot_aggtrades"


def test_market_proxy_uses_price_impulse_when_volume_is_missing() -> None:
    rows, history = _shape_market_bars(
        bars=[
            {"timestamp": "2026-05-08T10:00:00+00:00", "close": 1.1000, "volume": 0},
            {"timestamp": "2026-05-08T10:05:00+00:00", "close": 1.1001, "volume": 0},
            {"timestamp": "2026-05-08T10:10:00+00:00", "close": 1.1060, "volume": 0},
        ],
        symbol="EURUSD",
        yahoo_symbol="EURUSD=X",
        market="FX",
        threshold_usd=1_000_000,
        row_limit=5,
    )

    assert history
    assert rows
    assert rows[0]["alert_type"] in {"liquidity_impulse_proxy", "top_impulse_window"}
    assert rows[0]["source_mode"].startswith("yahoo_")
