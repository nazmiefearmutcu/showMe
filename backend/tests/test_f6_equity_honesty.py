"""F6 campaign — equity-fundamentals honesty regressions.

Pins the F6 fixes for the CRITICAL/HIGH audit findings:

* EREV must never substitute fabricated analyst buckets when Finnhub is
  absent/failed — the outage path is a labelled ``provider_unavailable``
  envelope with an empty trend and no ``finnhub`` source claim.
* DVD Model mode must return real reference rows labelled ``model`` (not a
  bare template dict that renders as "No corporate actions").
* CDE evaluate must keep the store truth (``count`` + stored rows) rather
  than repurposing ``count=1`` and hiding every stored field.
* ESG's SEC-EDGAR text proxy must stay visibly labelled (counts, not risk
  scores) so the pane can relabel its KPI captions.
"""

from __future__ import annotations

import pytest

import asyncio
import json
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument


def _run(coro):
    return asyncio.run(coro)


def _instrument(symbol: str = "AAPL") -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)


# ---------------------------------------------------------------------------
# EREV — no fabricated analyst buckets
# ---------------------------------------------------------------------------


def test_erev_without_provider_returns_unavailable_empty_trend():
    from showme.engine.functions.equity.erev import EREVFunction

    result = _run(EREVFunction(FunctionDeps()).execute(instrument=_instrument("AAPL")))
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert data["trend"] == []
    assert data["rows"] == []
    assert result.sources == [], "no provider produced data — sources must not claim one"
    assert result.warnings, "the outage must be visibly flagged"
    assert result.metadata.get("fallback") is True
    assert result.metadata.get("live") is False
    # The fabricated buckets were three "2026-0x" months — pin their absence.
    assert not any(isinstance(r, dict) and "strongBuy" in r for r in data["rows"])


def test_erev_failed_provider_never_claims_finnhub_source():
    from showme.engine.functions.equity.erev import EREVFunction

    class _BoomFinnhub:
        async def recommendations(self, symbol: str) -> Any:
            raise RuntimeError("rate limited")

    result = _run(
        EREVFunction(FunctionDeps(finnhub=_BoomFinnhub())).execute(
            instrument=_instrument("AAPL")
        )
    )
    assert result.data["status"] == "provider_unavailable"
    assert result.data["trend"] == []
    assert "finnhub" not in result.sources
    assert result.metadata.get("fallback") is True
    assert any("rate limited" in w for w in result.warnings)


def test_erev_live_provider_returns_weighted_trend():
    from showme.engine.functions.equity.erev import EREVFunction

    class _FakeFinnhub:
        async def recommendations(self, symbol: str) -> list[dict[str, Any]]:
            return [
                {"period": "2026-02", "strongBuy": 2, "buy": 3, "hold": 5, "sell": 0, "strongSell": 0},
                {"period": "2026-03", "strongBuy": 4, "buy": 4, "hold": 2, "sell": 0, "strongSell": 0},
            ]

    result = _run(
        EREVFunction(FunctionDeps(finnhub=_FakeFinnhub())).execute(
            instrument=_instrument("AAPL")
        )
    )
    assert result.data["status"] == "ok"
    assert result.sources == ["finnhub"]
    assert result.metadata.get("live") is True
    assert result.metadata.get("data_mode") == "live_official"
    trend = result.data["trend"]
    assert len(trend) == 2
    # 4*2 + 4*1 + 2*0 = 12 -> avg 12/10 = 1.2
    assert trend[-1]["score"] == 12
    assert abs(trend[-1]["avg"] - 1.2) < 1e-9


# ---------------------------------------------------------------------------
# RV — negative P/E is N/A, not "cheapest" (HNT-11)
# ---------------------------------------------------------------------------


