"""FastAPI route tests for /api/templates/*."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from showme.server import build_app


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    # Reset singleton
    import showme.server_routes.templates as tmod
    tmod._CATALOG = None
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def test_list_returns_12(client):
    r = client.get("/api/templates")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 12
    ids = {e["id"] for e in body}
    assert {"rsi-mean-revert", "macd-cross", "ema-crossover", "golden-cross"}.issubset(ids)


def test_detail_returns_entry(client):
    r = client.get("/api/templates/rsi-mean-revert")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "rsi-mean-revert"
    assert body["uses_indicators"] == ["rsi"]
    assert "spec_template" in body


def test_detail_unknown_404(client):
    r = client.get("/api/templates/not-real")
    assert r.status_code == 404


def test_instantiate_creates_strategy(client):
    r = client.post("/api/templates/rsi-mean-revert/instantiate",
                    json={"name": "My RSI", "symbol": "ETH/USDT"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["template_id"] == "rsi-mean-revert"
    spec = body["strategy"]
    assert spec["name"] == "My RSI"
    assert spec["asset_filter"]["symbols"] == ["ETH/USDT"]
    # Now confirm it persisted:
    listed = client.get("/api/strategies").json()
    ids = {r["id"] for r in listed["records"]}
    assert spec["id"] in ids


def test_instantiate_unknown_404(client):
    r = client.post("/api/templates/not-real/instantiate", json={})
    assert r.status_code == 404


def test_instantiate_default_name_used_when_no_override(client):
    r = client.post("/api/templates/macd-cross/instantiate", json={})
    assert r.status_code == 200, r.text
    spec = r.json()["strategy"]
    assert spec["name"] == "MACD Crossover"  # template's default name


# ── Agent 2 regression tests (BOT_AUDIT_REPORT.md H-API-5) ──────────────


def test_instantiate_rejects_list_symbol(client):
    """H-API-5 — ``symbol=["BTC","ETH"]`` used to coerce to the literal
    ``"['BTC', 'ETH']"``. Now it's a 422 instead of silent corruption.
    """
    r = client.post("/api/templates/rsi-mean-revert/instantiate", json={
        "symbol": ["BTC/USDT", "ETH/USDT"],
    })
    assert r.status_code == 422, r.text


def test_instantiate_rejects_whitespace_only_symbol(client):
    """MEDIUM (whitespace symbol reject)."""
    r = client.post("/api/templates/rsi-mean-revert/instantiate", json={
        "symbol": "   ",
    })
    # Empty / whitespace falls into the falsy branch before
    # ``_coerce_symbol`` runs (``if payload["symbol"]:``), so the template
    # is instantiated without an asset-filter override. The contract says
    # NEVER persist a whitespace-only symbol — empty payload is fine, but
    # a non-empty whitespace string must be rejected.
    # ``"   "`` is truthy (non-empty string) → enters _coerce_symbol →
    # trimmed empty → 422.
    assert r.status_code == 422, r.text


def test_instantiate_rejects_newline_symbol(client):
    """LOW (control char reject) — defense-in-depth against log injection."""
    r = client.post("/api/templates/rsi-mean-revert/instantiate", json={
        "symbol": "BTC/USDT\ninjected",
    })
    assert r.status_code == 422, r.text


def test_instantiate_rejects_unformatted_symbol(client):
    """H-API-5 — ``BTCUSDT`` (no slash) and ``BTC-USDT`` fail format check."""
    for bad in ("BTCUSDT", "BTC-USDT", "BTC", "/USDT", "BTC/"):
        r = client.post("/api/templates/rsi-mean-revert/instantiate", json={
            "symbol": bad,
        })
        assert r.status_code == 422, f"expected 422 for {bad!r}, got {r.status_code}"


def test_instantiate_normalises_symbol_case_and_whitespace(client):
    """H-API-5 — ``"  btc/usdt  "`` is normalised to ``"BTC/USDT"``."""
    r = client.post("/api/templates/rsi-mean-revert/instantiate", json={
        "symbol": "  eth/usdt  ",
    })
    assert r.status_code == 200, r.text
    spec = r.json()["strategy"]
    assert spec["asset_filter"]["symbols"] == ["ETH/USDT"]


def test_instantiate_rejects_non_string_name(client):
    """H-API-5 — ``name=[...]`` was silently turned into ``"[...]"``."""
    r = client.post("/api/templates/rsi-mean-revert/instantiate", json={
        "name": ["a", "b"],
    })
    assert r.status_code == 422, r.text
