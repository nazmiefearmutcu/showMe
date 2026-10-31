"""VCAP semantic fixtures; all persistence lives in a test-owned directory."""
from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from showme.engine.services.vcap.models import InputError, Query, validate_dataset
from showme.engine.services.vcap.providers import parse_oecd
from showme.engine.services.vcap.service import VCAPService
from showme.engine.services.vcap.store import SnapshotStore


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_VCAP_DIR", str(tmp_path))
    monkeypatch.delenv("SHOWME_DEFILLAMA_API_KEY", raising=False)
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path / "app"))


def dataset(source="custom_test", published="2025-06-01", value=100, **changes):
    result = {
        "schema_version": 1, "source_id": source, "source_name": "Test publication",
        "source_url": "https://example.org/research", "published_at": published,
        "methodology": "Company investment reported by the publisher.",
        "methodology_version": "v1", "geography_basis": "company_hq",
        "date_basis": "announced", "sector": "all", "observations": [{
            "scope": "countries", "geography": "USA", "period": "2024",
            "metric": "investment", "stage": "total", "unit": "USD",
            "value": value, "status": "reported",
        }],
    }
    result.update(changes)
    return result


def test_atomic_idempotent_revision_and_vintage():
    store = SnapshotStore()
    first = store.save(validate_dataset(dataset()))
    assert store.save(validate_dataset(dataset()))["snapshot_id"] == first["snapshot_id"]
    latest = store.save(validate_dataset(dataset(published="2025-07-01", value=150)))
    store.save(validate_dataset(dataset(published="2025-01-01", value=80)))
    assert len(store.versions()) == 3
    assert store.selected(["custom_test"])[0]["snapshot_id"] == latest["snapshot_id"]
    assert store.selected(["custom_test"], first["snapshot_id"])[0]["dataset"]["observations"][0]["value"] == 100
    bad = dataset(published="2026-01-01")
    bad["observations"].append({**bad["observations"][0], "value": -1})
    with pytest.raises(InputError):
        store.save(validate_dataset(bad))
    assert len(store.versions()) == 3


@pytest.mark.parametrize("value", [-1, True, float("nan"), float("inf"), "10"])
def test_reject_invalid_amounts(value):
    with pytest.raises(InputError):
        validate_dataset(dataset(value=value))


@pytest.mark.parametrize("change", [
    {"period": "2024-Q5"}, {"period": "2024-02-31"}, {"status": "missing", "value": 1},
    {"unit": "PERCENT_GDP", "value": 101}, {"metric": "deals", "unit": "COUNT", "value": 1.5},
    {"metric": "deals", "unit": "USD"}, {"metric": "investment", "unit": "COUNT"},
    {"scope": "global", "geography": "USA"}, {"scope": "turkey", "geography": "DEU"},
])
def test_observation_semantics(change):
    data = dataset()
    data["observations"][0].update(change)
    with pytest.raises(InputError):
        validate_dataset(data)


def test_null_zero_and_duplicates():
    missing = dataset(value=None)
    missing["observations"][0]["status"] = "missing"
    assert validate_dataset(missing)["observations"][0]["value"] is None
    assert validate_dataset(dataset(value=0))["observations"][0]["value"] == 0
    duplicate = dataset()
    duplicate["observations"].append(copy.deepcopy(duplicate["observations"][0]))
    with pytest.raises(InputError, match="duplicate"):
        validate_dataset(duplicate)


@pytest.mark.parametrize("changes", [
    {"start_year": True}, {"end_year": "bad"}, {"refresh": "yes"}, {"source_ids": [1]},
    {"metric": "deals", "unit": "USD"}, {"start_year": 2025, "end_year": 2024},
    {"scope": "countries", "geographies": ["WORLD"]}, {"frequency": "monthly"},
])
def test_invalid_queries(changes):
    with pytest.raises(InputError):
        Query.parse(changes)


@pytest.mark.parametrize("change", [
    {"published_at": "2025-02-30"}, {"schema_version": True},
    {"source_url": "https://user:secret@example.org/"}, {"source_url": "file:///tmp/a"},
    {"methodology": ""}, {"source_id": "../bad"}, {"observations": "bad"},
])
def test_invalid_dataset_metadata(change):
    with pytest.raises(InputError):
        validate_dataset(dataset(**change))


