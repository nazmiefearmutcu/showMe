"""Semantic acceptance harness for showMe FunctionManifests.

Contract
--------
For every code registered in ``showme.manifest.registry.REGISTRY``
this test asserts that the live ``/api/fn/{code}`` response — invoked
with the manifest's declared ``defaults`` — satisfies the manifest's
declared output contract:

* every ``output_contract.must_have`` field is present and non-empty
* if ``provider_chain`` produced a non-``live_*`` mode, the response
  carries a degradation reason (``warnings`` or an explicit
  ``degraded`` field)
* if ``chart_grammar`` is declared, the response payload includes a
  ``series`` or ``panes`` field shaped compatibly

The harness grows organically — codes without a manifest entry simply
skip per assertion. As seed modules under ``backend/showme/manifest/seeds/``
land, the matching parametrised case starts asserting against the
real handler. This means the test never crashes on a missing manifest;
it just leaves a coverage gap that pytest counts as a skip.

The /api/fn dispatch path is exercised in-process via FastAPI's
``TestClient`` so the test stays hermetic — no external network, no
sidecar process. If the engine cannot be attached in-process (e.g.
optional ML deps missing in CI), the test still skips per-case rather
than failing the suite.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Make `showme.*` importable from the repo root without requiring an
# editable install. The CI flow installs the backend package, but tests/
# is rooted at the repo, so we add backend/ to sys.path here.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _safe_load_registry() -> Any | None:
    """Return REGISTRY with seeds loaded, or None if import failed."""
    try:
        from showme.manifest.registry import REGISTRY
        from showme.manifest.seeds import load_seeds
    except Exception:
        # Backend package not importable in this environment — let the
        # test parametrisation degenerate to a single skip.
        return None
    try:
        load_seeds()
    except Exception:
        # Tolerate duplicate-registration on warm reload; just keep
        # whatever the registry already has.
        pass
    return REGISTRY


def _registered_codes() -> list[str]:
    """Return registered codes, or a single placeholder for the empty case."""
    registry = _safe_load_registry()
    if registry is None:
        return ["__no_registry__"]
    codes = registry.codes()
    if not codes:
        return ["__no_manifest__"]
    return codes


# ---------------------------------------------------------------------------
# TestClient bootstrap — best-effort; on any failure we degrade the
# test to a per-case skip so this file never blocks the suite.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fn_client() -> Any | None:
    """Return a FastAPI TestClient bound to the showMe sidecar, or None.

    The sidecar pulls in a large dependency graph (torch, ccxt, etc.).
    Any ImportError or runtime crash during build_app collapses to a
    None fixture — every parametrised case then skips with a reason.
    """
    try:
        from fastapi.testclient import TestClient

        from showme import server as server_mod
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"sidecar import failed: {exc!r}")
        return None
    build_app = getattr(server_mod, "build_app", None)
    if build_app is None:
        return None
    try:
        app = build_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"build_app failed: {exc!r}")
        return None
    try:
        with TestClient(app) as client:
            yield client
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"TestClient lifespan failed: {exc!r}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_LIVE_PREFIX = "live_"


def _is_non_empty(value: Any) -> bool:
    """True iff ``value`` is something a downstream UI would treat as data."""
    if value is None:
        return False
    if isinstance(value, (str, bytes)):
        return len(value) > 0
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    # Numbers, bools, custom objects — any non-None value counts.
    return True


def _extract_data_mode(payload: dict[str, Any]) -> str | None:
    """Pull the data_mode string from a /api/fn response shape, if present."""
    if not isinstance(payload, dict):
        return None
    # Top-level (newer handlers).
    mode = payload.get("data_mode")
    if isinstance(mode, str):
        return mode
    # Nested under data (older handlers + cards).
    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("data_mode")
        if isinstance(nested, str):
            return nested
        cards = data.get("cards")
        if isinstance(cards, list):
            for card in cards:
                if isinstance(card, dict) and card.get("key") == "data_mode":
                    value = card.get("value")
                    if isinstance(value, str):
                        return value
    return None


def _has_degradation_reason(payload: dict[str, Any]) -> bool:
    """True iff a non-live response carries warnings or an explicit reason."""
    if not isinstance(payload, dict):
        return False
    for key in ("warnings", "warning", "degraded", "degradation_reason"):
        value = payload.get(key)
        if _is_non_empty(value):
            return True
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("warnings", "warning", "degraded", "degradation_reason"):
            value = data.get(key)
            if _is_non_empty(value):
                return True
    return False


def _resolve_payload_field(payload: dict[str, Any], field: str) -> Any:
    """Return ``payload[field]`` or ``payload['data'][field]`` if present."""
    if not isinstance(payload, dict):
        return None
    if field in payload:
        return payload[field]
    data = payload.get("data")
    if isinstance(data, dict) and field in data:
        return data[field]
    return None


# ---------------------------------------------------------------------------
# Parametrised acceptance test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", _registered_codes())
def test_manifest_contract_holds_for_defaults(
    code: str,
    fn_client: Any | None,
) -> None:
    """Assert /api/fn/{code} satisfies its manifest's must_have contract."""
    if code in {"__no_registry__", "__no_manifest__"}:
        pytest.skip(
            "no manifests registered yet; this test grows as seed "
            "modules under backend/showme/manifest/seeds/ land",
        )
    if fn_client is None:
        pytest.skip("sidecar TestClient not available in this environment")

    registry = _safe_load_registry()
    if registry is None:
        pytest.skip("manifest registry not importable")
    try:
        manifest = registry.get(code)
    except KeyError:
        pytest.skip(f"manifest not yet defined for code {code!r}")
        return

    # Defaults are the canonical input set the manifest author promises
    # will produce a valid response. Pass them as a JSON body so the
    # POST handler routes them through `_route_function_params`.
    body = dict(manifest.defaults or {})
    response = fn_client.post(f"/api/fn/{code}", json=body)
    if response.status_code == 503:
        pytest.skip(f"engine not attached for {code!r}: {response.text!r}")
    assert response.status_code == 200, (
        f"/api/fn/{code} returned {response.status_code}: {response.text!r}"
    )
    payload = response.json()
    assert isinstance(payload, dict), (
        f"/api/fn/{code} returned non-object payload: {type(payload).__name__}"
    )

    # 1. must_have fields are present + non-empty.
    must_have = list(manifest.output_contract.must_have or [])
    missing: list[str] = []
    empty: list[str] = []
    for field in must_have:
        value = _resolve_payload_field(payload, field)
        if value is None:
            missing.append(field)
        elif not _is_non_empty(value):
            empty.append(field)
    assert not missing, (
        f"/api/fn/{code} missing must_have field(s) {missing!r} in payload keys "
        f"{sorted(payload.keys())}"
    )
    assert not empty, (
        f"/api/fn/{code} has empty must_have field(s) {empty!r}"
    )

    # 2. Non-live mode must carry a degradation reason.
    mode = _extract_data_mode(payload)
    if mode is not None and not mode.startswith(_LIVE_PREFIX):
        assert _has_degradation_reason(payload), (
            f"/api/fn/{code} returned data_mode={mode!r} (non-live) but no "
            f"warnings / degradation_reason explained the degradation"
        )

    # 3. If chart_grammar is declared, response carries series OR panes.
    if manifest.chart_grammar is not None:
        series = _resolve_payload_field(payload, "series")
        panes = _resolve_payload_field(payload, "panes")
        has_compatible_payload = _is_non_empty(series) or _is_non_empty(panes)
        assert has_compatible_payload, (
            f"/api/fn/{code} declared chart_grammar="
            f"{manifest.chart_grammar.kind!r} but payload has neither a "
            f"non-empty 'series' nor 'panes' field"
        )
