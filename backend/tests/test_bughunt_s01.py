"""Regression-pinning tests for ShowMe BugHunt Session 01.

Pins the foundation and per-code fixes applied to the 10 codes in this
session: ACCT, AIM, ALLQ, ALRT, ANR, APPL, AV, BBGT, BETA, BGAS.

Each test isolates one defect and asserts the new behaviour so a
future revert is caught by CI. None of these tests need a live
provider — every external dep is replaced by a minimal stub.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme import server
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.commodity._funcs import BGASFunction
from showme.engine.functions.equity.anr import ANRFunction
from showme.engine.functions.equity.beta import BetaFunction
from showme.engine.functions.misc._bonus import APPLFunction
from showme.engine.functions.misc.alrt import ALRTFunction
from showme.engine.functions.portfolio.acct import ACCTFunction
from showme.engine.functions.trade._funcs import AIMFunction, BBGTFunction


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ── Foundation 1 — SYNTHETIC_SOURCE_MARKERS catches *_model / *_baseline ──


def test_synthetic_markers_now_catch_model_sources() -> None:
    """Bug-hunt S01 foundation: previously sources named ``trace_proxy_model``,
    ``taxonomy_model``, ``beta_market_model``, ``commodity_reference_model``,
    ``podcast_directory_model`` all leaked through as ``ok`` because none of
    the substrings ``template/sample/placeholder/synthetic/continuity``
    matched. The ``_model``, ``_baseline``, ``_defaults`` markers close the
    gap.
    """
    for source in (
        "trace_proxy_model",
        "taxonomy_model",
        "beta_market_model",
        "commodity_reference_model",
        "podcast_directory_model",
        "manual_or_public_defaults",
        "reference_baseline",
    ):
        assert server._is_synthetic_source(source), source


def test_synthetic_markers_do_not_false_positive_live_sources() -> None:
    """Live sources used elsewhere must keep round-tripping as live."""
    for source in (
        "yfinance",
        "yfinance_quote",
        "yfinance_options",
        "finnhub",
        "polymarket",
        "opensky",
        "eia",
        "openstreetmap_nominatim",
        "podcast_rss",
        "paper_ticket",
        "order_history",
        "user_positions",
    ):
        assert not server._is_synthetic_source(source), source


def test_sanitize_labels_trace_proxy_model_source_as_model() -> None:
    """Refactored 2026-05-24: ALLQ rows from ``trace_proxy_model`` are
    no longer wiped. They flow through tagged ``data_state == "model"``
    so the bond pane can show the row with an honest MODEL pill instead
    of a useless ``provider_unavailable`` envelope.
    """
    payload = server.sanitize_function_payload(
        "ALLQ",
        {"symbol": "US10Y"},
        {
            "code": "ALLQ",
            "instrument": {"symbol": "US10Y", "asset_class": "BOND"},
            "data": {"rows": [{"dealer": "Composite A", "bid": 99.0, "ask": 99.5}]},
            "metadata": {},
            "sources": ["trace_proxy_model"],
            "warnings": [],
        },
    )
    # Row is kept; status is NOT collapsed.
    assert payload["data"]["status"] != "provider_unavailable"
    assert payload["data"]["rows"] == [
        {"dealer": "Composite A", "bid": 99.0, "ask": 99.5}
    ]
    # Source preserved, data_state pill stamped.
    assert payload["sources"] == ["trace_proxy_model"]
    assert payload["data_state"] == "model"
    assert payload["sanitizer_summary"]["model"] == 1


def test_sanitize_still_labels_template_payload_as_synthetic() -> None:
    """Existing pin (test_sanitize_suppresses_template_payloads) was
    updated 2026-05-24 to reflect the new contract: ``template`` rows
    pass through with ``data_state == "synthetic"`` and a populated
    ``sanitizer_summary``.
    """
    payload = server.sanitize_function_payload(
        "BETA",
        {"symbol": "AAPL", "asset_class": "EQUITY"},
        {
            "code": "BETA",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {"beta": 1.0, "rows": [{"close": 100.0}]},
            "metadata": {"mode": "template"},
            "sources": ["fundamentals_template"],
            "warnings": [],
        },
    )
    assert payload["sources"] == ["fundamentals_template"]
    assert payload["metadata"]["synthetic"] is True
    assert payload["data_state"] == "synthetic"
    assert payload["sanitizer_summary"]["synthetic"] == 1
    assert payload["data"]["status"] != "provider_unavailable"


# ── ANR ─────────────────────────────────────────────────────────────────────


def test_anr_returns_input_required_when_instrument_missing() -> None:
    """ANRFunction.execute previously raised ValueError, which the generic
    exception handler converted to a provider_unavailable envelope. Now
    return an explicit input_required FunctionResult.
    """
    fn = ANRFunction()
    fn.deps = FunctionDeps()
    result = _run(fn.execute(instrument=None))
    assert result.data["status"] == "input_required"
    assert "symbol" in result.data["reason"].lower()
    assert result.data["rows"] == []


# ── BETA ────────────────────────────────────────────────────────────────────


def test_beta_returns_input_required_when_instrument_missing() -> None:
    fn = BetaFunction()
    fn.deps = FunctionDeps()
    result = _run(fn.execute(instrument=None))
    assert result.data["status"] == "input_required"
    assert result.data["rows"] == []


def test_beta_returns_provider_unavailable_when_no_yfinance() -> None:
    """Previously BetaFunction returned ``data={}`` + a single warning, which
    the envelope routed to EMPTY with no clear reason. Now surface as
    provider_unavailable so the UI knows yfinance is missing."""
    fn = BetaFunction()
    fn.deps = FunctionDeps()  # yfinance=None
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    result = _run(fn.execute(instrument=inst))
    assert result.data["status"] == "provider_unavailable"
    assert result.sources == ["no_live_source"]
    assert result.metadata["fallback"] is True
    assert "yfinance" in " ".join(result.metadata["provider_errors"]).lower()


# ── BBGT (EMSX subclass) ────────────────────────────────────────────────────


def test_bbgt_returns_provider_unavailable_when_submit_without_broker() -> None:
    """Bug-hunt S01: submit=true with no broker previously silently
    downgraded to a paper preview. Now surface provider_unavailable."""
    fn = BBGTFunction()
    fn.deps = FunctionDeps()  # no broker adapters wired
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    result = _run(fn.execute(instrument=inst, quantity=1, submit=True))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["broker"] is None
    assert result.sources == ["no_live_source"]
    assert result.metadata["fallback"] is True
    assert any("broker" in str(err).lower() for err in result.metadata["provider_errors"])


def test_bbgt_keeps_preview_when_submit_false_without_broker() -> None:
    """Preview mode must still work — only submit=true is treated as
    a real intent to send the order."""
    fn = BBGTFunction()
    fn.deps = FunctionDeps()
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    result = _run(fn.execute(instrument=inst, quantity=1, submit=False))
    assert result.data["status"] == "preview"
    assert result.data["broker"] == "paper"


def test_bbgt_input_required_when_quantity_zero() -> None:
    """Existing input_required path must keep working after the new branch."""
    fn = BBGTFunction()
    fn.deps = FunctionDeps()
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    result = _run(fn.execute(instrument=inst, quantity=0, submit=True))
    assert result.data["status"] == "input_required"


# ── AIM ─────────────────────────────────────────────────────────────────────


class _BoomBroker:
    name = "boom"

    async def get_open_orders(self) -> list[Any]:
        raise RuntimeError("simulated broker outage")


def test_aim_surfaces_broker_exceptions_in_provider_errors() -> None:
    """Bug-hunt S01: previously broker exceptions silently coerced to [].
    Now surface them in metadata.provider_errors so the source/status
    panel can show the transport failure."""
    fn = AIMFunction()
    # broker adapters are injected dynamically by function_factory, so we
    # attach them as attributes (FunctionDeps does not declare them).
    deps = FunctionDeps()
    deps.binance_broker = _BoomBroker()
    fn.deps = deps
    result = _run(fn.execute(instrument=None))
    # No orders anywhere → empty envelope but with the broker error
    # captured so the user can see what failed.
    errors = result.metadata.get("provider_errors") or []
    assert any("binance_broker" in str(e) and "simulated broker outage" in str(e)
               for e in errors), errors


def test_aim_coerces_non_integer_limit_to_default() -> None:
    fn = AIMFunction()
    fn.deps = FunctionDeps()
    result = _run(fn.execute(instrument=None, limit="not-a-number"))
    errors = result.metadata.get("provider_errors") or []
    assert any("limit" in str(e).lower() and "not-a-number" in str(e)
               for e in errors), errors


# ── ALRT ────────────────────────────────────────────────────────────────────


def test_alrt_add_without_condition_returns_input_required() -> None:
    """Bug-hunt S01: previously params['condition'] missing raised KeyError
    which the generic handler converted to a provider_unavailable
    envelope (misleading). Now surface input_required."""
    fn = ALRTFunction()
    fn.deps = FunctionDeps()
    result = _run(fn.execute(instrument=None, action="add"))
    assert result.data["status"] == "input_required"
    assert "condition" in result.data["reason"].lower()


def test_alrt_remove_without_id_returns_input_required() -> None:
    fn = ALRTFunction()
    fn.deps = FunctionDeps()
    result = _run(fn.execute(instrument=None, action="remove"))
    assert result.data["status"] == "input_required"


def test_alrt_unknown_action_returns_input_error() -> None:
    fn = ALRTFunction()
    fn.deps = FunctionDeps()
    result = _run(fn.execute(instrument=None, action="explode"))
    assert result.data["status"] == "input_error"
    assert "explode" in result.data["reason"]


def test_alrt_list_response_includes_evaluator_status() -> None:
    """Bug-hunt S01: list response now advertises that the background
    evaluator is not wired, so the UI can show a clear banner instead of
    pretending the DSL examples will fire."""
    fn = ALRTFunction()
    fn.deps = FunctionDeps()
    result = _run(fn.execute(instrument=None))  # default action=list
    assert result.data["evaluator_status"] == "not_running"
    assert "evaluator" in result.data["evaluator_note"].lower()


# ── ACCT ────────────────────────────────────────────────────────────────────


class _EmptyPortfolio:
    """Stand-in PortfolioState so ACCT tests are hermetic regardless of
    any lingering runtime/portfolio.json on the dev box."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.positions: list[Any] = []

    def import_legacy_crypto(self, *_args: Any, **_kwargs: Any) -> int:
        return 0


