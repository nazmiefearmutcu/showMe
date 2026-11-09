"""RV#4 — the seed's promised ratios filter, FCF yield and card/table keys.

The seed promised a ``ratios`` filter, an FCF yield column and card slots whose
keys the handler never emitted. These tests pin: the filter really restricts
the table, unknown names are reported, FCF yield is freeCashflow over market
cap (negative FCF stays negative, missing input stays None), and every card
slot and table column key is present in the payload. Network is replaced by
in-memory fakes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.rv import RVFunction
from showme.manifest import REGISTRY, load_seeds


def _raw(pe: float, *, fcf: float | None = None, mcap: float = 1.0e11) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "trailingPE": pe,
        "forwardPE": pe * 0.9,
        "priceToBook": 4.0,
        "priceToSalesTrailing12Months": 2.0,
        "enterpriseToEbitda": 12.0,
        "returnOnEquity": 0.2,
        "returnOnAssets": 0.05,
        "debtToEquity": 50.0,
        "marketCap": mcap,
        "dividendYield": 1.0,
        "dividendRate": 1.0,
        "currentPrice": 100.0,
    }
    if fcf is not None:
        raw["freeCashflow"] = fcf
    return raw


class _YF:
    def __init__(self, by_symbol: dict[str, dict[str, Any]]) -> None:
        self._by = by_symbol

    async def fetch(self, request: Any) -> Any:
        raw = self._by.get(request.instrument.symbol, {})
        return SimpleNamespace(market_cap=None, extras={"raw": dict(raw)})


def _run(by_symbol: dict[str, dict[str, Any]], peers: list[str], **params: Any) -> Any:
    fn = RVFunction(SimpleNamespace(yfinance=_YF(by_symbol), finnhub=None))
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(fn.execute(instrument=inst, peers=peers, **params))


def _four_names(aapl_fcf: float | None = 2.0e10) -> dict[str, dict[str, Any]]:
    return {
        "AAPL": _raw(30.0, fcf=aapl_fcf),
        "MSFT": _raw(10.0, fcf=5.0e9),
        "GOOG": _raw(20.0, fcf=1.0e10),
        "AMZN": _raw(40.0, fcf=-2.0e9),
    }


_PEERS = ["MSFT", "GOOG", "AMZN"]


def test_ratios_filter_restricts_rows_and_medians() -> None:
    result = _run(_four_names(), _PEERS, ratios=["pe_ttm", "fcf_yield"])
    assert result.data["status"] == "ok"
    assert result.data["ratios"] == ["fcf_yield", "pe"]
    for row in result.data["rows"]:
        assert "pe_ttm" in row and "fcf_yield" in row
        assert "ev_ebitda" not in row and "dividend_yield" not in row and "pb" not in row
        assert "roe" not in row and "fwd_pe" not in row
    assert set(result.data["peer_median"]) <= {"pe", "fcf_yield"}
    # The P/E premium is a headline figure and is reported regardless of the filter.
    assert result.data["pe_vs_peer_pct"] is not None


def test_no_ratios_param_keeps_every_ratio() -> None:
    result = _run(_four_names(), _PEERS)
    assert result.data["ratios"] is None
    row = next(r for r in result.data["rows"] if r["symbol"] == "AAPL")
    for key in ("pe_ttm", "ev_ebitda", "ps_ttm", "pb", "dividend_yield", "fcf_yield", "roe"):
        assert key in row, key


def test_unknown_ratio_names_are_reported_and_ignored() -> None:
    result = _run(_four_names(), _PEERS, ratios="pe_ttm, bogus_ratio")
    assert result.data["ratios"] == ["pe"]
    assert any("bogus_ratio" in w for w in result.warnings), result.warnings


def test_fcf_yield_is_free_cash_flow_over_market_cap() -> None:
    result = _run(_four_names(aapl_fcf=2.0e10), _PEERS)
    row = next(r for r in result.data["rows"] if r["symbol"] == "AAPL")
    assert row["fcf_yield"] == 0.2  # 2e10 / 1e11, a decimal fraction
    peer = next(r for r in result.data["rows"] if r["symbol"] == "AMZN")
    assert peer["fcf_yield"] < 0  # negative free cash flow stays negative


def test_fcf_yield_is_none_when_free_cash_flow_is_missing() -> None:
    result = _run(_four_names(aapl_fcf=None), _PEERS)
    row = next(r for r in result.data["rows"] if r["symbol"] == "AAPL")
    assert row["fcf_yield"] is None


def test_own_pe_and_data_mode_are_in_the_payload() -> None:
    result = _run(_four_names(), _PEERS)
    assert result.data["own_pe"] == 30.0
    assert result.data["data_mode"] == "live_yfinance"
    assert result.data["peer_median_pe"] == 20.0


def test_unavailable_state_has_no_own_pe_and_says_so() -> None:
    result = _run({}, _PEERS)
    assert result.data["status"] == "provider_unavailable"
    assert result.data["own_pe"] is None
    assert result.data["data_mode"] == "provider_unavailable"


def test_every_seed_card_slot_key_is_emitted_by_the_handler() -> None:
    load_seeds()
    rv = REGISTRY.get("RV")
    result = _run(_four_names(), _PEERS)
    slot_keys = {slot.key for slot in rv.card_schema.slots}
    missing = slot_keys - set(result.data)
    assert not missing, f"RV card slots with no payload key: {sorted(missing)}"


def test_every_seed_table_column_key_is_in_each_row() -> None:
    load_seeds()
    rv = REGISTRY.get("RV")
    result = _run(_four_names(), _PEERS)
    column_keys = {col.key for col in rv.table_schema.columns} - {"symbol"}
    for row in result.data["rows"]:
        missing = column_keys - set(row)
        assert not missing, f"row {row.get('symbol')} lacks table columns {sorted(missing)}"
