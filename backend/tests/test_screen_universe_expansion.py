"""Universe-expansion pins for the screener family (MOST / MOSS / CSRC).

Owner order (2026-09-15): lift the tiny hardcoded universes everywhere — the
MOST tabs collapsed to a handful of FX rows (resolved-only merge silently
dropped everything else), CSRC was restricted to 6 commodities by a route
default, and MOSS ranked a 3-5 name peer group injected by the generic route
profile. These pins lock in the expanded universes, the bounded-scan honesty
contract (pending/unresolved symbols are emitted with nulls, never dropped),
and the fixed route defaults.

All tests are offline: quote/OHLCV providers are injected fakes and the one
batched Binance call is monkeypatched.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from showme import server
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.quote import Quote


def _run(coro):
    return asyncio.run(coro)


def _quote(symbol: str, last: float = 100.0, prev: float = 99.0, volume: float = 1_000_000.0) -> Quote:
    return Quote(
        symbol=symbol,
        timestamp=datetime.now(timezone.utc),
        last=last,
        close_prev=prev,
        volume_24h=volume,
        high_24h=last * 1.01,
        low_24h=prev * 0.99,
    )


class _AllQuotesProvider:
    """yfinance-shaped QUOTE provider that answers every symbol live."""

    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, request: Any) -> Any:
        self.calls += 1
        symbol = str(getattr(getattr(request, "instrument", None), "symbol", "") or "X")
        return _quote(symbol)


class _NoQuotesProvider(_AllQuotesProvider):
    """Provider is present but never returns a usable quote."""

    async def fetch(self, request: Any) -> Any:
        self.calls += 1
        return None


class _SelectiveQuotesProvider(_AllQuotesProvider):
    """Answers only the requested symbols; everything else stays unresolved."""

    def __init__(self, symbols: set[str]) -> None:
        super().__init__()
        self.symbols = {symbol.upper() for symbol in symbols}

    async def fetch(self, request: Any) -> Any:
        self.calls += 1
        symbol = str(getattr(getattr(request, "instrument", None), "symbol", "") or "X")
        if symbol.upper() in self.symbols:
            return _quote(symbol)
        return None


def _ohlcv_frame(days: int = 90) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=days, freq="D")
    closes = [100.0 + float((i % 7) - 3) for i in range(days)]
    return pd.DataFrame({"close": closes}, index=index)


class _OhlcvProvider:
    """yfinance-shaped OHLCV provider returning a synthetic daily series."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls = 0

    async def fetch(self, request: Any) -> Any:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return _ohlcv_frame()


def _stub_binance_batch(rows: list[dict[str, Any]]):
    async def _stub(limit: int = 60) -> list[dict[str, Any]]:
        return [dict(row) for row in rows[:limit]]

    return _stub


def _fake_crypto_board(count: int = 60) -> list[dict[str, Any]]:
    board: list[dict[str, Any]] = []
    for index in range(count):
        board.append({
            "symbol": f"COIN{index:02d}USDT",
            "name": f"Coin {index} / USDT",
            "asset_class": "crypto",
            "exchange": "BINANCE",
            "last": 10.0 + index,
            "prev_close": 9.5 + index,
            "change": 0.5,
            "volume": 1_000.0 * (index + 1),
            "dollar_volume": 5_000_000.0 * (count - index),
            "change_pct": 1.0,
            "high": 11.0 + index,
            "low": 9.0 + index,
            "range_pct": 2.0,
            "quote_state": "live",
            "source": "binance",
        })
    return board


# ──────────────────────────────────────────────────────────────────────────
# MOST — expanded cross-asset universes
# ──────────────────────────────────────────────────────────────────────────


def test_most_fx_universe_has_g10_and_em_pairs_live() -> None:
    from showme.engine.functions.screen._funcs import MOSTFunction

    provider = _AllQuotesProvider()
    result = _run(
        MOSTFunction(deps=FunctionDeps(yfinance=provider)).execute(
            asset_class="fx", live_screen=True, sort="abs_change", limit=50
        )
    )
    rows = result.data["rows"]
    assert result.data["universe_size"] >= 25, "FX tab must scan the full G10+EM board"
    assert len(rows) >= 25
    assert provider.calls >= 25
    assert all(row["quote_state"] == "live" for row in rows)
    assert any(row["symbol"] == "EURUSD=X" for row in rows)
    assert any(row["symbol"] == "USDTRY=X" for row in rows)