def test_acct_skips_invalid_positions_and_reports_them(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug-hunt S01: previously a non-numeric quantity raised a 500.
    Now the bad row is skipped and the index reported in metadata."""
    monkeypatch.setattr(
        "showme.engine.functions.portfolio.acct.PortfolioState",
        _EmptyPortfolio,
    )
    fn = ACCTFunction()
    fn.deps = FunctionDeps()
    positions = [
        {"symbol": "AAPL", "asset_class": "EQUITY", "quantity": 10, "avg_cost": 100, "last": 200, "account": "main"},
        {"symbol": "MSFT", "asset_class": "EQUITY", "quantity": "not-a-number", "avg_cost": 0, "last": 0, "account": "main"},
        {"asset_class": "EQUITY", "quantity": 5, "avg_cost": 1},  # missing symbol
    ]
    result = _run(fn.execute(instrument=None, positions=positions))
    # AAPL must still be aggregated
    rows = result.data["rows"]
    assert any(row["account"] == "main" for row in rows)
    skipped = result.metadata.get("skipped_positions") or []
    # MSFT (bad quantity) + index-2 (missing symbol)
    assert len(skipped) == 2
    skipped_idxs = sorted(s["index"] for s in skipped)
    assert skipped_idxs == [1, 2]


def test_acct_rejects_non_list_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "showme.engine.functions.portfolio.acct.PortfolioState",
        _EmptyPortfolio,
    )
    fn = ACCTFunction()
    fn.deps = FunctionDeps()
    result = _run(fn.execute(instrument=None, positions={"AAPL": 10}))
    assert result.data["status"] == "input_error"


# ── BGAS ────────────────────────────────────────────────────────────────────


class _BoomEIA:
    async def fetch(self, request: Any) -> Any:
        raise RuntimeError("EIA api key not set")


def test_bgas_captures_eia_failure_in_provider_errors() -> None:
    """Bug-hunt S01: ``except Exception: pass`` previously hid every EIA
    transport failure. Now capture into provider_errors so the source/
    status panel can show why the yfinance fallback ran."""
    fn = BGASFunction()
    # eia raises → fall through to yfinance branch with no yfinance dep →
    # provider_unavailable; provider_errors must include the eia message.
    fn.deps = FunctionDeps(eia=_BoomEIA())
    result = _run(fn.execute())
    assert result.data["status"] == "provider_unavailable"
    errors = result.metadata.get("provider_errors") or []
    assert any("eia" in str(e).lower() and "EIA api key not set" in str(e)
               for e in errors), errors


def test_bgas_warns_when_contract_overridden_to_ngas() -> None:
    """Passing a contract not in COMMODITY_CONTRACTS used to be silently
    reverted to NG=F. Now we surface the override in provider_errors."""
    fn = BGASFunction()
    fn.deps = FunctionDeps()
    # FAKE=F is not in COMMODITY_CONTRACTS; the function must report the
    # silent revert to NG=F.
    result = _run(fn.execute(contract="FAKE=F"))
    errors = result.metadata.get("provider_errors") or []
    assert any("FAKE=F" in str(e) and "NG=F" in str(e) for e in errors), errors


# ── APPL ────────────────────────────────────────────────────────────────────


def test_appl_emits_warning_when_yfinance_missing() -> None:
    """Bug-hunt S01: previously the live=False / no-yfinance branch was
    silent; the user got the bundled taxonomy with no indication that the
    provider was missing."""
    fn = APPLFunction()
    fn.deps = FunctionDeps()  # no yfinance
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    result = _run(fn.execute(instrument=inst, live=True))
    # warnings reach the function result envelope
    assert result.warnings
    assert any("yfinance" in w.lower() for w in result.warnings)
