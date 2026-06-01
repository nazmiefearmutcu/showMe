"""Sidecar boot/runtime helpers."""
from __future__ import annotations

import asyncio
import os
import sys
import types
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from showme import server


def test_prepare_writable_cwd_is_noop_outside_frozen(monkeypatch) -> None:
    monkeypatch.delattr(server.sys, "_MEIPASS", raising=False)

    assert server.prepare_writable_cwd() is None


def test_prepare_writable_cwd_publishes_app_home_without_chdir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """ARCH-09 P0: process-wide ``os.chdir`` removed.

    ``prepare_writable_cwd`` must still ensure the app-home/runtime directories
    exist and publish ``SHOWME_HOME`` to the environment, but it must NOT call
    ``os.chdir`` — every store now resolves paths via
    ``showme.app_paths.runtime_path`` instead of relying on cwd.
    """
    frozen_extract = tmp_path / "_MEI"
    app_home = tmp_path / "app-home"
    frozen_extract.mkdir()
    monkeypatch.setattr(server.sys, "_MEIPASS", str(frozen_extract), raising=False)
    monkeypatch.setenv("SHOWME_HOME", str(app_home))
    monkeypatch.chdir(frozen_extract)

    resolved = server.prepare_writable_cwd()

    assert resolved == app_home
    # cwd MUST stay where it was — no implicit chdir.
    assert Path.cwd() == frozen_extract
    assert (app_home / "runtime").is_dir()
    assert os.environ["SHOWME_HOME"] == str(app_home)