def test_import_limits():
    with pytest.raises(InputError, match="2 MB"):
        validate_dataset(dataset(methodology="a" * 2_000_001))
    with pytest.raises(InputError, match="10,000"):
        validate_dataset(dataset(observations=[{}] * 10001))


OECD_CSV = """REF_AREA,MEASURE,BUSINESS_DEVELOPMENT_STAGE,UNIT_MEASURE,FREQ,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT_MULT
USA,VC_INV_MKT,_T,USD_EXC,A,2023,131680.3188381091,A,6
USA,VC_INV_MKT,SEED,USD_EXC,A,2023,0,A,6
USA,VC_INV_MKT,START,PT_B1GQ,A,2023,0.25,P,0
FRA,VC_INV_MKT,LATER,USD_EXC,A,2023,,M,6
"""


def test_oecd_scaling_flags_missing_and_real_coverage():
    data = parse_oecd(OECD_CSV, "2026-01-01T00:00:00+00:00", "2025-12-30")
    rows = data["observations"]
    total = next(r for r in rows if r["stage"] == "total")
    assert total["value"] == pytest.approx(131680318838.1091)
    assert total["unit_mult"] == 6 and total["observation_flag"] == "A"
    assert next(r for r in rows if r["stage"] == "seed")["value"] == 0
    assert next(r for r in rows if r["stage"] == "early")["value"] == .25
    assert next(r for r in rows if r["geography"] == "FRA")["value"] is None
    assert {r["geography"] for r in rows} == {"USA", "FRA"}
    assert "TUR" not in {r["geography"] for r in rows}


def test_multisource_vintage_and_comparability():
    service = VCAPService()
    first = service.store.save(validate_dataset(dataset()))
    service.store.save(validate_dataset(dataset(published="2025-07-01", value=150)))
    service.store.save(validate_dataset(dataset(source="another", value=110)))
    data, meta = asyncio.run(service.query(Query.parse({
        "source_ids": ["another", "custom_test"], "vintage": first["snapshot_id"],
    })))
    assert [r["source_id"] for r in data["rows"]] == ["another", "custom_test"]
    assert [r["value"] for r in data["rows"]] == [110, 100]
    assert data["comparison"]["blocked_pairs"]
    assert data["comparison"]["comparable_pairs"] == []
    assert meta["data_mode"] == "imported"
    assert data["available_geographies"] == ["USA"]
    assert len(data["sources"]) >= 9


def test_no_annual_quarter_splicing_or_country_sum():
    service = VCAPService()
    data = dataset()
    data["observations"].extend([
        {**data["observations"][0], "period": "2024-Q1", "value": 25},
        {**data["observations"][0], "geography": "FRA", "value": 50},
    ])
    service.store.save(validate_dataset(data))
    result, _ = asyncio.run(service.query(Query.parse({"source_ids": ["custom_test"]})))
    assert len(result["rows"]) == 1
    world, _ = asyncio.run(service.query(Query.parse({
        "source_ids": ["custom_test"], "scope": "global", "geographies": ["WORLD"],
    })))
    assert world["rows"] == []
    assert world["summary"]["total"] is None


def test_no_key_has_catalogue_and_empty_snapshots():
    service = VCAPService()
    data, meta = asyncio.run(service.query(Query.parse({"scope": "crypto", "source_ids": ["defillama"]})))
    assert data["rows"] == [] and data["snapshots"] == []
    assert meta["data_mode"] == "unavailable"
    source = next(s for s in data["sources"] if s["source_id"] == "defillama")
    assert source["access_status"] == "not_configured"
    assert "key" in source["access_notes"].lower()
    assert "pro-api.llama.fi/" not in json.dumps(data)


def test_defillama_units_undisclosed_and_no_false_vc():
    from showme.engine.services.vcap.providers import parse_defillama
    parsed = parse_defillama({"raises": [
        {"name": "A", "date": 1704067200, "amount": 8, "round": "Series A"},
        {"name": "B", "date": 1704067200, "amount": None, "round": "ICO"},
    ]})
    annual = [r for r in parsed["observations"] if r["frequency"] == "annual"]
    assert next(r for r in annual if r["metric"] == "investment")["value"] == 8_000_000
    assert next(r for r in annual if r["metric"] == "deals")["value"] == 2
    assert all(r["financing_scope"] == "all_raises" for r in annual)
    assert all(r["geography"] == "WORLD" for r in annual)
    service = VCAPService()
    service.store.save(parsed, origin="reference")
    strict, _ = asyncio.run(service.query(Query.parse({"scope": "crypto", "source_ids": ["defillama"]})))
    assert strict["rows"] == []
    missing = parse_defillama({"raises": [{"name": "C", "date": 1704067200, "amount": None}]})
    assert next(r for r in missing["observations"] if r["metric"] == "investment")["value"] is None


