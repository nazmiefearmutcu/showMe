"""Regression pins for BugHunt Session 02 without overwriting test_server.py."""

from __future__ import annotations

import asyncio


def test_brief_live_composes_from_top_items_and_returns_articles(monkeypatch) -> None:
    from showme.engine.core.base_function import FunctionResult
    from showme.engine.functions.news import top as top_mod
    from showme.engine.functions.news.brief import BRIEFFunction

    # 2026-06-01 contract change: BRIEF composes from TOP (live RSS/GDELT
    # headlines under the ``items`` key), not the READ reading-list store.
    class FakeTOP:
        def __init__(self, _deps):
            pass

        async def execute(self, **kwargs):
            assert kwargs["live"] is True
            sym = kwargs.get("symbol") or "MACRO"
            return FunctionResult(
                code="TOP",
                instrument=None,
                data={"items": [{
                    "title": f"{sym} supply-chain story",
                    "url": f"https://example.com/{sym}",
                    "matched_symbol": sym,
                    "source": "rss",
                    "summary": "<p>Apple &amp; suppliers raised guidance.</p>",
                }], "status": "ok"},
                sources=["rss"],
                metadata={"provider_errors": []},
            )

    monkeypatch.setattr(top_mod, "TOPFunction", FakeTOP)

    result = asyncio.run(BRIEFFunction().execute(live=True, watchlist=["AAPL"]))

    assert result.data["status"] == "ok"
    assert result.data["article_count"] >= 1
    assert "supply-chain story" in result.data["markdown"]
    assert any(
        a["summary"] == "Apple & suppliers raised guidance."
        for a in result.data["articles"]
    )


def test_brief_offline_returns_dict_with_markdown_key() -> None:
    """2026-06-01 contract change: the de-garbaged BRIEF composes from real live
    surfaces by default (READ/watchlist/TOP), and the only ``live=false`` path is
    an honest OPT-OUT that returns ``status="empty"`` with NO fabricated
    headlines — not the old ``"reference"`` template. The FunctionStub renderer
    still reads ``markdown`` in every branch, so the contract this test guards is
    that a ``markdown`` key is always present even offline.
    """
    from showme.engine.functions.news.brief import BRIEFFunction

    result = asyncio.run(BRIEFFunction().execute(live=False, watchlist=["AAPL", "MSFT"]))

    assert isinstance(result.data, dict)
    assert isinstance(result.data.get("markdown"), str)
    assert result.data["status"] == "empty"
    assert result.data["article_count"] == 0
    assert result.data["articles"] == []
    assert "AAPL" in result.data["watchlist"]
    assert "ShowMe Daily Brief" in result.data["markdown"]


def test_blak_offline_returns_dict_with_posterior_keys() -> None:
    from showme.engine.functions.portfolio.blak import BLAKFunction

    fn = BLAKFunction()
    with_symbols = asyncio.run(fn.execute(live=False, symbols=["AAPL", "MSFT", "GOOG", "META", "NVDA"]))
    assert isinstance(with_symbols.data, dict)
    for key in (
        "status",
        "rows",
        "market_weights",
        "posterior_returns",
        "implied_optimal_weights",
        "samples",
        "summary",
    ):
        assert key in with_symbols.data
    assert with_symbols.data["samples"] >= 60
    assert len(with_symbols.data["rows"]) == 5

    no_symbols = asyncio.run(fn.execute(live=False, symbols=[]))
    assert isinstance(no_symbols.data, dict)
    assert no_symbols.data == {}
    assert "symbols required" in (no_symbols.warnings or [])


def test_bmtx_offline_returns_matrix_template_dict() -> None:
    from showme.engine.functions.portfolio.bmtx import BMTXFunction

    result = asyncio.run(BMTXFunction().execute(live=False))

    assert isinstance(result.data, dict)
    for key in (
        "status",
        "symbols",
        "strategies",
        "cells",
        "surface",
        "best_per_symbol",
        "top_10_by_sharpe",
        "summary",
    ):
        assert key in result.data
    assert isinstance(result.data["cells"], list)
    assert len(result.data["cells"]) > 0
    for cell_key in ("symbol", "strategy", "sharpe", "total_return"):
        assert cell_key in result.data["cells"][0]


def test_btfw_offline_returns_equity_curve_dict() -> None:
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.functions.portfolio.btfw import BTFWFunction

    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    result = asyncio.run(BTFWFunction().execute(instrument=inst, live=False, strategy="buy_and_hold"))

    assert isinstance(result.data, dict)
    for key in ("status", "symbol", "strategy", "metrics", "final_equity", "equity_curve", "summary"):
        assert key in result.data
    assert result.data["symbol"] == "AAPL"
    assert result.data["strategy"] == "buy_and_hold"
    assert isinstance(result.data["equity_curve"], list)
    assert len(result.data["equity_curve"]) > 0
