"""R2 M-6 regression: MARS partial factor-proxy coverage must be labelled.

``align_return_series(policy="pairwise")`` drops empty proxy series, so when
only SOME of the six ETF factor proxies answer, the regression used to run
silently on the survivors while wearing full-live metadata
(``{"live": True, "data_mode": "live_yfinance"}``, ``sources=["yfinance"]``,
no warning). Contract after the fix:

* All six proxies land -> live labels kept, loaded list surfaced in
  ``metadata.factor_proxies_loaded``.
* Any proxy missing -> ``live=False`` / ``fallback=True`` /
  ``data_mode="modeled"``, a warning NAMING the missing proxies, sources
  downgraded to ``multi_asset_risk_model``, and the loaded-proxy list in
  metadata.

Offline: the yfinance adapter is a fake that succeeds for a chosen symbol
subset (same fake shape as test_default_polarity_flip.py).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402

EQ = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)

_ALL_PROXIES = {"SPY", "IWM", "VLUE", "MTUM", "QUAL", "USMV"}
_ALL_FACTORS = {"MKT", "SMB", "HML", "MOM", "QMJ", "BAB"}


def _run(coro):
    return asyncio.run(coro)


def _ohlcv(days: int = 400) -> pd.DataFrame:
    idx = pd.date_range(end=datetime.now(timezone.utc), periods=days, freq="1D", tz="UTC")
    close = pd.Series([100.0 + i * 0.5 for i in range(days)], index=idx)
    return pd.DataFrame({"close": close})


class _SubsetYfinance:
    """Answers OHLCV only for the listed symbols; raises for the rest."""

    def __init__(self, ok_symbols: set[str]):
        self.ok_symbols = ok_symbols
        self.asked: list[str] = []

    async def fetch(self, request: Any, *args: Any, **kwargs: Any) -> pd.DataFrame:
        symbol = request.instrument.symbol
        self.asked.append(symbol)
        if symbol not in self.ok_symbols:
            raise RuntimeError(f"no history for {symbol}")
        return _ohlcv()


def _mars(yf: _SubsetYfinance, **params: Any):
    from showme.engine.functions.portfolio._more import MARSFunction
    return _run(MARSFunction(FunctionDeps(yfinance=yf)).execute(
        instrument=EQ, symbols=["AAPL"], **params
    ))


def test_mars_partial_proxy_coverage_is_labelled_not_live():
    # 5 of the 6 factor proxies answer; USMV (BAB) is down. The portfolio
    # leg (AAPL) answers too, so ONLY the factor shortfall drives labels.
    yf = _SubsetYfinance({"SPY", "IWM", "VLUE", "MTUM", "QUAL", "AAPL"})
    result = _mars(yf)
    metadata = result.metadata or {}
    assert metadata.get("live") is False, "partial proxy coverage must not claim live"
    assert metadata.get("fallback") is True
    assert metadata.get("data_mode") == "modeled"
    assert result.sources == ["multi_asset_risk_model"]
    # The warning names the missing factor and the survivors.
    joined = " ".join(result.warnings).lower()
    assert "bab" in joined, f"warning must name the missing factor, got: {result.warnings}"
    assert "5/6" in joined and "mkt" in joined
    # Loaded-factor list surfaces in metadata (5 survivors, BAB absent).
    loaded = metadata.get("factor_proxies_loaded")
    assert isinstance(loaded, list) and sorted(loaded) == sorted(_ALL_FACTORS - {"BAB"})


def test_mars_full_proxy_coverage_stays_live():
    yf = _SubsetYfinance(_ALL_PROXIES | {"AAPL"})
    result = _mars(yf)
    metadata = result.metadata or {}
    assert metadata.get("live") is True
    assert metadata.get("fallback") is not True
    assert result.sources == ["yfinance"]
    loaded = metadata.get("factor_proxies_loaded")
    assert isinstance(loaded, list) and sorted(loaded) == sorted(_ALL_FACTORS)
    assert not result.warnings, "full live coverage must not carry proxy warnings"


def test_mars_sanitizer_never_grants_live_on_shortfall():
    """End-to-end through the sanitizer: the partial envelope must not
    earn a LIVE data_state (the M-6 attack this test pins)."""
    from showme import server

    yf = _SubsetYfinance({"SPY", "IWM", "VLUE", "MTUM", "QUAL", "AAPL"})
    result = _mars(yf)
    payload = {
        "code": "MARS",
        "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
        "data": result.data,
        "metadata": result.metadata,
        "sources": list(result.sources),
        "warnings": list(result.warnings),
    }
    sanitized = server.enforce_live_or_label_synthetic("MARS", {"symbol": "AAPL"}, payload)
    assert sanitized["data_state"] != "live"