def test_most_equities_tab_is_not_empty_live() -> None:
    from showme.engine.functions.screen._funcs import MOSTFunction

    provider = _AllQuotesProvider()
    result = _run(
        MOSTFunction(deps=FunctionDeps(yfinance=provider)).execute(
            asset_class="equities", live_screen=True, sort="volume", limit=50
        )
    )
    rows = result.data["rows"]
    assert result.data["universe_size"] >= 50, "equities tab scans a liquid S&P subset"
    assert len(rows) >= 40
    assert all(row["quote_state"] == "live" for row in rows)


def test_most_crypto_uses_one_batch_call_and_ranks(monkeypatch) -> None:
    import showme.engine.functions.screen._funcs as funcs

    from showme.engine.functions.screen._funcs import MOSTFunction

    monkeypatch.setattr(funcs, "_binance_top_crypto_rows", _stub_binance_batch(_fake_crypto_board(60)))
    provider = _AllQuotesProvider()
    result = _run(
        MOSTFunction(deps=FunctionDeps(yfinance=provider)).execute(
            asset_class="crypto", live_screen=True, sort="dollar_volume", limit=50
        )
    )
    rows = result.data["rows"]
    assert len(rows) >= 20
    assert result.data["universe_size"] >= 20
    assert "binance" in result.sources
    assert provider.calls == 0, "crypto must not fan out per-symbol quotes when the batch answers"
    dollars = [float(row["dollar_volume"] or 0) for row in rows]
    assert dollars == sorted(dollars, reverse=True)
    assert all(row["quote_state"] == "live" for row in rows)


def test_most_pending_rows_are_emitted_with_nulls_not_dropped(monkeypatch) -> None:
    import showme.engine.functions.screen._funcs as funcs

    from showme.engine.functions.screen._funcs import MOSTFunction

    monkeypatch.setattr(funcs, "_binance_top_crypto_rows", _stub_binance_batch([]))
    provider = _NoQuotesProvider()
    result = _run(
        MOSTFunction(deps=FunctionDeps(yfinance=provider)).execute(
            asset_class="equities", live_screen=True, limit=100
        )
    )
    rows = result.data["rows"]
    universe_size = result.data["universe_size"]
    assert universe_size >= 50
    assert len(rows) == universe_size, "every scanned symbol must be emitted"
    assert all(row["quote_state"] == "unavailable" for row in rows)
    assert all(row["last"] is None and row["volume"] is None for row in rows)
    assert result.data["scanned"] == universe_size
    assert result.data["unavailable"] == universe_size
    assert result.data["resolved"] == 0
    assert result.data["status"] == "provider_unavailable"
    assert result.metadata.get("live") is True


# ──────────────────────────────────────────────────────────────────────────
# CSRC — full liquid futures complex
# ──────────────────────────────────────────────────────────────────────────


def test_csrc_commodity_universe_covers_full_complex() -> None:
    from showme.engine.functions.screen._funcs import _commodity_reference_rows

    rows = _commodity_reference_rows()
    symbols = [str(row["symbol"]) for row in rows]
    assert len(symbols) >= 20
    assert len(symbols) == len(set(symbols)), "universe must not contain duplicates"
    assert {"Energy", "Metals", "Grains", "Softs", "Livestock"} <= {
        str(row.get("sector")) for row in rows
    }
    for row in rows:
        assert row.get("name")
        assert row.get("exchange")
        assert row.get("contract_unit")
    for symbol in (
        "CL=F", "BZ=F", "NG=F", "RB=F", "HO=F",
        "GC=F", "SI=F", "HG=F", "PL=F", "PA=F",
        "ZC=F", "ZW=F", "ZS=F", "ZM=F", "ZL=F", "KE=F",
        "KC=F", "SB=F", "CC=F", "CT=F", "OJ=F",
        "LE=F", "HE=F", "GF=F",
    ):
        assert symbol in symbols, f"{symbol} missing from the commodity complex"
    # Verified-rejected tickers must not sneak back in:
    #   SRU=F  -> 404 on the public provider (probed 2026-09-15)
    #   LIT=F  -> resolves to the 2-Year Eris Swap Futures contract, NOT lithium
    assert "SRU=F" not in symbols
    assert "LIT=F" not in symbols
    assert "LTH=F" in symbols, "real lithium hydroxide contract must be present"
    assert "ALI=F" in symbols, "CME aluminum contract must be present"


