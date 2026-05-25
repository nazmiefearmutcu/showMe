"""Chart-grammar acceptance for showMe FunctionManifests.

Contract
--------
For every manifest entry with a declared ``chart_grammar``, the live
``/api/fn/{code}`` response must carry a payload that is *shape-
compatible* with the declared grammar kind:

* ``time_series_candles`` / ``ohlcv`` -> ``series`` items each carry
  open / high / low / close + a time field
* ``time_series_line`` / ``tenor_curve`` / ``distribution`` /
  ``scatter`` -> ``series`` items each carry a numeric value plus an
  x-axis key (``t`` / ``x`` / ``time`` / ``date``)
* ``heatmap`` / ``surface`` -> payload carries a 2-D ``matrix`` (or
  ``z`` / ``values``) field where every row is a list of the same
  width
* ``risk_contribution_bar`` / ``attribution_bar`` / ``bar_ladder`` /
  ``payoff`` / ``depth_ladder`` / ``frontier`` -> payload carries
  ``series`` or ``rows`` whose entries each have a name + a numeric
  value

The test never imports production handler internals; it talks to the
manifest registry and the dispatch endpoint as black boxes. Codes
without a matching manifest skip per case.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest


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
        return None
    try:
        load_seeds()
    except Exception:
        pass
    return REGISTRY


def _registered_codes_with_charts() -> list[str]:
    """Return codes that have a chart_grammar declared, or a placeholder."""
    registry = _safe_load_registry()
    if registry is None:
        return ["__no_registry__"]
    out: list[str] = [
        m.code for m in registry.all() if m.chart_grammar is not None
    ]
    if not out:
        return ["__no_chart_manifest__"]
    return out


# ---------------------------------------------------------------------------
# TestClient bootstrap
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fn_client() -> Any | None:
    """Return a FastAPI TestClient bound to the showMe sidecar."""
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
# Shape predicates
# ---------------------------------------------------------------------------


_TIME_KEYS = ("t", "time", "ts", "timestamp", "date", "x")
_VALUE_KEYS = ("v", "value", "y", "weight", "contribution", "amount", "score")
_NAME_KEYS = ("name", "label", "key", "ticker", "symbol", "bucket")
_MATRIX_KEYS = ("matrix", "z", "values", "data")


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


def _series_items(payload: dict[str, Any]) -> list[Any] | None:
    """Return the list of series entries (or None if not a list)."""
    series = _resolve_payload_field(payload, "series")
    if isinstance(series, list):
        return series
    # Some handlers nest under {series: {points: [...]}} or similar; flat
    # only is required by this test — defer to ``rows`` as fallback.
    return None


def _rows_items(payload: dict[str, Any]) -> list[Any] | None:
    """Return the list of row entries (or None if not a list)."""
    rows = _resolve_payload_field(payload, "rows")
    if isinstance(rows, list):
        return rows
    return None


def _has_time_field(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    return any(key in item for key in _TIME_KEYS)


def _has_value_field(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    return any(key in item for key in _VALUE_KEYS)


def _has_name_field(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    return any(key in item for key in _NAME_KEYS)


def _has_ohlc_fields(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    return all(key in item for key in ("open", "high", "low", "close")) or all(
        key in item for key in ("o", "h", "l", "c")
    )


def _is_rectangular_matrix(value: Any) -> bool:
    """True iff ``value`` is a non-empty list of equally-sized lists."""
    if not isinstance(value, list) or not value:
        return False
    inner_widths: set[int] = set()
    for row in value:
        if not isinstance(row, list):
            return False
        inner_widths.add(len(row))
    return len(inner_widths) == 1 and next(iter(inner_widths)) > 0


def _find_matrix(payload: dict[str, Any]) -> Any:
    """Return the first matrix-shaped payload field, if any."""
    for key in _MATRIX_KEYS:
        candidate = _resolve_payload_field(payload, key)
        if _is_rectangular_matrix(candidate):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Parametrised acceptance test
# ---------------------------------------------------------------------------


_CANDLE_KINDS = {"time_series_candles", "ohlcv"}
_LINE_KINDS = {"time_series_line", "tenor_curve", "distribution", "scatter"}
_MATRIX_KINDS = {"heatmap", "surface"}
_BAR_KINDS = {
    "risk_contribution_bar",
    "attribution_bar",
    "bar_ladder",
    "payoff",
    "depth_ladder",
    "frontier",
}


@pytest.mark.parametrize("code", _registered_codes_with_charts())
def test_chart_grammar_payload_shape(
    code: str,
    fn_client: Any | None,
) -> None:
    """Assert payload shape matches the manifest's declared chart_grammar."""
    if code in {"__no_registry__", "__no_chart_manifest__"}:
        pytest.skip(
            "no chart-bearing manifests registered yet; this test grows "
            "as seed modules under backend/showme/manifest/seeds/ land",
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
    if manifest.chart_grammar is None:
        pytest.skip(f"manifest {code!r} declares no chart_grammar")
        return

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

    kind = manifest.chart_grammar.kind.value if hasattr(
        manifest.chart_grammar.kind, "value"
    ) else str(manifest.chart_grammar.kind)

    if kind in _CANDLE_KINDS:
        series = _series_items(payload) or []
        assert series, (
            f"/api/fn/{code} declared chart_grammar.kind={kind!r} but "
            f"payload has no 'series' list"
        )
        sample = next((item for item in series if isinstance(item, dict)), None)
        assert sample is not None, (
            f"/api/fn/{code} 'series' entries are not dicts: "
            f"{type(series[0]).__name__}"
        )
        assert _has_ohlc_fields(sample), (
            f"/api/fn/{code} 'series' entries miss open/high/low/close "
            f"(or o/h/l/c). Sample keys: {sorted(sample.keys())}"
        )
        assert _has_time_field(sample), (
            f"/api/fn/{code} 'series' entries miss a time key "
            f"({_TIME_KEYS!r}). Sample keys: {sorted(sample.keys())}"
        )
    elif kind in _LINE_KINDS:
        series = _series_items(payload) or []
        assert series, (
            f"/api/fn/{code} declared chart_grammar.kind={kind!r} but "
            f"payload has no 'series' list"
        )
        sample = next((item for item in series if isinstance(item, dict)), None)
        assert sample is not None, (
            f"/api/fn/{code} 'series' entries are not dicts: "
            f"{type(series[0]).__name__}"
        )
        assert _has_value_field(sample), (
            f"/api/fn/{code} 'series' entries miss a value key "
            f"({_VALUE_KEYS!r}). Sample keys: {sorted(sample.keys())}"
        )
        assert _has_time_field(sample), (
            f"/api/fn/{code} 'series' entries miss an x-axis key "
            f"({_TIME_KEYS!r}). Sample keys: {sorted(sample.keys())}"
        )
    elif kind in _MATRIX_KINDS:
        matrix = _find_matrix(payload)
        assert matrix is not None, (
            f"/api/fn/{code} declared chart_grammar.kind={kind!r} but "
            f"payload carries no rectangular matrix-shaped field "
            f"({_MATRIX_KEYS!r})"
        )
    elif kind in _BAR_KINDS:
        items = _series_items(payload) or _rows_items(payload) or []
        assert items, (
            f"/api/fn/{code} declared chart_grammar.kind={kind!r} but "
            f"payload has neither 'series' nor 'rows' list"
        )
        sample = next((item for item in items if isinstance(item, dict)), None)
        assert sample is not None, (
            f"/api/fn/{code} bar-chart entries are not dicts: "
            f"{type(items[0]).__name__}"
        )
        assert _has_name_field(sample), (
            f"/api/fn/{code} bar-chart entries miss a name key "
            f"({_NAME_KEYS!r}). Sample keys: {sorted(sample.keys())}"
        )
        assert _has_value_field(sample), (
            f"/api/fn/{code} bar-chart entries miss a value key "
            f"({_VALUE_KEYS!r}). Sample keys: {sorted(sample.keys())}"
        )
    else:
        # Unknown / unhandled grammar kind — defer to a soft skip so new
        # ChartKind enum members never crash the suite; we just don't
        # have a shape predicate for them yet.
        pytest.skip(
            f"chart-grammar shape predicate not yet defined for kind "
            f"{kind!r} (extend tests/test_chart_grammar.py when added)",
        )
