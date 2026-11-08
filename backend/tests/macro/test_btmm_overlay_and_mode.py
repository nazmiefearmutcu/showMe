"""BTMM#2 / BTMM#4: the implied-path overlay and provider_mode must be honoured
or reported honestly, and the seed must name the provider that supplies the rows.

BTMM#2: ``overlay_implied_path`` used to be ignored (no implied block, no
warning) and ``provider_mode`` was never read, so the response always claimed
the requested mode. Now the overlay returns an explicit provider_unavailable
block when requested, and the response reports the data mode actually used.

BTMM#4: the seed declared ``primary="fred"`` although every row comes from BIS
CBPOL.

All tests are offline: the BIS loader is faked, or httpx is replaced by a fake
client and SHOWME_HOME points at a temporary cache directory.
"""

from __future__ import annotations

import asyncio
import io
import sys
import zipfile
from datetime import date
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import showme.engine.functions.macro.btmm as btmm  # noqa: E402
from showme.engine.functions.macro.btmm import BTMMFunction  # noqa: E402


def _rows() -> list[dict]:
    return [
        {
            "country_code": "US",
            "country": "United States",
            "policy_rate": 3.75,
            "change_bp": -25.0,
            "last_move": "cut",
            "region": "americas",
            "as_of": date.today().isoformat(),
            "source": "BIS CBPOL",
        }
    ]


def _run_with_loader(monkeypatch, loader, **params):
    monkeypatch.setattr(btmm, "_load_bis_rows", loader)
    return asyncio.run(BTMMFunction().execute(**params))


# ---------------------------------------------------------------- BTMM#2 overlay


def test_overlay_requested_reports_explicit_unavailable_block(monkeypatch) -> None:
    result = _run_with_loader(
        monkeypatch,
        lambda _t, _f=False: _rows(),
        country="US",
        overlay_implied_path=True,
    )

    block = result.data.get("implied_path")
    assert isinstance(block, dict), result.data.keys()
    assert block["status"] == "provider_unavailable", block
    assert block["points"] == []
    assert result.data["rows"], "policy-rate rows still come from BIS CBPOL"
    assert any("implied_path_unavailable" in w for w in result.warnings), result.warnings


def test_overlay_not_requested_is_marked_not_requested(monkeypatch) -> None:
    result = _run_with_loader(monkeypatch, lambda _t, _f=False: _rows(), country="US")

    block = result.data.get("implied_path")
    assert block == {"status": "not_requested", "points": []}, block
    assert not any("implied_path" in w for w in result.warnings)


# ------------------------------------------------------------- BTMM#2 provider_mode


def test_provider_mode_reports_mode_actually_served(monkeypatch, isolated_bis_cache) -> None:
    # Drive the real loader (fake httpx client) so the served mode is recorded
    # by the code under test, not supplied by a stub loader.
    _fake_bis_network(monkeypatch)

    result = asyncio.run(BTMMFunction().execute(country="US", provider_mode="live_official"))

    assert result.data["requested_mode"] == "live_official", result.data
    assert result.data["data_mode"] == "live_official", result.data


def test_requested_mode_differing_from_served_mode_is_warned(monkeypatch, isolated_bis_cache) -> None:
    _fake_bis_network(monkeypatch)

    result = asyncio.run(BTMMFunction().execute(country="US", provider_mode="cached_snapshot"))

    assert result.data["requested_mode"] == "cached_snapshot", result.data
    assert result.data["data_mode"] == "live_official", result.data
    assert any("provider_mode_differs" in w for w in result.warnings), result.warnings


def _bis_zip_bytes() -> bytes:
    today = date.today().isoformat()
    text = (
        "FREQ,Frequency,REF_AREA,Reference area,2026-01-01," + today + "\n"
        "D,Daily,US,United States,4.00,3.75\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("WS_CBPOL.csv", text)
    return buffer.getvalue()


@pytest.fixture
def isolated_bis_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setattr(btmm, "_CACHE_ROWS", None)
    monkeypatch.setattr(btmm, "_CACHE_AT", 0.0)
    monkeypatch.setattr(btmm, "_CACHE_ORIGIN", None)
    return tmp_path


def _fake_bis_network(monkeypatch) -> None:
    payload = _bis_zip_bytes()

    class _Response:
        content = payload

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> bool:
            return False

        def get(self, *_args, **_kwargs):
            return _Response()

    monkeypatch.setattr(httpx, "Client", _Client)


def test_network_fetch_is_reported_as_live_official(monkeypatch, isolated_bis_cache) -> None:
    _fake_bis_network(monkeypatch)

    result = asyncio.run(BTMMFunction().execute(country="US", provider_mode="live_official"))

    assert result.data["status"] == "ok", result.data
    assert result.data["data_mode"] == "live_official"
    assert result.metadata["data_mode"] == "live_official"


def test_disk_cache_serve_is_reported_as_cached_snapshot(monkeypatch, isolated_bis_cache) -> None:
    cache_path = btmm._disk_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(_bis_zip_bytes())

    def _no_network(*_args, **_kwargs):
        raise AssertionError("a fresh disk cache must not trigger a network call")

    monkeypatch.setattr(httpx, "Client", _no_network)

    result = asyncio.run(BTMMFunction().execute(country="US", provider_mode="live_official"))

    assert result.data["status"] == "ok", result.data
    assert result.data["data_mode"] == "cached_snapshot", result.data
    assert result.data["requested_mode"] == "live_official"
    assert any("provider_mode" in w for w in result.warnings), result.warnings


# ------------------------------------------------------------------- BTMM#4 seed


def test_btmm_seed_names_bis_as_primary_provider() -> None:
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    btmm_manifest = REGISTRY.get("BTMM")
    assert btmm_manifest.provider_chain.primary == "bis_cbpol", (
        "every BTMM row is read from BIS CBPOL, so the seed must not name fred; "
        f"got {btmm_manifest.provider_chain.primary!r}"
    )


def test_stale_bis_observation_is_a_warning_not_a_provider_error(monkeypatch) -> None:
    # BTMM#4: data staleness is a data-age notice, not a provider failure, so it
    # must not be filed under metadata.provider_errors.
    from datetime import timedelta

    stale = _rows()
    stale[0]["as_of"] = (date.today() - timedelta(days=10)).isoformat()
    result = _run_with_loader(monkeypatch, lambda _t, _f=False: stale, country="US")

    assert any(w.startswith("data_stale_24h") for w in result.warnings), result.warnings
    assert "provider_errors" not in (result.metadata or {}), result.metadata
