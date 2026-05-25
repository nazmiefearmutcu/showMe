"""Tests for the FunctionManifest contract (spec + registry + route)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from showme.manifest import (
    REGISTRY,
    AssetClass,
    Category,
    ChartKind,
    ControlKind,
    DataMode,
    FunctionManifest,
    ManifestRegistry,
    load_seeds,
    manifest,
)
from showme.manifest.spec import (
    CachingPolicy,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
)


def _minimal_manifest(code: str = "TST") -> FunctionManifest:
    """Build a minimal but valid FunctionManifest for registry tests."""
    return FunctionManifest(
        code=code,
        name=f"Test {code}",
        category=Category.MISC,
        intent="Test stub for registry round-trip.",
        asset_classes=[AssetClass.EQUITY],
        inputs=[],
        defaults={},
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=[],
            acceptable_modes=[DataMode.LIVE_OFFICIAL],
        ),
        caching=CachingPolicy(ttl_seconds=0, scope="global", persist=False),
        output_contract=OutputContract(must_have=[]),
        chart_grammar=None,
        table_schema=None,
        card_schema=None,
        methodology="Trivial.",
        formula_dict={},
        field_dict={},
        provenance=ProvenanceSpec(),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="noop",
                description="placeholder",
                inputs={},
                assertions=["true"],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Spec / seed validation
# ---------------------------------------------------------------------------


def test_example_gp_manifest_valid() -> None:
    """Importing the GP seed must register a valid FunctionManifest."""
    load_seeds()
    entry = REGISTRY.get("GP")
    assert entry.code == "GP"
    assert entry.category == Category.CHARTS_TECH
    assert AssetClass.EQUITY in entry.asset_classes
    assert AssetClass.CRYPTO in entry.asset_classes
    # Sanity: chart grammar wires through to the candle kind.
    assert entry.chart_grammar is not None
    assert entry.chart_grammar.kind == ChartKind.TIME_SERIES_CANDLES
    # Input list mirrors the spec controls. GP exposes symbol + range
    # + interval + provider_mode (the design at docs/rebuild/manifests/wave1/GP.md
    # uses select controls for range/interval rather than a free date_range).
    control_kinds = {i.control for i in entry.inputs}
    assert ControlKind.SYMBOL_PICKER in control_kinds
    assert ControlKind.PROVIDER_MODE in control_kinds
    # At least one semantic test is required by the schema.
    assert entry.semantic_tests, "GP must declare at least one semantic test"


# ---------------------------------------------------------------------------
# Registry behaviour
# ---------------------------------------------------------------------------


def test_registry_register_then_get() -> None:
    reg = ManifestRegistry()
    m = _minimal_manifest("RT1")
    reg.register(m)
    assert "RT1" in reg
    assert reg.get("RT1") is m
    assert reg.codes() == ["RT1"]
    assert reg.all() == [m]


def test_registry_duplicate_register_raises() -> None:
    reg = ManifestRegistry()
    m = _minimal_manifest("DUP")
    reg.register(m)
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_minimal_manifest("DUP"))


def test_manifest_decorator_registers_into_target() -> None:
    """The @manifest decorator should register into the requested registry."""
    reg = ManifestRegistry()

    @manifest(registry=reg)
    def _factory() -> FunctionManifest:
        return _minimal_manifest("DEC")

    assert "DEC" in reg
    # The decorator replaces the symbol with the manifest itself.
    assert isinstance(_factory, FunctionManifest)
    assert _factory.code == "DEC"


# ---------------------------------------------------------------------------
# HTTP route smoke
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    try:
        from fastapi.testclient import TestClient  # noqa: F401
    except ImportError:  # pragma: no cover
        pytest.skip("fastapi.testclient not installed")
    try:
        from showme.server import build_app
    except Exception as exc:  # pragma: no cover - environment issue
        pytest.skip(f"showme.server unavailable: {exc}")

    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    # Force a fresh seed-load on import in the route module.
    import showme.server_routes.manifest as mroute
    mroute._SEEDS_LOADED = False

    from fastapi.testclient import TestClient

    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def test_manifest_route_lists_all(client: Any) -> None:
    r = client.get("/api/manifest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    codes = {entry["code"] for entry in body}
    assert "GP" in codes


def test_manifest_route_get_one(client: Any) -> None:
    r = client.get("/api/manifest/GP")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == "GP"
    assert body["category"] == Category.CHARTS_TECH.value
    assert body["chart_grammar"]["kind"] == ChartKind.TIME_SERIES_CANDLES.value
    # 404 path
    r404 = client.get("/api/manifest/ZZZ_NOT_REAL")
    assert r404.status_code == 404
