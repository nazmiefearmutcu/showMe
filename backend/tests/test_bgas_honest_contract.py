"""BGAS honesty: identity, contract handling, inputs and output fields.

BGAS is the Henry Hub natural-gas spot monitor (handler, pane and EIA branch
all say natural gas). It must never serve another instrument's rows under its
own name, and must never substitute NG=F for a contract it was asked for.

Network is never used: yfinance and EIA are replaced by in-memory fakes.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.commodity._funcs import (
    BGASFunction,
    NGASFunction,
    _ng_front_month,
)
from showme.manifest import REGISTRY, load_seeds


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _Yahoo:
    """Quote-only yfinance stand-in that records every request it receives."""

    def __init__(self, last: float = 2.5) -> None:
        self.last = last
        self.requests: list[Any] = []

    async def fetch(self, request: Any) -> Any:
        self.requests.append(request)
        if request.kind.name == "QUOTE":
            return SimpleNamespace(
                last=self.last,
                close_prev=self.last - 0.1,
                high_24h=self.last + 0.05,
                low_24h=self.last - 0.05,
                open_24h=self.last,
                volume_24h=1000.0,
                source="yfinance",
                timestamp=datetime(2026, 11, 6, 21, 0, tzinfo=UTC),
            )
        return pd.DataFrame()  # no history bars


class _EiaSeries:
    """EIA-shaped adapter returning a Henry Hub frame, and recording calls."""

    def __init__(self) -> None:
        self.calls = 0
        self.frame = pd.DataFrame(
            {"value": [3.20, 3.10], "series": ["RNGWHHD"] * 2, "units": ["$/MMBtu"] * 2},
            index=pd.to_datetime(["2026-09-10", "2026-09-09"]),
        )

    async def fetch(self, request: Any) -> Any:
        self.calls += 1
        return self.frame


def _symbols(data: dict[str, Any]) -> list[str]:
    return [str(row.get("symbol")) for row in data.get("rows", [])]


# ── BGAS#3: identity is natural gas, non-NG contracts are refused ─────────


@pytest.mark.parametrize("contract", ["RB=F", "HO=F", "BZ=F", "CL=F"])
def test_non_gas_contract_is_refused_not_served_as_natural_gas(contract: str) -> None:
    """Pre-fix: RB=F/CL=F returned status ok under the natural-gas title."""
    fn = BGASFunction(deps=FunctionDeps(yfinance=_Yahoo()))
    result = _run(fn.execute(contract=contract))
    assert result.data["status"] == "input_error", result.data
    assert result.data["rows"] == []
    assert contract in str(result.data.get("reason", ""))
    assert "natural gas" in str(result.data.get("reason", "")).lower()


def test_ng_contract_is_served_from_yahoo_quote() -> None:
    fn = BGASFunction(deps=FunctionDeps(yfinance=_Yahoo(last=3.1)))
    result = _run(fn.execute(contract="NG=F"))
    assert result.data["status"] == "ok"
    assert _symbols(result.data) == ["NG=F"]


# ── BGAS#4: EIA branch serves Henry Hub only for the NG contract ──────────


def test_eia_branch_does_not_answer_for_rb_contract() -> None:
    """Pre-fix: RB=F with EIA configured returned HENRYHUB as status ok."""
    eia = _EiaSeries()
    fn = BGASFunction(deps=FunctionDeps(eia=eia))
    result = _run(fn.execute(contract="RB=F"))
    assert result.data["status"] == "input_error"
    assert "HENRYHUB" not in _symbols(result.data)
    assert eia.calls == 0


def test_eia_branch_still_serves_natural_gas_contract() -> None:
    eia = _EiaSeries()
    fn = BGASFunction(deps=FunctionDeps(eia=eia))
    result = _run(fn.execute(contract="NG=F"))
    assert result.data["status"] == "ok"
    assert result.data["source_mode"] == "live_eia"
    assert _symbols(result.data) == ["HENRYHUB"]


# ── BGAS#6: live=false never swaps the contract for NG=F ──────────────────


def test_model_fallback_does_not_replace_requested_contract() -> None:
    """Pre-fix: live=false with RB=F returned an NG=F reference row."""
    fn = BGASFunction(deps=FunctionDeps())
    result = _run(fn.execute(contract="RB=F", live=False))
    assert result.data["status"] == "input_error"
    assert "NG=F" not in _symbols(result.data)


def test_model_fallback_for_ng_contract_is_labelled_reference() -> None:
    fn = BGASFunction(deps=FunctionDeps())
    result = _run(fn.execute(contract="NG=F", live=False))
    assert result.data["status"] == "reference_model"
    assert result.data["source_mode"] == "model"
    assert _symbols(result.data) == ["NG=F"]


def test_ngas_alias_inherits_the_same_contract_rule() -> None:
    fn = NGASFunction(deps=FunctionDeps(yfinance=_Yahoo()))
    result = _run(fn.execute(contract="CL=F"))
    assert result.data["status"] == "input_error"


# ── seed identity ─────────────────────────────────────────────────────────


def test_bgas_seed_describes_natural_gas_not_gasoline() -> None:
    load_seeds()
    manifest = REGISTRY.get("BGAS")
    text = " ".join([manifest.name, manifest.intent, manifest.methodology]).lower()
    assert "gasoline" not in text
    assert "rbob" not in text
    contract = next(spec for spec in manifest.inputs if spec.name == "contract")
    assert list(contract.options or []) == ["NG=F"]
    assert manifest.defaults["contract"] == "NG=F"


# ── expiry helper (used by BGAS#5) ────────────────────────────────────────


def test_front_month_rolls_after_last_trade_day() -> None:
    # Nov 2026 contract expired ~Oct 28; Dec 2026 last trades Nov 26 (Thanksgiving
    # not modelled, weekends only); Jan 2027 last trades Dec 29.
    assert _ng_front_month(date(2026, 11, 8)) == ("2026-12", "2026-11-26")
    assert _ng_front_month(date(2026, 11, 27)) == ("2027-01", "2026-12-29")


# ── BGAS#5: advertised inputs are read; output carries unit/expiry/mode ──


def test_rows_and_envelope_carry_unit_expiry_and_mode() -> None:
    """Pre-fix: rows had no expiry_month / contract_unit and the envelope had
    no data_mode, although the output contract lists them as must-have."""
    fn = BGASFunction(deps=FunctionDeps(yfinance=_Yahoo(last=3.1)))
    result = _run(fn.execute(contract="NG=F"))
    data = result.data
    assert data["contract"] == "NG=F"
    assert data["contract_unit"] == "USD/MMBtu"
    assert data["data_mode"] == "live_yfinance"
    assert data["expiry_month"] == _ng_front_month(datetime.now(UTC).date())[0]
    assert data["expiry_month"] is not None and len(data["expiry_month"]) == 7
    row = data["rows"][0]
    assert row["contract_unit"] == "USD/MMBtu"
    assert row["expiry_month"] == data["expiry_month"]
    assert row["data_mode"] == "live_yfinance"
    assert "candles" in data


def test_eia_spot_rows_have_no_delivery_month() -> None:
    fn = BGASFunction(deps=FunctionDeps(eia=_EiaSeries()))
    result = _run(fn.execute(contract="NG=F"))
    row = result.data["rows"][0]
    assert row["expiry_month"] is None
    assert row["expiry_basis"] == "spot_no_delivery_month"
    assert result.data["data_mode"] == "live_official"


def test_range_is_read_when_days_is_not_given() -> None:
    """Pre-fix: range was advertised but never read; the history length was
    always the days default. range=3M must request about 91 daily bars."""
    yahoo = _Yahoo()
    fn = BGASFunction(deps=FunctionDeps(yfinance=yahoo))
    _run(fn.execute(contract="NG=F", range="3M"))
    ohlcv = [r for r in yahoo.requests if r.kind.name == "OHLCV"]
    assert ohlcv, "history request expected"
    assert ohlcv[0].limit == 91


def test_unsupported_range_is_refused_not_defaulted() -> None:
    fn = BGASFunction(deps=FunctionDeps(yfinance=_Yahoo()))
    result = _run(fn.execute(contract="NG=F", range="MAX"))
    assert result.data["status"] == "input_error"
    assert "MAX" in str(result.data.get("reason", ""))


def test_intraday_interval_is_refused_not_ignored() -> None:
    """Pre-fix: interval=1h was accepted and served as daily bars."""
    fn = BGASFunction(deps=FunctionDeps(yfinance=_Yahoo()))
    result = _run(fn.execute(contract="NG=F", interval="1h"))
    assert result.data["status"] == "input_error"
    assert "daily" in str(result.data.get("reason", "")).lower()


def test_provider_mode_is_no_longer_an_unread_input() -> None:
    manifest = REGISTRY.get("BGAS")
    assert "provider_mode" not in [spec.name for spec in manifest.inputs]


# ── BGAS#7: catalog description is written, not the template ─────────────


def test_catalog_description_is_real_text() -> None:
    """Pre-fix: description was empty, so the catalog purpose became the
    template 'Natural Gas Spot function.'."""
    description = BGASFunction.description
    assert description.strip()
    assert "function." not in description.lower()
    assert "natural gas" in description.lower()


# ── BGAS residual: model row expiry follows the price vintage, not render date ──


def test_model_row_expiry_matches_reference_vintage_not_render_date() -> None:
    """The NG=F reference row is priced at its 2024-06 vintage. Its expiry must
    be the front month as of that vintage (2024-07), not the front month of
    today's render date, which would pair a 2024 price with a 2026 contract."""
    fn = BGASFunction(deps=FunctionDeps())
    result = _run(fn.execute(contract="NG=F", live=False))
    row = result.data["rows"][0]
    assert row["as_of"] == "2024-06"
    assert row["expiry_month"] == "2024-07"
    assert row["expiry_last_trade"] == "2024-06-26"
    assert result.data["expiry_month"] == "2024-07"


def test_model_row_with_unparseable_vintage_has_no_expiry() -> None:
    from showme.engine.functions.commodity import _funcs

    rows = _funcs._bgas_decorate_rows(
        [{"symbol": "NG=F", "source_mode": "model", "source": "commodity_reference_model",
          "as_of": "not-a-date"}],
        as_of_day=date(2026, 11, 8),
    )
    assert rows[0]["expiry_month"] is None
    assert rows[0]["expiry_basis"] == "unknown_price_vintage"