def test_prepare_writable_cwd_does_not_scan_legacy_runtime_by_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    frozen_extract = tmp_path / "_MEI"
    app_home = tmp_path / "app-home"
    home = tmp_path / "home"
    legacy_runtime = home / "Desktop" / "Projeler" / "proje" / "showMe/engine" / "runtime"
    frozen_extract.mkdir()
    legacy_runtime.mkdir(parents=True)
    (legacy_runtime / "state.json").write_text('{"positions": {}}\n')
    monkeypatch.setattr(server.sys, "_MEIPASS", str(frozen_extract), raising=False)
    monkeypatch.setenv("SHOWME_HOME", str(app_home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("SHOWME_MIRROR_LEGACY_RUNTIME", raising=False)
    monkeypatch.delenv("SHOWME_ENGINE_RUNTIME_PATH", raising=False)
    monkeypatch.delenv("SHOWME_ENGINE_PATH", raising=False)
    monkeypatch.chdir(frozen_extract)

    server.prepare_writable_cwd()

    assert not (app_home / "runtime" / "state.json").exists()


def test_prepare_writable_cwd_can_mirror_explicit_legacy_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    frozen_extract = tmp_path / "_MEI"
    app_home = tmp_path / "app-home"
    source = tmp_path / "showme-engine-runtime"
    frozen_extract.mkdir()
    source.mkdir()
    (source / "state.json").write_text('{"positions": {}}\n')
    monkeypatch.setattr(server.sys, "_MEIPASS", str(frozen_extract), raising=False)
    monkeypatch.setenv("SHOWME_HOME", str(app_home))
    monkeypatch.setenv("SHOWME_MIRROR_LEGACY_RUNTIME", "1")
    monkeypatch.setenv("SHOWME_ENGINE_RUNTIME_PATH", str(source))
    monkeypatch.chdir(frozen_extract)

    server.prepare_writable_cwd()

    assert (app_home / "runtime" / "state.json").is_file()


def test_mirror_legacy_runtime_copies_state_files(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "showme-engine-runtime"
    app_home = tmp_path / "app-home"
    source.mkdir()
    (source / "state.json").write_text('{"positions": {}}\n')
    (source / "portfolio.json").write_text('{"positions": []}\n')
    (source / "orders.sqlite").write_bytes(b"sqlite")
    (source / "bot.log").write_text("large logs are not mirrored\n")
    monkeypatch.setenv("SHOWME_ENGINE_RUNTIME_PATH", str(source))

    copied = server.mirror_legacy_runtime(app_home)

    assert copied == 3
    assert (app_home / "runtime" / "state.json").is_file()
    assert (app_home / "runtime" / "portfolio.json").is_file()
    assert (app_home / "runtime" / "orders.sqlite").is_file()
    assert not (app_home / "runtime" / "bot.log").exists()


def test_default_asset_class_infers_crypto_pairs() -> None:
    assert server.default_asset_class_name("BTCUSDT") == "CRYPTO"
    assert server.default_asset_class_name("FLOCKUSDT") == "CRYPTO"
    assert server.resolve_crypto_symbol_alias("ethereum") == "ETHUSDT"
    assert server.resolve_crypto_symbol_alias("Pepe") == "PEPEUSDT"
    assert server.default_asset_class_name("ethereum") == "CRYPTO"
    assert server.default_asset_class_name("eth-usd") == "CRYPTO"
    assert server.default_asset_class_name("SOL/USDC") == "CRYPTO"
    assert server.default_asset_class_name("AAPL") == "EQUITY"
    assert server.default_asset_class_name("EURUSD") == "FX"
    assert server.default_asset_class_name("GBPUSD=X") == "FX"
    assert server.default_asset_class_name("GC=F") == "COMMODITY"
    assert server.default_asset_class_name("XAUUSD") == "COMMODITY"
    assert server.default_asset_class_name("^GSPC") == "INDEX"
    assert server.default_asset_class_name("US10Y") == "BOND"
    assert server.default_asset_class_name("us2y") == "BOND"


def test_default_asset_class_respects_explicit_request() -> None:
    assert server.default_asset_class_name("BTCUSDT", "equity") == "EQUITY"


def test_corr_impactor_template_covers_all_markets() -> None:
    engine_root = Path(__file__).resolve().parents[2] / "engine"
    sys.path.insert(0, str(engine_root))
    from showme.engine.functions.portfolio.corr import _correlation_template

    symbols = ["AAPL", "SPX", "EURUSD", "BTCUSDT", "GC=F", "US10Y", "CDXIG"]
    payload = _correlation_template(symbols, 365)
    impact = payload["impactor"]

    assert payload["summary"]["method"] == "correlation_impact_matrix"
    assert {row["market"] for row in impact["market_coverage"]} == {
        "Equity",
        "Index",
        "FX",
        "Crypto",
        "Commodity",
        "Rates",
        "Credit",
    }
    assert len(impact["matrix"]) == len(symbols) ** 2
    assert impact["analysis_steps"]
    assert impact["return_series_summary"]
    assert impact["top_positive_pairs"]
    assert impact["bug_analysis"][0]["status"] == "passed"


def test_route_params_do_not_inject_symbol_into_standalone_derivative(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [
            server.FunctionIndexEntry(
                code="OVME",
                name="Option Valuation",
                category="derivative",
                asset_classes=["DERIVATIVE"],
            ),
        ],
    )

    params = server._route_function_params("OVME", {})

    assert "symbol" not in params
    assert "topic" not in params
    assert "asset_class" not in params
    assert params["spot"] == 100
    assert params["strike"] == 105
    assert params["type"] == "CALL"


def test_route_params_keep_symbol_for_symbol_functions(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [
            server.FunctionIndexEntry(
                code="CN",
                name="Company News",
                category="news",
                asset_classes=["EQUITY", "CRYPTO"],
            ),
        ],
    )

    params = server._route_function_params("CN", {})

    assert params["symbol"] == "BTCUSDT"
    assert params["asset_class"] == "CRYPTO"


def test_route_params_resolve_crypto_coin_names_for_symbol_functions(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [
            server.FunctionIndexEntry(
                code="ANR",
                name="Analyst Recommendations",
                category="equity",
                asset_classes=["EQUITY", "CRYPTO"],
            ),
            server.FunctionIndexEntry(
                code="CN",
                name="Company News",
                category="news",
                asset_classes=["EQUITY", "CRYPTO"],
            ),
        ],
    )

    anr = server._route_function_params("ANR", {"symbol": "ethereum"})
    cn = server._route_function_params("CN", {"symbol": "Pepe"})

    assert anr["symbol"] == "ETHUSDT"
    assert anr["asset_class"] == "CRYPTO"
    assert cn["symbol"] == "PEPEUSDT"
    assert cn["asset_class"] == "CRYPTO"


def test_route_params_do_not_convert_ni_topic_to_symbol(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [
            server.FunctionIndexEntry(
                code="NI",
                name="News by Topic",
                category="news",
                asset_classes=[],
            ),
        ],
    )

    params = server._route_function_params("NI", {"topic": "FED"})

    assert params["topic"] == "FED"
    assert "symbol" not in params
    assert "asset_class" not in params


def test_route_params_do_not_shrink_frh_to_peer_symbols(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [
            server.FunctionIndexEntry(
                code="FRH",
                name="Funding Rate Heatmap",
                category="screen",
                asset_classes=[],
            ),
        ],
    )

    params = server._route_function_params("FRH", {})

    assert "symbols" not in params
    assert "symbol" not in params
    assert "asset_class" not in params
    assert params["exchange"] == "BINANCE"


def test_route_params_keep_explicit_frh_symbols(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [
            server.FunctionIndexEntry(
                code="FRH",
                name="Funding Rate Heatmap",
                category="screen",
                asset_classes=[],
            ),
        ],
    )

    params = server._route_function_params("FRH", {"symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]})

    assert params["symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def test_route_params_make_micro_symbol_first_with_intraday_interval(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [
            server.FunctionIndexEntry(
                code="MICRO",
                name="Market Microstructure",
                category="screen",
                asset_classes=["CRYPTO", "EQUITY"],
            ),
        ],
    )

    params = server._route_function_params("MICRO", {})

    assert params["symbol"] == "BTCUSDT"
    assert params["asset_class"] == "CRYPTO"
    assert params["interval"] == "1m"


def test_route_params_preserve_most_asset_tab_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [
            server.FunctionIndexEntry(
                code="MOST",
                name="Most Active",
                category="screen",
                asset_classes=[],
            ),
        ],
    )

    params = server._route_function_params("MOST", {"asset_class": "crypto", "limit": 50})

    assert params["asset_class"] == "crypto"
    assert "symbol" not in params


def test_json_safe_converts_dataframes() -> None:
    payload = {"rows": pd.DataFrame([{"symbol": "BTCUSDT", "value": 1.5}])}

    assert server.json_safe(payload) == {"rows": [{"symbol": "BTCUSDT", "value": 1.5}]}


def test_json_safe_converts_dataclasses() -> None:
    @dataclass
    class Quote:
        symbol: str
        fetched_at: datetime
        extras: dict[str, object]

    payload = Quote(
        symbol="AAPL",
        fetched_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        extras={"raw": {"currentPrice": 282.62}},
    )

    assert server.json_safe(payload) == {
        "symbol": "AAPL",
        "fetched_at": "2026-05-01T00:00:00+00:00",
        "extras": {"raw": {"currentPrice": 282.62}},
    }


def test_price_history_alias_rows_normalize_ohlcv_frame() -> None:
    frame = pd.DataFrame(
        [{"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100}],
        index=pd.to_datetime(["2026-05-01"]),
    )

    rows = server._history_rows(frame)

    assert rows == [{
        "date": "2026-05-01T00:00:00",
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "adj_close": None,
        "volume": 100,
    }]


def test_price_history_alias_range_days() -> None:
    assert server._days_from_range("1M") == 30
    assert server._days_from_range("max") == 365 * 25
    assert server._days_from_range("unknown") is None
    assert server._history_days_from_params({"range": "5Y"}) == 365 * 5
    assert server._history_days_from_params({"days": "45"}) == 45


def test_function_warning_payload_keeps_function_shape() -> None:
    payload = server.function_warning_payload(
        "BGAS",
        {"symbol": "BTCUSDT", "asset_class": "CRYPTO"},
        RuntimeError("EIA_API_KEY not set"),
    )

    assert payload["code"] == "BGAS"
    assert payload["instrument"] == {"symbol": "BTCUSDT", "asset_class": "CRYPTO"}
    assert payload["warnings"] == []
    assert payload["metadata"]["provider_errors"] == ["EIA_API_KEY not set"]
    assert payload["metadata"]["fallback"] is True
    assert payload["sources"] == ["no_live_source"]
    assert payload["data"]["status"] == "provider_unavailable"
    assert payload["data"]["rows"] == []


def test_sanitize_labels_template_payloads_as_synthetic() -> None:
    """Refactored 2026-05-24: the sanitizer no longer wipes template
    rows. It labels them ``data_state == "synthetic"`` and lets the row
    through so the UI can pill accurately instead of showing a useless
    ``provider_unavailable`` envelope.
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

    # Row is kept; status is NOT collapsed to provider_unavailable.
    assert payload["data"]["status"] != "provider_unavailable"
    assert payload["data"]["rows"] == [{"close": 100.0}]
    # Source string is preserved (no longer rewritten to no_live_source).
    assert payload["sources"] == ["fundamentals_template"]
    # data_state pill + sanitizer_summary expose the synthetic nature.
    assert payload["data_state"] == "synthetic"
    assert payload["sanitizer_summary"]["synthetic"] == 1
    assert payload["metadata"]["synthetic"] is True
    assert payload["metadata"]["data_state"] == "synthetic"


def test_sanitize_lots_empty_state_is_not_ok() -> None:
    payload = server.sanitize_function_payload(
        "LOTS",
        {"action": "list"},
        {
            "code": "LOTS",
            "instrument": None,
            "data": {
                "status": "empty",
                "reason": "local portfolio has no tax lots",
                "lots": [],
                "rows": [],
                "next_actions": ["Add or import tax lots before running LOTS."],
            },
            "metadata": {},
            "sources": ["local_tax_lot_ledger"],
            "warnings": [],
        },
    )

    assert payload["status"] == "empty"
    assert payload["reason"] == "local portfolio has no tax lots"
    assert payload["nextAction"] == "Add or import tax lots before running LOTS."
    assert payload["rows"] == []


def test_sanitize_lots_seed_rows_are_ok() -> None:
    payload = server.sanitize_function_payload(
        "LOTS",
        {"action": "list"},
        {
            "code": "LOTS",
            "instrument": None,
            "data": {
                "status": "ok",
                "lots": [{"lot_id": "seed-aapl-001", "symbol": "AAPL", "remaining": 15}],
                "rows": [{"lot_id": "seed-aapl-001", "symbol": "AAPL", "remaining": 15}],
                "count": 1,
            },
            "metadata": {},
            "sources": ["local_tax_lot_ledger"],
            "warnings": [],
        },
    )

    assert payload["status"] == "ok"
    assert payload["rows"] == [{"lot_id": "seed-aapl-001", "symbol": "AAPL", "remaining": 15}]


def test_sanitize_fa_ok_requires_ratios_payload() -> None:
    payload = server.sanitize_function_payload(
        "FA",
        {"symbol": "AAPL", "asset_class": "EQUITY"},
        {
            "code": "FA",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {
                "symbol": "AAPL",
                "status": "ok",
                "income_statement": [{"line_item": "revenue", "latest": 100}],
                "balance_sheet": [{"line_item": "total_assets", "latest": 300}],
                "cash_flow": [{"line_item": "cfo", "latest": 30}],
                "ratios": {"net_margin": 0.25},
            },
            "metadata": {},
            "sources": ["sec_edgar"],
            "warnings": [],
        },
    )

    assert payload["status"] == "ok"
    assert payload["data"]["ratios"]["net_margin"] == 0.25
    assert payload["cards"][0]["section"] == "ratios"


def test_sanitize_fa_without_ratios_becomes_calc_error() -> None:
    payload = server.sanitize_function_payload(
        "FA",
        {"symbol": "AAPL", "asset_class": "EQUITY"},
        {
            "code": "FA",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {
                "symbol": "AAPL",
                "status": "ok",
                "income_statement": [{"line_item": "revenue", "latest": 100}],
                "balance_sheet": [],
                "cash_flow": [],
                "ratios": {},
            },
            "metadata": {},
            "sources": ["sec_edgar"],
            "warnings": [],
        },
    )

    assert payload["status"] == "calc_error"
    assert "ratios payload" in payload["reason"]


def test_portfolio_close_position_suppresses_legacy_reimport(monkeypatch, tmp_path: Path) -> None:
    # bughunt 2026-05-24: legacy mirror is now opt-in. Set the flag so the
    # closed-symbol dedup is actually exercised (otherwise the import returns
    # 0 because the gate is closed, not because the dedup fired).
    monkeypatch.setenv("SHOWME_IMPORT_LEGACY_TBV3", "1")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    from showme.engine.core.instrument import Instrument
    from showme.engine.portfolio.state import PortfolioPosition, PortfolioState

    path = tmp_path / "portfolio.json"
    legacy = tmp_path / "state.json"
    state = PortfolioState(path)
    state.add_position(PortfolioPosition(
        instrument=Instrument.crypto("BTCUSDT"),
        quantity=2,
        avg_cost=100,
    ))

    preview = state.close_position("BTCUSDT", exit_price=110, dry_run=True)
    assert preview and preview["dry_run"] is True
    assert len(state.positions) == 1

    closed = state.close_position("BTCUSDT", exit_price=110, dry_run=False)
    assert closed and closed["realized_pnl"] == 20
    assert len(state.positions) == 0
    assert "BTCUSDT" in state.closed_symbols

    legacy.write_text('{"positions": {"BTCUSDT": {"quantity": 2, "entry_price": 100}}}')
    assert state.import_legacy_crypto(legacy) == 0

    reloaded = PortfolioState(path)
    assert "BTCUSDT" in reloaded.closed_symbols
    assert reloaded.positions == []


def test_sanitize_input_required_becomes_input_error() -> None:
    payload = server.sanitize_function_payload(
        "TRQA",
        {"symbol": "AAPL"},
        {
            "code": "TRQA",
            "instrument": {"symbol": "AAPL", "asset_class": "EQUITY"},
            "data": {
                "status": "input_required",
                "reason": "Transcript Q&A needs transcript text.",
                "answers": [],
            },
            "metadata": {},
            "sources": [],
            "warnings": [],
        },
    )

    assert payload["status"] == "input_error"
    assert payload["reason"] == "Transcript Q&A needs transcript text."


def test_tca_empty_order_history_is_not_ok(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    monkeypatch.chdir(tmp_path)
    # order_history resolves its SQLite path via app_paths (SHOWME_HOME), not
    # cwd, so isolate the runtime store to an empty temp dir — otherwise this
    # hermetic "no fills" assertion silently depends on the host's real
    # order_history being empty.
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setattr(
        "showme.engine.services.order_history.runtime_path",
        lambda name: tmp_path / "runtime" / name,
    )
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)
    from showme.engine.services import tca

    out = tca.analyze_orders(limit=50)

    assert out["status"] == "empty"
    assert out["orders"] == []
    assert "implementation_shortfall_bps" in out["equations"]
    assert out["next_actions"]


def test_exec_monitor_filled_live_parent_is_marked_needs_close(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    monkeypatch.chdir(tmp_path)
    from showme.engine.services import exec_monitor

    exec_monitor.open_parent(
        "parent-1",
        symbol="AAPL",
        side="BUY",
        target_qty=100,
        arrival_price=150,
        horizon_seconds=600,
    )
    exec_monitor.record_slice("parent-1", slice_idx=0, qty=100, avg_px=150.2)

    row = exec_monitor.list_parents(limit=10)[0]

    assert row["status"] == "filled_not_closed"
    assert row["stored_status"] == "live"
    assert row["started_at_iso"]
    assert row["metrics"]["residual_qty"] == 0
    assert row["metrics"]["pace_pct"] == 0
    assert row["next_action"]


def test_agent_candidate_parser_infers_market_classes() -> None:
    rows = server._parse_agent_candidates("btcusdt, ethereum, AAPL, EURUSD, GC=F")

    assert rows == [
        {"symbol": "BTCUSDT", "asset_class": "CRYPTO"},
        {"symbol": "ETHUSDT", "asset_class": "CRYPTO"},
        {"symbol": "AAPL", "asset_class": "EQUITY"},
        {"symbol": "EURUSD", "asset_class": "FX"},
        {"symbol": "GC=F", "asset_class": "COMMODITY"},
    ]


def test_agent_payload_score_reads_positive_and_negative_signals() -> None:
    payload = {
        "data": {
            "test_accuracy": 0.58,
            "strategy_sharpe": 1.2,
            "max_drawdown_pct": 8.0,
            "signal": "long_bias",
        },
        "metadata": {},
        "warnings": [],
    }

    score = server._agent_payload_score("MLSIG", payload)

    assert score["signal_count"] >= 3
    assert score["score"] > 0


def test_agent_fast_probe_returns_non_zero_candidate_scores(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [
            server.FunctionIndexEntry(code="MLSIG", name="ML Signal", category="portfolio"),
            server.FunctionIndexEntry(code="PORT", name="Portfolio", category="portfolio"),
        ],
    )

    out = server._run_best_symbol_agent_blocking(
        {
            "candidates": ["BTCUSDT", "AAPL", "EURUSD"],
            "max_candidates": 3,
            "execute_functions": False,
        }
    )

    assert out["method"] == "all_function_symbol_agent_v3_fast_probe"
    assert out["best"]["score"] > 0
    assert all(row["score"] != 0 for row in out["ranked"])
    assert all(row["signal_functions"] >= 1 for row in out["ranked"])


def test_agent_fast_probe_exposes_multiple_evidence_rows_and_exclusions(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [
            server.FunctionIndexEntry(code="MLSIG", name="ML Signal", category="portfolio"),
            server.FunctionIndexEntry(code="BTFW", name="Walk Forward", category="portfolio"),
            server.FunctionIndexEntry(code="BTUNE", name="Backtest Tuner", category="portfolio"),
            server.FunctionIndexEntry(code="NALRT", name="News Alerts", category="news"),
        ],
    )

    out = server._run_best_symbol_agent_blocking(
        {
            "candidates": ["BTCUSDT", "AAPL"],
            "max_candidates": 2,
            "execute_functions": False,
        }
    )

    assert out["catalog_count"] == out["function_count"] + 3
    assert [row["code"] for row in out["excluded_functions"]] == ["AGENT", "ASK", "HOME"]
    assert out["best"]["signal_functions"] >= 4
    assert len(out["best"]["top_evidence"]) >= 4
    assert {row["code"] for row in out["best"]["top_evidence"]} >= {"MLSIG", "BTFW", "BTUNE", "NALRT"}


def test_screen_reference_screeners_apply_real_filters(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    from showme.engine.functions.screen._funcs import CSRCFunction, FSRCFunction, SECFFunction, SRCHFunction

    csrc = asyncio.run(CSRCFunction().execute(query='sector = "Energy"', live=False, limit=50))
    csrc_rows = csrc.data["rows"]
    assert csrc.data["matched"] >= 3
    assert all(row["sector"] == "Energy" for row in csrc_rows)
    assert csrc.data["field_dictionary"]

    fsrc = asyncio.run(FSRCFunction().execute(query="expenseRatio <= 0.001", live=False, limit=50))
    assert {row["symbol"] for row in fsrc.data["rows"]} >= {"VOO", "IVV", "VTI"}
    assert all(row["expenseRatio"] <= 0.001 for row in fsrc.data["rows"])

    srch = asyncio.run(SRCHFunction().execute(query="yield >= 4 AND duration <= 10", live=False, limit=50))
    assert {"US2Y", "US5Y", "US10Y"} <= {row["symbol"] for row in srch.data["rows"]}
    assert all(row["yield"] >= 4 and row["duration"] <= 10 for row in srch.data["rows"])

    secf = asyncio.run(SECFFunction().execute(query="technology", live=False, limit=50))
    assert {row["symbol"] for row in secf.data["rows"]} >= {"AAPL", "MSFT", "NVDA"}
    assert all("marketCap" not in row for row in secf.data["rows"])


def test_icx_index_query_and_reference_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [
            server.FunctionIndexEntry(
                code="ICX",
                name="Index Constituents",
                category="screen",
                asset_classes=["INDEX"],
            ),
        ],
    )

    routed = server._route_function_params("ICX", {"query": "NDX", "limit": 50})
    assert routed["index"] == "NDX"

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    from showme.engine.functions.screen.icx import ICXFunction

    out = asyncio.run(ICXFunction().execute(index="SPX", live=False, limit=50))
    assert out.data["status"] == "ok"
    assert out.data["index"] == "SPX"
    assert out.data["constituents"] >= 10


def test_sat_missing_provider_is_truthful_preview(monkeypatch) -> None:
    """de-garbage 2026-06-01: SAT no longer ships a key-gated Sentinel Hub stub
    that returned ``provider_unavailable`` + a synthetic base64 SVG 'preview'
    pretending to be imagery. It now uses KEYLESS NASA GIBS tiles + Open-Meteo
    conditions. The anti-garbage intent is preserved: SAT is truthful, never
    fabricated. When the keyless providers are reachable it returns real data
    (a live GIBS ``tile_url`` flagged ``is_satellite=True`` and a REAL Open-Meteo
    cloud_pct that is numeric-or-null, never invented); on a genuine outage it
    degrades honestly to ``provider_unavailable`` with NO fake tile."""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    from showme.engine.functions.misc.sat import SATFunction

    out = asyncio.run(SATFunction().execute(
        bbox="-122.55,37.70,-122.30,37.85",
        date_from="2026-04-26",
        date_to="2026-05-03",
    ))
    data = out.data

    # The AOI centroid must be honest regardless of provider reachability.
    assert data["status"] in {"ok", "partial", "provider_unavailable"}

    if data["status"] == "provider_unavailable":
        # Honest outage: no rows, no fabricated tile, no synthetic image.
        assert data["rows"] == []
        assert "data:image/svg+xml" not in str(data)
    else:
        assert data["rows"][0]["center_lat"] == 37.775
        # Real, fetchable NASA GIBS tile — never a synthetic SVG data-URL.
        tile_url = data["tile_url"]
        assert tile_url.startswith("http")
        assert "gibs.earthdata.nasa.gov" in tile_url
        assert "data:image/svg+xml" not in tile_url
        assert data["true_color_tile"]["is_satellite"] is True
        # Cloud cover is a REAL Open-Meteo value or honestly null — never faked.
        cloud_pct = data["cloud_pct"]
        assert cloud_pct is None or isinstance(cloud_pct, (int, float))


def test_sat_days_control_updates_date_window(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [
            server.FunctionIndexEntry(
                code="SAT",
                name="Satellite Imagery",
                category="misc",
                asset_classes=[],
            ),
        ],
    )

    routed = server._route_function_params("SAT", {"bbox": "-122.55,37.70,-122.30,37.85", "days": 30})

    assert routed["bbox"] == "-122.55,37.70,-122.30,37.85"
    assert routed["date_from"] < routed["date_to"]


def test_trqa_extractive_answer_uses_transcript_evidence(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    from showme.engine.functions.news.trqa import _extractive_answer

    answer = _extractive_answer(
        "Revenue grew 12 percent in the quarter. Management raised full-year guidance to 8 percent growth.",
        "What changed in guidance?",
    )

    assert "guidance" in answer["a"].lower()
    assert answer["evidence"] == answer["a"]
    assert answer["confidence"] > 0


def test_trqa_route_query_becomes_single_question(monkeypatch) -> None:
    routed = server._route_function_params(
        "TRQA",
        {
            "query": "What changed in guidance?",
            "text": "Management raised full-year guidance.",
        },
    )

    assert routed["questions"] == ["What changed in guidance?"]


def test_trqa_dash_llm_response_falls_back_to_extractive_answer(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))

    class FakeRouter:
        async def complete(self, _req):
            return types.SimpleNamespace(
                text="-",
                model="none",
                cost_usd=0,
                tokens_in=0,
                tokens_out=0,
            )

    fake_llm_router = types.SimpleNamespace(
        LLMRequest=lambda **kwargs: types.SimpleNamespace(**kwargs),
        LLMRouter=lambda: FakeRouter(),
    )
    monkeypatch.setitem(sys.modules, "showme.engine.agents.llm_router", fake_llm_router)

    from showme.engine.functions.news.trqa import TRQAFunction

    result = asyncio.run(
        TRQAFunction().execute(
            text="Revenue grew 12 percent. Management raised full-year guidance to 8 percent revenue growth.",
            query="What changed in guidance?",
        )
    )

    answer = result.data["answers"][0]
    assert answer["q"] == "What changed in guidance?"
    assert answer["model"] == "local_extractive"
    assert "guidance" in answer["a"].lower()


def test_av_media_rows_keep_playable_audio_url(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    from showme.engine.functions.news.av import _matches_query, _media_row

    row = _media_row(
        {"title": "Planet Money"},
        {
            "title": "Markets and the economy",
            "link": "https://example.com/episode",
            "published": "Sun, 03 May 2026 12:00:00 GMT",
            "summary": "<p>Macro markets episode.</p>",
            "enclosures": [{"href": "https://example.com/audio.mp3", "type": "audio/mpeg"}],
        },
    )

    assert row["audio_url"] == "https://example.com/audio.mp3"
    assert row["url"] == "https://example.com/audio.mp3"
    assert row["source_url"] == "https://example.com/episode"
    assert row["media_type"] == "audio/mpeg"
    assert _matches_query(row, "market")


def test_brief_live_composes_from_top_items_and_returns_articles(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    from showme.engine.core.base_function import FunctionResult
    from showme.engine.functions.news import top as top_mod
    from showme.engine.functions.news.brief import BRIEFFunction

    # 2026-06-01 contract change: BRIEF no longer sources headlines from the
    # READ reading-list store (which is empty for a fresh user). It composes
    # from TOP, which ranks live RSS/GDELT headlines under the ``items`` key —
    # the exact key the old BRIEF ignored. This fake TOP proves BRIEF reads
    # ``items`` and unescapes article HTML.
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


def test_evts_empty_provider_returns_actionable_status(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    from showme.engine.core.base_data_source import DataKind
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.functions.news.evts import EVTSFunction

    class EmptyYFinance:
        async def fetch(self, request):
            assert request.kind == DataKind.EVENTS
            return {
                "calendar": {},
                "earnings_dates": pd.DataFrame(),
                "actions": pd.DataFrame(),
                "dividends": pd.Series(dtype=float),
                "splits": pd.Series(dtype=float),
            }

    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    result = asyncio.run(EVTSFunction(FunctionDeps(yfinance=EmptyYFinance())).execute(instrument, live=True))

    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.data["next_actions"]


def test_sosc_provider_failure_does_not_emit_placeholder(monkeypatch) -> None:
    """De-garbage 2026-06-01: SOSC now reads keyless GDELT tone, so when the
    network is up the live path legitimately returns real rows. To pin the
    *contract* ("a provider failure must NOT be papered over with a fabricated
    placeholder") deterministically — instead of depending on the network
    actually being down — we force the GDELT leg to raise and assert the
    honest ``provider_unavailable`` envelope with empty rows."""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.functions.news import sosc as sosc_mod
    from showme.engine.functions.news.sosc import SOSCFunction

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated GDELT outage")

    monkeypatch.setattr(sosc_mod, "_gdelt_articles", _boom)

    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    result = asyncio.run(SOSCFunction(FunctionDeps()).execute(instrument, live=True))

    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.data["summary"]["net_sentiment"] is None
    assert result.data["summary"]["total_mentions"] == 0
    assert "simulated GDELT outage" in result.data["reason"]
    assert "placeholder" not in str(result.data).lower()


def test_sosc_tone_maps_to_unit_interval() -> None:
    """De-garbage 2026-06-01: SOSC was rewritten from a StockTwits/Reddit
    aggregator (the removed ``_sentiment_rows`` helper) to a keyless GDELT
    news-tone + FinBERT signal. The old per-row reddit_score/sentiment_score
    separation no longer applies. This pins the new contract's core numeric
    primitive instead: GDELT tone (roughly [-10, +10]) maps to a bounded
    [-1, +1] sentiment, and garbage tone values are dropped (None), never
    fabricated."""
    from showme.engine.functions.news.sosc import _to_unit_tone

    assert abs(_to_unit_tone(5.0) - 0.5) < 1e-9
    assert abs(_to_unit_tone(-5.0) - (-0.5)) < 1e-9
    # Clamped to the unit interval, never out of band.
    assert _to_unit_tone(50.0) == 1.0
    assert _to_unit_tone(-50.0) == -1.0
    # Non-numeric / NaN tone is dropped honestly, not coerced to a fake 0.
    assert _to_unit_tone("not-a-number") is None
    assert _to_unit_tone(None) is None


def test_news_alert_stale_headline_cannot_be_critical(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    from showme.engine.services.news_intelligence import critical_articles, enrich_articles

    stale = datetime.now(timezone.utc) - timedelta(days=90)
    rows = enrich_articles(
        [{
            "title": "Spot Bitcoin ETF approved after SEC decision",
            "summary": "Bitcoin market catalyst",
            "published_at": stale.isoformat(),
            "source": "Coindesk",
            "url": "https://example.com/old",
        }],
        symbol="BTCUSDT",
        query="bitcoin",
        asset_class="CRYPTO",
        threshold=70,
        max_alert_age_minutes=48 * 60,
    )

    assert rows[0]["stale_for_alert"] is True
    assert rows[0]["alert"] is False
    assert rows[0]["importance_score"] < 70
    assert critical_articles(rows, threshold=70) == []


def test_news_relevance_does_not_match_symbol_from_feed_name(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    from showme.engine.services.news_intelligence import enrich_articles

    rows = enrich_articles(
        [{
            "title": "Why shares of Altria Group soared in April",
            "summary": "Tobacco price hikes are driving earnings growth.",
            "feed": "Nasdaq AAPL symbol feed",
            "source": "rss",
            "published_at": datetime.now(timezone.utc).isoformat(),
        }],
        symbol="AAPL",
        query="AAPL",
        asset_class="EQUITY",
        threshold=70,
    )

    assert rows[0]["matched_terms"] == []
    assert "weak symbol/query match" in rows[0]["importance_reasons"]


def test_read_surfaces_saved_articles_not_placeholders(monkeypatch) -> None:
    """READ is now a persistent reading list (per its manifest) backed by the
    saved-articles store — it returns real saved rows, never a synthetic
    watchlist_cache placeholder."""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    from showme.engine.functions.news.read import READFunction
    from showme.engine.services.reading_list_store import ReadingListStore, SavedArticle

    store = ReadingListStore()
    store.clear()
    try:
        store.save(
            SavedArticle(
                article_id="",
                url="https://example.com/news",
                title="AAPL real headline",
                source="rss",
                matched_symbol="AAPL",
                status="unread",
            )
        )
        result = asyncio.run(READFunction().execute(watchlist=["AAPL"]))
        rows = result.data["rows"]
        assert len(rows) == 1
        assert rows[0]["title"] == "AAPL real headline"
        assert rows[0]["matched_symbol"] == "AAPL"
        assert "watchlist_cache" not in result.sources
        assert result.sources == ["internal_reading_list"]
    finally:
        store.clear()


def test_read_symbol_filter_scopes_the_queue(monkeypatch) -> None:
    """The watchlist/symbols filter scopes the saved-articles view to the
    matching symbol tag."""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    from showme.engine.functions.news.read import READFunction
    from showme.engine.services.reading_list_store import ReadingListStore, SavedArticle

    store = ReadingListStore()
    store.clear()
    try:
        store.save(SavedArticle(article_id="", url="https://example.com/btc",
                                title="fresh headline", source="rss",
                                matched_symbol="BTCUSDT", status="unread"))
        store.save(SavedArticle(article_id="", url="https://example.com/eth",
                                title="other headline", source="rss",
                                matched_symbol="ETHUSDT", status="unread"))
        result = asyncio.run(READFunction().execute(watchlist=["BTCUSDT"]))
        assert [row["title"] for row in result.data["rows"]] == ["fresh headline"]
        assert result.metadata["watchlist"] == ["BTCUSDT"]
    finally:
        store.clear()


def test_tldr_mover_lines_do_not_put_gainers_in_down_bucket(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    from showme.engine.functions.news.tldr import _format_movers

    quotes = [
        {"symbol": "AAPL", "change_pct": 3.32},
        {"symbol": "MSFT", "change_pct": 1.51},
        {"symbol": "BTCUSDT", "change_pct": -0.11},
    ]

    assert _format_movers(quotes, positive=True) == "AAPL (+3.32%), MSFT (+1.51%)"
    assert _format_movers(quotes, positive=False) == "BTCUSDT (-0.11%)"


def test_top_age_window_filters_stale_articles(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))
    from showme.engine.functions.news.top import _within_age_window

    assert _within_age_window(
        {"published_at": datetime.now(timezone.utc).isoformat()},
        45,
    )
    assert not _within_age_window(
        {"published_at": (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()},
        45,
    )
