"""MAP world market heatmap rewrite (2026-09-15) — fan-out honesty pins.

The pane previously fanned out 25 slow ``deps.yfinance`` fetches under a 5 s
screen budget and silently dropped every symbol that had not finished. The
rewrite fans out over the fast keyless ``showme.quotes`` service with a
bounded semaphore (8) and keeps contract-level honesty:

  * a failed or timed-out symbol is STILL emitted as a
    ``quote_type="unavailable"`` row — the market list never shrinks to the
    symbols that finished in time;
  * if no symbol produced a live last, the deterministic template fallback
    (status ``provider_unavailable``) ships instead — unchanged shape;
  * BIST/İstanbul (``XU100.IS``) is part of the expanded market map.
"""
from __future__ import annotations

import asyncio
import types
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.screen import wmap
from showme.engine.functions.screen.wmap import MAPFunction

FULL_SIZE = len(wmap._COUNTRY_ETFS)


def _snapshot(last: float | None, prev: float | None) -> dict[str, Any]:
    return {"last": last, "previous_close": prev}


async def test_failed_symbols_still_render_as_unavailable_rows(monkeypatch: Any) -> None:
    """A raising provider must not shorten the row list: the failed market is
    emitted with ``last=None`` / ``change_pct=None`` / ``quote_type``
    ``unavailable`` and the metadata reports the count."""

    async def _fake(symbol: str) -> dict[str, Any]:
        if symbol == "SPY":
            return _snapshot(105.0, 100.0)
        raise RuntimeError(f"provider down for {symbol}")

    monkeypatch.setattr(wmap, "fetch_quote_snapshot", _fake)
    res = await MAPFunction(FunctionDeps()).execute(live=True, screen_timeout=4)

    assert res.data["status"] == "ok"
    rows = res.data["rows"]
    assert len(rows) == FULL_SIZE
    by_etf = {row["etf"]: row for row in rows}
    assert by_etf["SPY"]["quote_type"] == "live"
    assert by_etf["SPY"]["change_pct"] == pytest.approx(5.0)
    failed = by_etf["EWG"]
    assert failed["quote_type"] == "unavailable"
    assert failed["last"] is None
    assert failed["change_pct"] is None
    errors = res.metadata.get("provider_errors") or []
    assert any("unavailable" in str(e) for e in errors), errors


async def test_all_symbols_failing_ships_template_fallback(monkeypatch: Any) -> None:
    """No live last at all → the unchanged ``provider_unavailable`` envelope
    with the deterministic template rows (never a silently empty list)."""

    async def _boom(symbol: str) -> dict[str, Any]:
        raise RuntimeError("quote service down")

    monkeypatch.setattr(wmap, "fetch_quote_snapshot", _boom)
    res = await MAPFunction(FunctionDeps()).execute(live=True, screen_timeout=4)

    assert res.data["status"] == "provider_unavailable"
    assert res.data["period"] == "1D"
    assert len(res.data["rows"]) == FULL_SIZE
    assert all(row["quote_type"] == "model" for row in res.data["rows"])
    assert res.metadata.get("fallback") is True
    assert res.metadata.get("degraded") is True
    assert "world_market_model" in res.sources


async def test_bist_row_is_present_and_quotes_xu100(monkeypatch: Any) -> None:
    """BIST (İstanbul) is a first-class market in the expanded map."""
    seen: list[str] = []

    async def _fake(symbol: str) -> dict[str, Any]:
        seen.append(symbol)
        return _snapshot(100.0, 100.0)

    monkeypatch.setattr(wmap, "fetch_quote_snapshot", _fake)
    res = await MAPFunction(FunctionDeps()).execute(live=True, screen_timeout=4)

    assert len(wmap._COUNTRY_ETFS) >= 45
    rows = {row["country"]: row for row in res.data["rows"]}
    assert rows["BIST"]["etf"] == "XU100.IS"
    assert "XU100.IS" in seen


async def test_change_pct_sign_and_sort_for_stubbed_pairs(monkeypatch: Any) -> None:
    """change_pct = last/prev - 1 (in % units, signed); rows sort desc with
    null-change rows last."""

    async def _fake(symbol: str) -> dict[str, Any]:
        quotes = {
            "SPY": (110.0, 100.0),  # +10%
            "EWZ": (90.0, 100.0),   # -10%
            "EWJ": (100.0, 100.0),  # 0%
            "VGK": (50.0, None),    # no prev leg -> null change
        }
        last, prev = quotes.get(symbol, (100.0, 100.0))
        return _snapshot(last, prev)

    monkeypatch.setattr(wmap, "fetch_quote_snapshot", _fake)
    res = await MAPFunction(FunctionDeps()).execute(live=True, screen_timeout=4)

    by_etf = {row["etf"]: row for row in res.data["rows"]}
    assert by_etf["SPY"]["change_pct"] == pytest.approx(10.0)
    assert by_etf["EWZ"]["change_pct"] == pytest.approx(-10.0)
    assert by_etf["EWJ"]["change_pct"] == pytest.approx(0.0)
    assert by_etf["VGK"]["change_pct"] is None
    # A live last with an unknown change leg stays "live" (only the change is
    # withheld) — same provenance semantics as the pre-rewrite row contract.
    assert by_etf["VGK"]["quote_type"] == "live"

    order = [row["etf"] for row in res.data["rows"]]
    assert order.index("SPY") < order.index("EWJ") < order.index("EWZ")
    assert order.index("EWZ") < order.index("VGK")


async def test_pending_symbols_still_render_a_row(monkeypatch: Any) -> None:
    """The core regression: symbols that miss the screen deadline are
    cancelled but STILL emitted as ``unavailable`` rows.

    ``wmap.asyncio`` is shimmed to force a near-instant deadline so the test
    does not sit on the real 4 s floor; everything else is the production
    code path (semaphore, task fan-out, cancel + emit).
    """

    async def _fake(symbol: str) -> dict[str, Any]:
        if symbol == "SPY":
            return _snapshot(110.0, 100.0)
        await asyncio.sleep(30)
        return _snapshot(100.0, 100.0)

    async def _fast_wait(tasks: Any, timeout: float | None = None) -> Any:
        return await asyncio.wait(tasks, timeout=0.2)

    shim = types.SimpleNamespace(
        Semaphore=asyncio.Semaphore,
        create_task=asyncio.create_task,
        wait=_fast_wait,
    )
    monkeypatch.setattr(wmap, "fetch_quote_snapshot", _fake)
    monkeypatch.setattr(wmap, "asyncio", shim)  # type: ignore[arg-type]
    res = await MAPFunction(FunctionDeps()).execute(live=True, screen_timeout=12)

    assert res.data["status"] == "ok"
    rows = res.data["rows"]
    assert len(rows) == FULL_SIZE
    by_etf = {row["etf"]: row for row in rows}
    assert by_etf["SPY"]["quote_type"] == "live"
    assert by_etf["SPY"]["change_pct"] == pytest.approx(10.0)
    # Every non-SPY symbol missed the deadline — still rendered, never dropped.
    assert by_etf["EWZ"]["quote_type"] == "unavailable"
    assert by_etf["EWZ"]["last"] is None
    errors = res.metadata.get("provider_errors") or []
    assert errors and "unavailable" in str(errors[0])
