from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass  # noqa: E402
from showme.engine.functions.misc.whal import WHALFunction, _shape_binance_trades, _shape_market_bars  # noqa: E402


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


# ── Min-USD contract (2026-09-15) ────────────────────────────────────────
# User report: "Min USD 10M" still listed $13k-$39k trades. The crypto path
# returned `(crossed or parsed)` — the top trades even when nothing crossed
# the threshold. Rows below the applied threshold must never render.


def test_crypto_rows_below_threshold_never_render() -> None:
    rows = _shape_binance_trades(
        [
            {"p": "65000", "q": "0.2", "T": 1_700_000_000_000, "m": False},  # ~$13k
            {"p": "65000", "q": "0.6", "T": 1_700_000_060_000, "m": True},   # ~$39k
        ],
        "BTCUSDT",
        "spot",
        10_000_000,
        25,
    )
    assert rows == [], "sub-threshold trades must not leak through the fallback"


def test_crypto_rows_at_or_above_threshold_survive() -> None:
    rows = _shape_binance_trades(
        [
            {"p": "65000", "q": "0.2", "T": 1_700_000_000_000, "m": False},  # ~$13k
            {"p": "65000", "q": "200", "T": 1_700_000_060_000, "m": True},   # $13M
        ],
        "BTCUSDT",
        "spot",
        10_000_000,
        25,
    )
    assert len(rows) == 1
    assert rows[0]["threshold_crossed"] is True
    assert rows[0]["usd_value"] == 13_000_000.0


def test_proxy_top_window_fallback_respects_threshold() -> None:
    bars = [
        {"timestamp": f"2026-05-08T10:{i:02d}:00+00:00", "close": 100.0 + i * 0.01, "volume": 50}
        for i in range(6)
    ]
    rows, _ = _shape_market_bars(
        bars=bars,
        symbol="AAPL",
        yahoo_symbol="AAPL",
        market="EQUITY",
        threshold_usd=1_000_000,
        row_limit=10,
    )
    assert rows == [], "the top-window fallback must not bypass Min USD"

    unthresholded, _ = _shape_market_bars(
        bars=bars,
        symbol="AAPL",
        yahoo_symbol="AAPL",
        market="EQUITY",
        threshold_usd=0,
        row_limit=10,
    )
    assert unthresholded, "without a threshold the top windows still render"


def test_sec_ticker_map_is_cached_between_calls() -> None:
    import showme.engine.functions.misc.whal as whal_mod

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}

    class _FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        async def get(self, url, headers=None):
            self.calls += 1
            return _FakeResponse()

    async def _run():
        whal_mod._SEC_TICKERS_CACHE["fetched_at"] = 0.0
        whal_mod._SEC_TICKERS_CACHE["by_ticker"] = {}
        client = _FakeClient()
        first = await whal_mod._sec_ticker_map(client)
        second = await whal_mod._sec_ticker_map(client)
        return client.calls, first, second

    calls, first, second = asyncio.run(_run())
    assert calls == 1, "the 800 KB SEC ticker file must not refetch per poll"
    assert "AAPL" in first
    assert second is first


def test_whal_route_keeps_its_own_interval_and_timeout() -> None:
    """Route must not collapse WHAL to a 1d interval / 3s budget."""
    from showme import server

    routed = server._route_function_params(
        "WHAL", {"symbol": "AAPL", "market": "EQUITY"}
    )
    assert "interval" not in routed, "generic '1d' collapsed equity flow to one daily bar"
    assert "timeout" not in routed, "generic 3s undercut SEC/Yahoo fetches"


def test_crypto_pair_on_equity_tab_reports_honest_warning(monkeypatch) -> None:
    """A crypto pair under the Equity tab must not read as a silent empty."""
    import showme.engine.functions.misc.whal as whal_mod

    async def _no_bars(*_args, **_kwargs):
        return []

    async def _no_sec(*_args, **_kwargs):
        return []

    monkeypatch.setattr(whal_mod, "_fetch_yahoo_bars", _no_bars)
    monkeypatch.setattr(whal_mod, "_fetch_sec_filing_rows", _no_sec)

    fn = WHALFunction(FunctionDeps())
    result = asyncio.run(
        fn.execute(symbol="BTCUSDT", market="EQUITY", threshold_usd=1_000_000)
    )
    assert any("Crypto tab" in w for w in result.warnings)
