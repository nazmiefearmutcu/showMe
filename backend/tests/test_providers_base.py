"""Tests for the provider adapter layer.

All HTTP calls are stubbed — no real network. We monkeypatch the shared
``httpx.AsyncClient`` returned by ``_http.get_client`` with a fake that
implements ``get`` / ``post`` and the response surface our adapters use.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from showme.providers import (
    AdapterError,
    AdapterRegistry,
    DataMode,
    FredAdapter,
    OpenFigiAdapter,
    ProviderAdapter,
    REGISTRY,
    SecEdgarAdapter,
    TreasuryDirectAdapter,
    chain,
)
from showme.providers import _http


# ---- fixtures ---------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test gets a clean registry; restore the original after."""
    saved = list(REGISTRY.all())
    REGISTRY.clear()
    yield
    REGISTRY.clear()
    for adapter in saved:
        REGISTRY.register(adapter)


def _fake_response(payload: Any, status: int = 200) -> MagicMock:
    """Build a httpx-Response-shaped mock."""
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=payload)
    resp.text = json.dumps(payload) if not isinstance(payload, str) else payload
    if 200 <= status < 400:
        resp.raise_for_status = MagicMock(return_value=None)
    else:
        from httpx import HTTPStatusError, Request, Response

        req = Request("GET", "http://test")
        real = Response(status, request=req)
        err = HTTPStatusError(f"HTTP {status}", request=req, response=real)
        resp.raise_for_status = MagicMock(side_effect=err)
    return resp


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    get_payload: Any = None,
    post_payload: Any = None,
    get_status: int = 200,
    post_status: int = 200,
) -> MagicMock:
    """Replace ``_http.get_client`` with a coroutine that yields a fake client."""
    fake = MagicMock()
    fake.is_closed = False
    fake.get = AsyncMock(return_value=_fake_response(get_payload, get_status))
    fake.post = AsyncMock(return_value=_fake_response(post_payload, post_status))
    fake.aclose = AsyncMock(return_value=None)

    async def _get_client() -> Any:
        return fake

    # Patch every name that imports get_client; they all re-export the
    # same callable so one patch is enough — but our adapters reach into
    # the function under `from ._http import get_client`, which binds the
    # name into each adapter module. Patch at every binding site.
    monkeypatch.setattr(_http, "get_client", _get_client)
    import showme.providers.sec_edgar as sec_mod
    import showme.providers.fred as fred_mod
    import showme.providers.treasury_direct as td_mod
    import showme.providers.openfigi as of_mod

    monkeypatch.setattr(sec_mod, "get_client", _get_client)
    monkeypatch.setattr(fred_mod, "get_client", _get_client)
    monkeypatch.setattr(td_mod, "get_client", _get_client)
    monkeypatch.setattr(of_mod, "get_client", _get_client)
    return fake


# ---- enum + base contract --------------------------------------------


def test_data_mode_values_stable():
    """The enum's string values are part of the public JSON contract."""
    assert DataMode.LIVE_OFFICIAL.value == "live_official"
    assert DataMode.LIVE_EXCHANGE.value == "live_exchange"
    assert DataMode.DELAYED_REFERENCE.value == "delayed_reference"
    assert DataMode.MODELED.value == "modeled"
    assert DataMode.CACHED_SNAPSHOT.value == "cached_snapshot"
    assert DataMode.PROVIDER_UNAVAILABLE.value == "provider_unavailable"
    assert DataMode.NOT_CONFIGURED.value == "not_configured"
    # Exactly seven members; no accidental extras.
    assert len(list(DataMode)) == 7


def test_registry_register_get():
    reg = AdapterRegistry()

    class _DummyAdapter(ProviderAdapter):
        name = "dummy"

        def capabilities(self):
            return {"x"}

    a = _DummyAdapter()
    reg.register(a)
    assert reg.get("dummy") is a
    assert reg.get("nope") is None
    assert reg.all() == [a]
    assert reg.names() == ["dummy"]


def test_registry_rejects_empty_name():
    reg = AdapterRegistry()

    class _Nameless(ProviderAdapter):
        name = ""

        def capabilities(self):
            return set()

    with pytest.raises(ValueError):
        reg.register(_Nameless())


