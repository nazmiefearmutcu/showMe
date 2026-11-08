"""MARS (Multi-Asset Risk) honesty and input contract, offline.

Each block pins one audit finding (MARS#1..#7). Network is replaced by an
in-memory yfinance fake; no test touches the internet or the sidecar.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402

EQ = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _run(coro):
    return asyncio.run(coro)


def _series_frame(seed: int, days: int = 400) -> pd.DataFrame:
    """Deterministic, non-collinear close series per symbol (seeded random walk)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(end=datetime.now(timezone.utc), periods=days, freq="1D", tz="UTC")
    steps = rng.normal(0.0004, 0.01, size=days)
    close = 100.0 * np.exp(np.cumsum(steps))
    return pd.DataFrame({"close": close}, index=idx)


class _KeyedYfinance:
    """Serves a distinct random-walk series per symbol; optional per-symbol delay."""

    def __init__(self, ok_symbols: set[str] | None = None, delay: float = 0.0):
        self.ok_symbols = ok_symbols
        self.delay = delay
        self.asked: list[str] = []

    async def fetch(self, request: Any, *args: Any, **kwargs: Any) -> pd.DataFrame:
        symbol = request.instrument.symbol
        self.asked.append(symbol)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.ok_symbols is not None and symbol not in self.ok_symbols:
            raise RuntimeError(f"Quote not found for symbol: {symbol}")
        seed = sum(ord(c) for c in symbol) * 7 + 3
        return _series_frame(seed)


# ────────────────────────────────────────────────────────────────────────
# MARS#7: catalog description is missing and the `live` toggle is unread.
# ────────────────────────────────────────────────────────────────────────


def test_mars_has_a_catalog_description():
    from showme.engine.functions.portfolio._more import MARSFunction

    assert MARSFunction.description.strip(), "MARS needs a function-index description"
    assert "factor" in MARSFunction.description.lower()


def test_mars_live_false_from_pane_is_honoured():
    """PortfolioAnalytics sends live=false; the handler must not still fetch live."""
    from showme.engine.functions.portfolio._more import MARSFunction

    yf = _KeyedYfinance()
    result = _run(MARSFunction(FunctionDeps(yfinance=yf)).execute(
        instrument=EQ, symbols=["AAPL"], live=False,
    ))
    assert yf.asked == [], "live=false must serve the labelled template without a live fetch"
    assert result.metadata.get("live") is False
    assert result.sources == ["multi_asset_risk_model"]


def test_mars_router_default_live_true_still_fetches_live():
    """The router injects live=True on every routed call; that must keep the live path."""
    from showme.engine.functions.portfolio._more import MARSFunction

    yf = _KeyedYfinance()
    result = _run(MARSFunction(FunctionDeps(yfinance=yf)).execute(
        instrument=EQ, symbols=["AAPL"], live=True,
    ))
    assert yf.asked, "live=true must attempt the live provider"
    assert result.metadata.get("live") is True


# ────────────────────────────────────────────────────────────────────────
# MARS#6: the manifest seed describes a different function (Mean-Reverting
# Allocation) and its must_have fields are not produced by the handler.
# ────────────────────────────────────────────────────────────────────────


def _mars_seed():
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    return REGISTRY.get("MARS")


def test_mars_seed_names_the_shipped_handler():
    from showme.engine.functions.portfolio._more import MARSFunction

    entry = _mars_seed()
    assert entry.name == MARSFunction.name == "Multi-Asset Risk"
    assert "reversion" not in entry.intent.lower()


def test_mars_seed_must_have_keys_are_produced_by_handler():
    from showme.engine.functions.portfolio._more import MARSFunction

    entry = _mars_seed()
    result = _run(MARSFunction(FunctionDeps()).execute(instrument=EQ, reference=True))
    top_level = set(result.data) | {"symbol"}
    missing = [k for k in entry.output_contract.must_have if k not in top_level]
    assert missing == [], f"seed promises fields the handler never returns: {missing}"


# ────────────────────────────────────────────────────────────────────────
# MARS#4: the router injects quote_timeout=3 on every routed call. MARS
# fetches six ETF proxies plus the universe, so ordinary latency must not
# drop the proxies into the template fallback.
# ────────────────────────────────────────────────────────────────────────


_SIX_PROXIES = {"SPY", "IWM", "VLUE", "MTUM", "QUAL", "USMV"}


def test_mars_router_quote_timeout_does_not_drop_live_factor_proxies():
    from showme.engine.functions.portfolio._more import MARSFunction

    # 3.2 s per fetch: above the router's generic 3 s budget, well under MARS's own.
    yf = _KeyedYfinance(delay=3.2)
    result = _run(MARSFunction(FunctionDeps(yfinance=yf)).execute(
        instrument=EQ, symbols=["AAPL"], live=True,
        timeout=3, quote_timeout=3, news_timeout=3, sec_timeout=3,
        yfinance_timeout=3, finnhub_timeout=3, fred_timeout=3, damodaran_timeout=3,
    ))
    assert result.metadata.get("live") is True, result.warnings
    assert set(result.metadata.get("factor_proxies_loaded") or []) == {
        "MKT", "SMB", "HML", "MOM", "QMJ", "BAB",
    }
