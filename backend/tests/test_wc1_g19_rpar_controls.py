"""WC1-G19 RPAR#5: the manifest controls are honoured or disclosed, never silently ignored.

lookback_window maps to the history window when days is absent, risk_budget sets the
ERC risk shares, frequency accepts only the daily closes RPAR fetches, and paper_mode
is reported with its real effect (RPAR has no order path).

No network: market data is a deterministic fake that records every request.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.rpar import RPARFunction
from showme.manifest import REGISTRY, load_seeds


class _RecordingYfinance:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def fetch(self, request: Any, *_args: Any, **_kwargs: Any) -> pd.DataFrame:
        self.requests.append(request)
        symbol = request.instrument.symbol
        seed = sum(ord(ch) for ch in symbol)
        rng = np.random.default_rng(seed)
        n = 320
        vol = 0.008 + (seed % 7) * 0.003
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, vol, n)))
        idx = pd.bdate_range(end="2026-10-30", periods=n)
        return pd.DataFrame({"close": close}, index=idx)


def _run(**params: Any):
    fake = _RecordingYfinance()
    out = asyncio.run(RPARFunction(FunctionDeps(yfinance=fake)).execute(**params))
    return out, fake


def _age_days(request: Any) -> int:
    return (datetime.now(timezone.utc) - request.start).days


def _shares(out: Any) -> dict[str, float]:
    return {row["symbol"]: row["risk_contribution_pct"] for row in out.data["rows"]}


# ----------------------------- frequency -----------------------------------

def test_unsupported_frequency_is_an_explicit_input_error() -> None:
    out, fake = _run(symbols="AAA,BBB,CCC", method="erc", frequency="1wk")
    assert out.data["status"] == "input_error"
    assert "daily" in out.data["reason"]
    assert fake.requests == []
    assert not out.data.get("weights")


def test_daily_frequency_is_accepted_and_reported() -> None:
    out, _ = _run(symbols="AAA,BBB,CCC", method="erc", frequency="1d")
    assert out.data["portfolio_vol"] is not None
    assert out.data["controls"]["frequency"] == "1d"


# ----------------------------- lookback_window ------------------------------

def test_lookback_window_sets_the_history_window_when_days_is_absent() -> None:
    out, fake = _run(symbols="AAA,BBB,CCC", method="erc", lookback_window="90d")
    assert 89 <= _age_days(fake.requests[0]) <= 91
    assert out.data["controls"]["lookback_days"] == 90


def test_explicit_days_wins_over_lookback_window() -> None:
    out, fake = _run(symbols="AAA,BBB,CCC", method="erc", days=252, lookback_window="5Y")
    assert 251 <= _age_days(fake.requests[0]) <= 253
    assert out.data["controls"]["lookback_days"] == 252


def test_unknown_lookback_window_is_an_input_error() -> None:
    out, fake = _run(symbols="AAA,BBB,CCC", method="erc", lookback_window="7Y")
    assert out.data["status"] == "input_error"
    assert "lookback_window" in out.data["reason"]
    assert fake.requests == []


# ----------------------------- risk_budget ----------------------------------

def test_risk_budget_mapping_sets_the_erc_risk_shares() -> None:
    out, _ = _run(
        symbols="AAA,BBB,CCC",
        method="erc",
        risk_budget={"AAA": 0.5, "BBB": 0.25, "CCC": 0.25},
    )
    shares = _shares(out)
    assert shares["AAA"] == pytest.approx(50.0, abs=0.05)
    assert shares["BBB"] == pytest.approx(25.0, abs=0.05)
    assert shares["CCC"] == pytest.approx(25.0, abs=0.05)
    assert out.data["controls"]["risk_budget_applied"] is True


def test_risk_budget_string_form_is_parsed() -> None:
    out, _ = _run(
        symbols="AAA,BBB,CCC",
        method="erc",
        risk_budget="AAA:0.5,BBB:0.25,CCC:0.25",
    )
    assert _shares(out)["AAA"] == pytest.approx(50.0, abs=0.05)


def test_risk_budget_must_cover_every_symbol() -> None:
    out, fake = _run(symbols="AAA,BBB,CCC", method="erc", risk_budget={"AAA": 0.5, "BBB": 0.5})
    assert out.data["status"] == "input_error"
    assert "CCC" in out.data["reason"]
    assert fake.requests == []


def test_risk_budget_rejects_non_positive_shares() -> None:
    out, fake = _run(symbols="AAA,BBB,CCC", method="erc", risk_budget={"AAA": 0.0, "BBB": 0.5, "CCC": 0.5})
    assert out.data["status"] == "input_error"
    assert fake.requests == []


def test_risk_budget_is_reported_as_not_applied_to_inverse_vol() -> None:
    out, _ = _run(
        symbols="AAA,BBB,CCC",
        method="inverse_vol",
        risk_budget={"AAA": 0.5, "BBB": 0.25, "CCC": 0.25},
    )
    assert out.data["controls"]["risk_budget_applied"] is False
    assert any("inverse_vol" in w for w in out.warnings), out.warnings


# ----------------------------- paper_mode -----------------------------------

def test_paper_mode_is_reported_with_its_real_effect() -> None:
    out, _ = _run(symbols="AAA,BBB,CCC", method="erc", paper_mode=False)
    controls = out.data["controls"]
    assert controls["paper_mode_requested"] is False
    assert "no order path" in controls["paper_mode_effect"]


# ----------------------------- disclosure -----------------------------------

def test_runtime_methodology_no_longer_lists_applied_controls_as_unapplied() -> None:
    out, _ = _run(symbols="AAA,BBB,CCC", method="erc")
    text = out.data["methodology"]
    assert "not applied yet" not in text
    assert "paper_mode" in text
    assert "risk_budget" in text


def test_seed_methodology_no_longer_lists_applied_controls_as_unapplied() -> None:
    load_seeds()
    text = REGISTRY.get("RPAR").methodology
    assert "not applied yet" not in text
    assert "paper_mode" in text
    assert "risk_budget" in text