def test_adapter_mode_default_logic():
    """Default mode resolution: error → UNAVAILABLE, key issue → NOT_CONFIGURED."""

    class _OkAdapter(ProviderAdapter):
        name = "ok"

        def capabilities(self):
            return set()

    a = _OkAdapter()
    # Nominal: no error, default auth_state "not_required" → LIVE_OFFICIAL.
    assert a.mode() == DataMode.LIVE_OFFICIAL

    # Record an error → PROVIDER_UNAVAILABLE.
    a._record_failure(RuntimeError("boom"))
    assert a.mode() == DataMode.PROVIDER_UNAVAILABLE

    # Recovery clears it.
    a._record_success(42)
    assert a.mode() == DataMode.LIVE_OFFICIAL
    assert a.last_latency_ms() == 42

    class _NoKey(ProviderAdapter):
        name = "nokey"

        def capabilities(self):
            return set()

        def auth_state(self):
            return "missing_key"

    nk = _NoKey()
    assert nk.mode() == DataMode.NOT_CONFIGURED

    class _BadKey(ProviderAdapter):
        name = "badkey"

        def capabilities(self):
            return set()

        def auth_state(self):
            return "invalid_key"

    assert _BadKey().mode() == DataMode.NOT_CONFIGURED


def test_chain_skips_not_configured_fallbacks():
    """``chain`` yields primary always, and only configured fallbacks."""

    class _OkAdapter(ProviderAdapter):
        name = "p"

        def capabilities(self):
            return set()

    class _Unconfigured(ProviderAdapter):
        name = "u"

        def capabilities(self):
            return set()

        def auth_state(self):
            return "missing_key"

    class _OkB(ProviderAdapter):
        name = "b"

        def capabilities(self):
            return set()

    REGISTRY.register(_OkAdapter())
    REGISTRY.register(_Unconfigured())
    REGISTRY.register(_OkB())
    seq = list(chain("p", ["u", "b"]))
    names = [a.name for a in seq]
    assert names == ["p", "b"]


# ---- SEC EDGAR --------------------------------------------------------


@pytest.mark.asyncio
async def test_sec_edgar_lookup_cik_offline(monkeypatch: pytest.MonkeyPatch):
    """Verify CIK extraction from the canonical SEC payload shape."""
    payload = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp."},
    }
    fake = _install_fake_client(monkeypatch, get_payload=payload)

    adapter = SecEdgarAdapter()
    cik = await adapter.lookup_cik("aapl")  # case-insensitive
    assert cik == "0000320193"
    cik2 = await adapter.lookup_cik("MSFT")
    assert cik2 == "0000789019"

    # Unknown ticker returns None without raising.
    assert await adapter.lookup_cik("ZZZZZ") is None

    # Only one HTTP call should have fired — the bootstrap fetch is cached.
    assert fake.get.call_count == 1

    # Latency was recorded on success; no error pending.
    assert adapter.last_latency_ms() is not None
    assert adapter.mode() == DataMode.LIVE_OFFICIAL


@pytest.mark.asyncio
async def test_sec_edgar_get_submissions_uses_padded_cik(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = _install_fake_client(monkeypatch, get_payload={"filings": {}})
    adapter = SecEdgarAdapter()
    await adapter.get_submissions("320193")
    # The URL has to embed the 10-digit padded form.
    called_url = fake.get.call_args.args[0]
    assert "CIK0000320193.json" in called_url


@pytest.mark.asyncio
async def test_sec_edgar_records_failure_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
):
    _install_fake_client(monkeypatch, get_payload={"err": "boom"}, get_status=500)
    adapter = SecEdgarAdapter()
    with pytest.raises(AdapterError):
        await adapter.get_submissions("320193")
    assert adapter.mode() == DataMode.PROVIDER_UNAVAILABLE


# ---- FRED -------------------------------------------------------------


def test_fred_auth_state_missing_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    adapter = FredAdapter()
    assert adapter.auth_state() == "missing_key"
    assert adapter.mode() == DataMode.NOT_CONFIGURED


