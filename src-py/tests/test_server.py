"""Sidecar boot/runtime helpers."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from showme import server


def test_prepare_writable_cwd_is_noop_outside_frozen(monkeypatch) -> None:
    monkeypatch.delattr(server.sys, "_MEIPASS", raising=False)

    assert server.prepare_writable_cwd() is None


def test_prepare_writable_cwd_moves_frozen_runtime_to_app_home(
    monkeypatch,
    tmp_path: Path,
) -> None:
    frozen_extract = tmp_path / "_MEI"
    app_home = tmp_path / "app-home"
    frozen_extract.mkdir()
    monkeypatch.setattr(server.sys, "_MEIPASS", str(frozen_extract), raising=False)
    monkeypatch.setenv("SHOWME_HOME", str(app_home))
    monkeypatch.chdir(frozen_extract)

    resolved = server.prepare_writable_cwd()

    assert resolved == app_home
    assert Path.cwd() == app_home
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
    assert server.default_asset_class_name("eth-usd") == "CRYPTO"
    assert server.default_asset_class_name("SOL/USDC") == "CRYPTO"
    assert server.default_asset_class_name("AAPL") == "EQUITY"
    assert server.default_asset_class_name("EURUSD") == "FX"
    assert server.default_asset_class_name("GBPUSD=X") == "FX"
    assert server.default_asset_class_name("GC=F") == "COMMODITY"
    assert server.default_asset_class_name("XAUUSD") == "COMMODITY"
    assert server.default_asset_class_name("^GSPC") == "INDEX"


def test_default_asset_class_respects_explicit_request() -> None:
    assert server.default_asset_class_name("BTCUSDT", "equity") == "EQUITY"


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


def test_sanitize_suppresses_template_payloads() -> None:
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

    assert payload["sources"] == ["no_live_source"]
    assert payload["metadata"]["synthetic"] is True
    assert payload["data"]["status"] == "provider_unavailable"
    assert payload["data"]["rows"] == []


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


def test_agent_candidate_parser_infers_market_classes() -> None:
    rows = server._parse_agent_candidates("btcusdt, AAPL, EURUSD, GC=F")

    assert rows == [
        {"symbol": "BTCUSDT", "asset_class": "CRYPTO"},
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
