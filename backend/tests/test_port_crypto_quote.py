"""PORT — crypto positions must receive live quotes too.

Previously PORTFunction.execute() hard-excluded crypto from the live-quote
fetch (`asset_class ... not in ("CRYPTO",)`), so crypto positions always fell
back to the stale legacy ``current_price`` / ``avg_cost``. The yfinance data
source's ``_yf_symbol`` already maps crypto pairs to Yahoo's ``BTC-USD`` form,
so the exclusion was an unnecessary data-honesty gap.

These tests pin the new contract: a crypto position gets the live quote when a
provider returns one, and the symbol-mapping path is exercised for crypto.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.core.quote import Quote, utcnow  # noqa: E402
from showme.engine.functions.portfolio.port import PORTFunction  # noqa: E402
from showme.engine.portfolio.state import PortfolioPosition, PortfolioState  # noqa: E402


class _FakeYf:
    """Minimal quote provider that records the instruments it was asked for."""

    def __init__(self, last: float) -> None:
        self._last = last
        self.requested: list[Instrument] = []

    async def fetch(self, request):  # noqa: ANN001 - DataRequest is loose
        self.requested.append(request.instrument)
        return Quote(symbol=request.instrument.symbol, timestamp=utcnow(), last=self._last)


def _crypto_portfolio(tmp_path: Path) -> PortfolioState:
    portfolio = PortfolioState(tmp_path / "portfolio.json")
    portfolio.positions = []
    portfolio.add_position(
        PortfolioPosition(
            instrument=Instrument(symbol="BTCUSDT", asset_class=AssetClass.CRYPTO,
                                  exchange="BINANCE", currency="USDT"),
            quantity=2.0,
            avg_cost=50_000.0,
            currency="USDT",
        )
    )
    return portfolio


def test_crypto_position_receives_live_quote(tmp_path: Path) -> None:
    portfolio = _crypto_portfolio(tmp_path)
    fake = _FakeYf(last=61_000.0)
    fn = PORTFunction(deps=FunctionDeps(yfinance=fake))

    result = asyncio.run(fn.execute(_portfolio_override=portfolio))

    row = result.data["positions"][0]
    assert row["symbol"] == "BTCUSDT"
    # The live mark (61k) must win over the stale avg_cost (50k).
    assert row["last"] == 61_000.0
    assert row["market_value"] == 122_000.0
    # The provider must actually have been asked for the crypto instrument.
    assert any(i.asset_class == AssetClass.CRYPTO for i in fake.requested)
    assert "yfinance" in result.sources


def test_crypto_position_falls_back_when_provider_errors(tmp_path: Path) -> None:
    portfolio = _crypto_portfolio(tmp_path)

    class _Boom:
        async def fetch(self, request):  # noqa: ANN001
            raise RuntimeError("provider down")

    fn = PORTFunction(deps=FunctionDeps(yfinance=_Boom()))
    result = asyncio.run(fn.execute(_portfolio_override=portfolio))

    row = result.data["positions"][0]
    # No live quote → graceful fallback to avg_cost, never garbage.
    assert row["last"] == 50_000.0
