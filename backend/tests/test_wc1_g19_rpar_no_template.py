"""WC1-G19 RPAR#2: the default and live-off paths never serve synthetic weights.

The reported defect was a cosine template reaching the pane default view with a
false "yfinance returned insufficient history" reason. These tests pin every path
that can reach an allocation without measured returns: each must return an
explicit state with no weights, must not call the template generator, and must
not claim a yfinance result when yfinance was never called.

No network: yfinance is a recording fake and the Yahoo fallback is patched.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio import rpar as rpar_mod
from showme.engine.functions.portfolio.rpar import RPARFunction


class _RecordingYfinance:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, *_args: Any, **_kwargs: Any) -> pd.DataFrame:  # pragma: no cover - must not run
        self.calls += 1
        raise AssertionError("yfinance must not be read on this path")


@pytest.fixture()
def no_template(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_a: Any, **_kw: Any) -> pd.DataFrame:
        raise AssertionError("RPAR must not build weights from _template_returns")

    monkeypatch.setattr(rpar_mod, "_template_returns", _forbidden)

    async def _no_yahoo(*_a: Any, **_kw: Any) -> pd.Series:
        raise AssertionError("Yahoo fallback must not run on this path")

    monkeypatch.setattr(rpar_mod, "_yahoo_daily_returns", _no_yahoo)


def _assert_no_allocation(data: dict[str, Any]) -> None:
    assert data["status"] in {"needs_input", "provider_unavailable"}
    assert data["reason"]
    assert data["next_actions"]
    assert data["weights"] == {}
    assert data["rows"] == []
    assert data["portfolio_vol"] is None
    assert data["gross_exposure"] is None


def test_source_never_references_the_template_generator() -> None:
    source = inspect.getsource(RPARFunction.execute)
    assert "_template_returns" not in source


def test_pane_default_live_off_is_explicit_model_request(no_template: None) -> None:
    # The pane sends live_risk=false together with model=true (live toggle off).
    fake = _RecordingYfinance()
    out = asyncio.run(
        RPARFunction(FunctionDeps(yfinance=fake)).execute(
            symbols="AAPL,MSFT,GC=F", method="erc", live_risk=False, model=True, risk_target=0.10
        )
    )
    _assert_no_allocation(out.data)
    assert out.data["status"] == "needs_input"
    assert out.metadata["fallback_reason"] == "model_requested"
    assert out.sources == []
    assert fake.calls == 0


def test_live_off_without_model_flag_reports_live_disabled_not_insufficient_history(
    no_template: None,
) -> None:
    fake = _RecordingYfinance()
    out = asyncio.run(
        RPARFunction(FunctionDeps(yfinance=fake)).execute(
            symbols="AAPL,MSFT,GC=F", method="erc", live_risk=False
        )
    )
    _assert_no_allocation(out.data)
    assert out.data["status"] == "needs_input"
    assert out.metadata["fallback_reason"] == "live_disabled"
    assert "live_risk=false" in out.data["reason"]
    # yfinance was never called, so no claim about what it returned is allowed.
    assert "insufficient" not in out.data["reason"]
    assert "insufficient" not in " ".join(out.warnings)
    assert fake.calls == 0
    assert out.sources == []


def test_default_without_yfinance_is_provider_unavailable_not_a_template(no_template: None) -> None:
    out = asyncio.run(RPARFunction().execute(symbols="AAPL,MSFT", method="erc"))
    _assert_no_allocation(out.data)
    assert out.data["status"] == "provider_unavailable"
    assert out.metadata["fallback_reason"] == "yfinance_unavailable"
    assert "insufficient" not in out.data["reason"]
    assert out.sources == []