def test_provider_singleflight_cache_refresh_and_expiry():
    from showme.engine.services.vcap.providers import Providers
    store = SnapshotStore()
    calls = []
    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, text=OECD_CSV)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = Providers(store, client)
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: asyncio.run(provider.ensure("oecd")), range(6)))
        assert len(calls) == 1
        assert sum(not result["cached"] for result in results) == 1
        refresh = asyncio.run(provider.ensure("oecd", refresh=True))
        assert refresh["refresh_cooldown"] is True and len(calls) == 1
        old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        with store._connect() as conn:
            conn.execute("UPDATE fetch_state SET last_attempt=?, last_success=?", (old, old))
        asyncio.run(provider.ensure("oecd"))
        assert len(calls) == 2
        assert len(store.versions()) == 1  # identical release is immutable/idempotent


def test_provider_stale_on_failure_preserves_release():
    from showme.engine.services.vcap.providers import Providers
    store = SnapshotStore()
    release = store.save(parse_oecd(OECD_CSV), origin="official")
    def error(request):
        raise httpx.ConnectError("failure https://bad.example/secret")
    with httpx.Client(transport=httpx.MockTransport(error)) as client:
        provider = Providers(store, client)
        state = asyncio.run(provider.ensure("oecd", refresh=True))
        assert state["stale"] is True and state["cached"] is True
        assert "secret" not in json.dumps(state)
        service = VCAPService(store, provider)
        data, meta = asyncio.run(service.query(Query.parse({"start_year": 2023, "end_year": 2023})))
        assert data["rows"][0]["snapshot_id"] == release["snapshot_id"]
        assert meta["stale"] is True and data["cache_note"]
        assert data["rows"][0]["published_at"] is None


@pytest.mark.parametrize("kind", ["timeout", "http", "oversized", "schema"])
def test_provider_sanitizes_keyed_failure(monkeypatch, kind):
    from showme.engine.services.vcap.providers import MAX_RESPONSE_BYTES, Providers
    monkeypatch.setenv("SHOWME_DEFILLAMA_API_KEY", "private-api-secret")
    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout(str(request.url))
        if kind == "http":
            return httpx.Response(403, text=str(request.url))
        if kind == "oversized":
            return httpx.Response(200, headers={"content-length": str(MAX_RESPONSE_BYTES + 1)})
        return httpx.Response(200, json={"invalid": str(request.url)})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        service = VCAPService()
        service.providers = Providers(service.store, client)
        data, meta = asyncio.run(service.query(Query.parse({"scope": "crypto", "financing_scope": "all_raises"})))
        output = json.dumps([data, meta, service.store.fetch_state("defillama")])
        assert "private-api-secret" not in output and "pro-api.llama.fi/" not in output
        assert data["status"] == "provider_unavailable" and data["rows"] == []
        assert meta["data_mode"] == "unavailable"


def test_httpx_request_log_does_not_expose_key(monkeypatch, caplog):
    from showme.engine.services.vcap.providers import Providers
    monkeypatch.setenv("SHOWME_DEFILLAMA_API_KEY", "private-api-secret")
    with caplog.at_level("INFO", logger="httpx"):
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"raises": []}))) as client:
            asyncio.run(Providers(SnapshotStore(), client).ensure("defillama"))
    assert "private-api-secret" not in caplog.text and "pro-api.llama.fi/" not in caplog.text
    assert "DefiLlama Pro endpoint" in caplog.text


def test_partial_provider_failure_does_not_discard_import():
    from showme.engine.services.vcap.providers import Providers
    service = VCAPService()
    service.store.save(validate_dataset(dataset(source="crunchbase")))
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as client:
        service.providers = Providers(service.store, client)
        data, _ = asyncio.run(service.query(Query.parse({"source_ids": ["oecd", "crunchbase"]})))
        assert data["status"] == "ok"
        assert len(data["rows"]) == 1 and data["rows"][0]["source_id"] == "crunchbase"
        assert data["warnings"]