def test_fred_auth_state_ok_when_key_present(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key-abc")
    adapter = FredAdapter()
    assert adapter.auth_state() == "ok"
    assert adapter.mode() == DataMode.LIVE_OFFICIAL


@pytest.mark.asyncio
async def test_fred_get_series_offline(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    payload = {
        "observations": [
            {"date": "2024-01-01", "value": "5.25"},
            {"date": "2024-02-01", "value": "5.30"},
        ]
    }
    fake = _install_fake_client(monkeypatch, get_payload=payload)
    adapter = FredAdapter()
    out = await adapter.get_series("DGS10", start="2024-01-01")
    assert out["observations"][0]["value"] == "5.25"
    # API key + file_type must be in the params.
    params = fake.get.call_args.kwargs.get("params") or {}
    assert params.get("api_key") == "test-key"
    assert params.get("file_type") == "json"
    assert params.get("series_id") == "DGS10"
    assert params.get("observation_start") == "2024-01-01"


@pytest.mark.asyncio
async def test_fred_raises_when_key_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    _install_fake_client(monkeypatch, get_payload={})
    adapter = FredAdapter()
    with pytest.raises(AdapterError):
        await adapter.get_series("DGS10")
    # auth_state still wins — missing_key, not unavailable.
    assert adapter.mode() == DataMode.NOT_CONFIGURED


# ---- TreasuryDirect ---------------------------------------------------


@pytest.mark.asyncio
async def test_treasury_query_offline(monkeypatch: pytest.MonkeyPatch):
    payload = {
        "data": [
            {"cusip": "912796XX0", "security_type": "Bill", "auction_date": "2026-05-22"}
        ],
        "meta": {"count": 1},
    }
    fake = _install_fake_client(monkeypatch, get_payload=payload)
    adapter = TreasuryDirectAdapter()
    out = await adapter.query_auctions(
        filters={"security_type": "Bill", "record_date": "gte:2026-01-01"},
        fields=["cusip", "security_type", "auction_date"],
        sort="-auction_date",
    )
    assert out["data"][0]["security_type"] == "Bill"
    params = fake.get.call_args.kwargs.get("params") or {}
    # Filter must serialise into the comma-joined "k:op:v" form.
    assert "security_type:eq:Bill" in params["filter"]
    assert "record_date:gte:2026-01-01" in params["filter"]
    assert params["fields"] == "cusip,security_type,auction_date"
    assert params["sort"] == "-auction_date"
    assert adapter.mode() == DataMode.LIVE_OFFICIAL


@pytest.mark.asyncio
async def test_treasury_query_records_failure(monkeypatch: pytest.MonkeyPatch):
    _install_fake_client(monkeypatch, get_payload={}, get_status=503)
    adapter = TreasuryDirectAdapter()
    with pytest.raises(AdapterError):
        await adapter.query_auctions()
    assert adapter.mode() == DataMode.PROVIDER_UNAVAILABLE


# ---- OpenFIGI ---------------------------------------------------------


@pytest.mark.asyncio
async def test_openfigi_map_identifiers_offline(monkeypatch: pytest.MonkeyPatch):
    payload = [
        {
            "data": [
                {
                    "figi": "BBG000B9XRY4",
                    "name": "APPLE INC",
                    "ticker": "AAPL",
                    "exchCode": "US",
                }
            ]
        }
    ]
    fake = _install_fake_client(monkeypatch, post_payload=payload)
    adapter = OpenFigiAdapter()
    out = await adapter.map_identifiers([{"idType": "TICKER", "idValue": "AAPL"}])
    assert out[0]["data"][0]["ticker"] == "AAPL"
    assert fake.post.call_args.args[0].endswith("/v3/mapping")
    sent_jobs = fake.post.call_args.kwargs.get("json")
    assert sent_jobs == [{"idType": "TICKER", "idValue": "AAPL"}]
    # No key → no X-OPENFIGI-APIKEY header.
    headers = fake.post.call_args.kwargs.get("headers") or {}
    assert "X-OPENFIGI-APIKEY" not in headers
    assert adapter.mode() == DataMode.LIVE_OFFICIAL


@pytest.mark.asyncio
async def test_openfigi_uses_api_key_when_present(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENFIGI_API_KEY", "secret-key")
    _install_fake_client(monkeypatch, post_payload=[{"data": []}])
    adapter = OpenFigiAdapter()
    await adapter.map_identifiers([{"idType": "TICKER", "idValue": "AAPL"}])
    # Implementation-detail check: header must be present when key is set.
    from showme.providers import openfigi as of_mod

    # Re-introspect the call via the patched client.
    fake = await of_mod.get_client()
    headers = fake.post.call_args.kwargs.get("headers") or {}
    assert headers.get("X-OPENFIGI-APIKEY") == "secret-key"


@pytest.mark.asyncio
async def test_openfigi_rejects_empty_jobs():
    adapter = OpenFigiAdapter()
    with pytest.raises(AdapterError):
        await adapter.map_identifiers([])


# ---- seed_register ----------------------------------------------------


def test_seed_register_populates_registry():
    """Importing ``seed_register`` should register the four adapters."""
    from showme.providers import seed_register

    # Idempotent: calling twice does not raise / double-register.
    seed_register.register_official_adapters()
    seed_register.register_official_adapters()

    names = set(REGISTRY.names())
    assert {"sec_edgar", "fred", "treasury_direct", "openfigi"}.issubset(names)