def test_csrc_live_scan_covers_universe_and_labels_unresolved() -> None:
    from showme.engine.functions.screen._funcs import CSRCFunction, _commodity_reference_rows

    provider = _SelectiveQuotesProvider({"CL=F", "GC=F"})
    result = _run(
        CSRCFunction(FunctionDeps(yfinance=provider)).execute(query='sector = "Energy"')
    )
    universe_size = len(_commodity_reference_rows())
    assert result.data["scanned"] == universe_size
    assert provider.calls == universe_size, "the live scan must cover the whole complex"
    by_symbol = {row["symbol"]: row for row in result.data["rows"]}
    assert by_symbol["CL=F"]["quote_state"] == "live"
    assert by_symbol["BZ=F"]["quote_state"] == "reference", "unresolved rows stay, labelled"


# ──────────────────────────────────────────────────────────────────────────
# MOSS — expanded cross-asset default universe + honest partial scan
# ──────────────────────────────────────────────────────────────────────────


def test_moss_default_universe_is_cross_asset_and_live() -> None:
    from showme.engine.functions.misc._bonus import MOSSFunction, _moss_default_universe

    provider = _OhlcvProvider()
    result = _run(
        MOSSFunction(deps=FunctionDeps(yfinance=provider)).execute(live=True, limit=100)
    )
    universe = result.data["universe"]
    assert len(universe) >= 40
    assert universe == _moss_default_universe()
    assert provider.calls == len(universe)
    rows = result.data["rows"]
    assert len(rows) == len(universe)
    assert all(row.get("vol_annualized") is not None for row in rows)
    assert result.data["live"] is True


def test_moss_pending_symbols_emitted_as_unavailable(monkeypatch) -> None:
    from showme.engine.functions.misc._bonus import MOSSFunction

    provider = _OhlcvProvider(delay=5.0)
    result = _run(
        MOSSFunction(deps=FunctionDeps(yfinance=provider)).execute(
            live=True, limit=200, screen_timeout=0.5, quote_concurrency=2
        )
    )
    rows = result.data["rows"]
    universe = result.data["universe"]
    assert len(rows) == len(universe), "pending symbols must be emitted, not dropped"
    assert all(row.get("vol_annualized") is None for row in rows)
    assert all(row.get("state") == "unavailable" for row in rows)
    assert result.data.get("unavailable") == len(rows)


# ──────────────────────────────────────────────────────────────────────────
# Route defaults — the tiny hardcoded universes must stay lifted
# ──────────────────────────────────────────────────────────────────────────


def test_route_csrc_default_universe_is_full_complex(monkeypatch) -> None:
    from showme.engine.functions.screen._funcs import _commodity_reference_symbols

    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [
            server.FunctionIndexEntry(
                code="CSRC",
                name="Commodity Screener",
                category="screen",
                asset_classes=["COMMODITY"],
            ),
        ],
    )
    params = server._route_function_params("CSRC", {})
    assert params["universe"] == _commodity_reference_symbols()
    assert len(params["universe"]) >= 20


def test_route_moss_keeps_full_default_universe(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [
            server.FunctionIndexEntry(
                code="MOSS",
                name="Most Volatile",
                category="screen",
                asset_classes=["EQUITY"],
            ),
        ],
    )
    params = server._route_function_params("MOSS", {})
    assert "symbols" not in params, "route peer list must not restrict the MOSS universe"
    explicit = server._route_function_params("MOSS", {"symbols": ["AAPL", "MSFT"]})
    assert explicit.get("symbols") == ["AAPL", "MSFT"]