def test_bad_query_never_fetches(monkeypatch):
    from showme.engine.functions.macro.vcap import VCAPFunction
    from showme.engine.services.vcap.providers import Providers
    def never(*args):
        raise AssertionError("invalid input caused a fetch")
    monkeypatch.setattr(Providers, "_download", never)
    for params in ({"metric": "deals"}, {"vintage": "a" * 64}, {"source_ids": ["unknown"]}, {"path": "C:/private.json"}):
        result = asyncio.run(VCAPFunction().execute(**params))
        assert result.data["status"] == "input_error"


def test_oecd_invalid_schema_and_bad_multiplier_fail_closed():
    from showme.engine.services.vcap.providers import ProviderError
    for body in ("wrong,columns\n1,2", OECD_CSV.replace(",6\n", ",999\n"), OECD_CSV.replace("131680.3188381091", "NaN")):
        with pytest.raises(ProviderError):
            parse_oecd(body)


def test_shared_envelope_retains_rows_and_reference_label():
    from showme import server
    from showme.engine.functions.macro.vcap import VCAPFunction
    from showme.function_contracts import normalize_function_contract, validate_envelope
    from showme.manifest.seeds.vcap_seed import vcap
    fn = VCAPFunction()
    asyncio.run(fn.execute(action="import", dataset=dataset()))
    result = asyncio.run(fn.execute(source_ids=["custom_test"]))
    normalized = normalize_function_contract("VCAP", {}, result.to_dict())
    assert validate_envelope(normalized).status == "ok"
    assert normalized["rows"][0]["value"] == 100
    sanitized = server.sanitize_function_payload("VCAP", {}, result.to_dict())
    assert sanitized["status"] == "ok" and sanitized["data"]["rows"][0]["value"] == 100
    assert sanitized["rows"][0]["value"] == 100
    assert sanitized["metadata"]["data_mode"] == "imported"
    assert sanitized["data_state"] == "reference"
    assert all(sanitized["data"].get(key) for key in vcap.output_contract.must_have)
    empty = asyncio.run(fn.execute(scope="global", source_ids=["kpmg_pitchbook"]))
    assert server.sanitize_function_payload("VCAP", {}, empty.to_dict())["status"] == "empty"


def test_post_import_versions_query_and_get_mutation_guard(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from showme import server
    from showme.engine.functions.macro.vcap import VCAPFunction
    from showme.server_routes import AppDeps, function_index
    async def execute(code, params):
        assert code == "VCAP"
        return await VCAPFunction().execute(**params)
    monkeypatch.setattr(server, "_execute_showme_function", execute)
    monkeypatch.setattr(server, "_route_function_params", lambda code, params: params)
    app = FastAPI()
    function_index.register(app, AppDeps(boot_state={"engine_attached": True}))
    client = TestClient(app)
    imported = client.post("/api/fn/VCAP", json={"action": "import", "dataset": dataset()})
    assert imported.status_code == 200 and imported.json()["status"] == "ok"
    sid = imported.json()["data"]["snapshot_id"]
    assert client.post("/api/fn/VCAP", json={"action": "versions"}).json()["data"]["snapshots"][0]["snapshot_id"] == sid
    query = client.post("/api/fn/VCAP", json={"source_ids": ["custom_test"], "vintage": sid})
    assert query.status_code == 200 and query.json()["rows"][0]["value"] == 100
    assert client.get("/api/fn/VCAP?action=import").status_code == 405
    assert len(SnapshotStore().versions()) == 1


def test_vcap_body_allowance_is_narrow_and_chunked_stays_rejected(monkeypatch):
    from fastapi.testclient import TestClient
    from showme import server
    monkeypatch.delenv("SHOWME_AUTH_TOKEN", raising=False)
    app = server.build_app(engine_root=None)
    # No lifespan/model boot needed: middleware runs before the engine503.
    client = TestClient(app)
    large = b" " * 300_000
    assert client.post("/api/fn/VCAP", content=large).status_code == 503
    assert client.post("/api/fn/ECFC", content=large).status_code == 413
    assert client.post("/api/fn/VCAP", content=b" " * 2_100_001).status_code == 413
    assert client.post("/api/fn/VCAP", content=iter([b"{}"])) .status_code == 411