def test_rv_negative_pe_is_excluded_from_ranking():
    from showme.engine.functions.equity.rv import _rank_rows

    rows = [
        {"symbol": "LOSSMAKER", "pe": -5.0},
        {"symbol": "CHEAP", "pe": 8.0},
        {"symbol": "PRICEY", "pe": 40.0},
        {"symbol": "NOPE", "pe": None},
    ]
    ranked = _rank_rows(rows, "LOSSMAKER")
    by_symbol = {r["symbol"]: r for r in ranked}
    # Positive PEs keep their ascending rank / percentile.
    assert by_symbol["CHEAP"]["rank_pe"] == 1
    assert by_symbol["CHEAP"]["percentile_pe"] == 0.0
    assert by_symbol["PRICEY"]["rank_pe"] == 2
    assert by_symbol["PRICEY"]["percentile_pe"] == 100.0
    # The loss-maker and the missing-PE row are rank-excluded (raw value
    # still visible) — never ranked as the cheapest name in the set.
    assert "rank_pe" not in by_symbol["LOSSMAKER"]
    assert "percentile_pe" not in by_symbol["LOSSMAKER"]
    assert "rank_pe" not in by_symbol["NOPE"]


# ---------------------------------------------------------------------------
# DVD — Model mode returns labelled reference rows
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CDE — evaluate keeps the store truth
# ---------------------------------------------------------------------------


def test_cde_evaluate_keeps_stored_count_and_rows(monkeypatch, tmp_path):
    import showme.engine.functions.misc.cde as cde_mod

    store_path = tmp_path / "cde_fields.json"
    monkeypatch.setattr(cde_mod, "_store", lambda: store_path)
    fn = cde_mod.CDEFunction(FunctionDeps())

    _run(fn.execute(None, action="add", name="cheap_quality", formula="pe < 25"))
    _run(fn.execute(None, action="add", name="low_beta", formula="beta < 1.2"))
    result = _run(
        fn.execute(None, action="evaluate", name="cheap_quality", row={"pe": 18})
    )
    data = result.data
    assert data["status"] == "ready"
    assert data["count"] == 2, "the Stored fields KPI must report the real store size"
    names = {r["name"] for r in data["rows"]}
    assert names == {"cheap_quality", "low_beta"}, "evaluate must not hide stored fields"
    assert data["evaluation"]["value"] is True


def test_cde_store_write_is_atomic(monkeypatch, tmp_path):
    """F6 [L]: write-temp + os.replace leaves no partial/tmp artifact."""
    import showme.engine.functions.misc.cde as cde_mod

    store_path = tmp_path / "cde_fields.json"
    monkeypatch.setattr(cde_mod, "_store", lambda: store_path)
    fn = cde_mod.CDEFunction(FunctionDeps())

    _run(fn.execute(None, action="add", name="x", formula="pe < 10"))
    assert json.loads(store_path.read_text()) == {"x": "pe < 10"}
    assert list(tmp_path.glob("*.tmp")) == [], "temp write must be renamed away"


# ---------------------------------------------------------------------------
# ESG — proxy counts stay labelled (pane relabels captions off this contract)
# ---------------------------------------------------------------------------


def test_esg_proxy_path_labels_counts_not_scores(monkeypatch):
    import showme.engine.functions.equity.esg as esg_mod
    from showme.engine.functions.equity.esg import ESGFunction

    async def fake_counts(symbol: str) -> dict[str, int]:
        return {"environment": 3, "social": 5, "governance": 7}

    monkeypatch.setattr(esg_mod, "_fetch_proxy_counts", fake_counts)
    result = _run(ESGFunction(FunctionDeps()).execute(instrument=_instrument("ZZZZ")))
    data = result.data
    assert data["status"] == "ok"
    assert data["rows"][0]["source_mode"] == "sec_text_proxy"
    assert data["rows"][0]["scale"] == "filing mentions (proxy)"
    assert data["warnings"], "proxy counts must carry the derived-signal warning"
    assert "not risk scores" in data["warnings"][0]


@pytest.fixture(autouse=True)
def _awareness_offline(monkeypatch):
    """Tests never hit the live awareness-markets service; injected fakes still win."""
    from showme.engine.data_sources.awareness import AwarenessUnavailable
    from showme.engine.functions.calendar import _common as _aw_common

    class _Offline:
        async def get(self, path, params=None):
            raise AwarenessUnavailable("awareness disabled in tests")

    monkeypatch.setattr(_aw_common, "get_awareness_client", lambda: _Offline())
