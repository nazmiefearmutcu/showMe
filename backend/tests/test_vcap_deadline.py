"""VCAP must return its domain fallback before the real worker cancels it."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess

# The blocked provider waits up to 5 s for release; answering within the worker
# budget plus 2 s still proves the shared deadline cut it short, while a loaded
# machine (TestClient + thread scheduling) no longer fails the bound
# (flaky under parallel load, 2026-11-08).
_LOAD_SLACK_S = 2.0
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from showme.engine.services.vcap.providers import Providers, parse_oecd
from showme.engine.services.vcap.store import SnapshotStore

CSV = """REF_AREA,MEASURE,BUSINESS_DEVELOPMENT_STAGE,UNIT_MEASURE,FREQ,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT_MULT
USA,VC_INV_MKT,_T,USD_EXC,A,2023,8,A,6
"""


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_VCAP_DIR", str(tmp_path / "vcap"))
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path / "app"))
    monkeypatch.delenv("SHOWME_DEFILLAMA_API_KEY", raising=False)


def stop_worker(worker):
    """The production worker has no shutdown API; leave no test-owned loop/thread."""
    async def cleanup():
        tasks = asyncio.all_tasks() - {asyncio.current_task()}
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await worker._loop.shutdown_asyncgens()
        await worker._loop.shutdown_default_executor()

    asyncio.run_coroutine_threadsafe(cleanup(), worker._loop).result(timeout=3)
    worker._loop.call_soon_threadsafe(worker._loop.stop)
    worker._thread.join(timeout=3)
    assert not worker._thread.is_alive()
    worker._loop.close()


@pytest.mark.parametrize("seeded", [True, False], ids=["cached", "cold"])
@pytest.mark.parametrize("succeeds", [True, False], ids=["eventual-success", "eventual-failure"])
def test_http_deadline_preserves_domain_and_cross_loop_singleflight(monkeypatch, seeded, succeeds):
    from showme import server
    from showme.engine.functions.macro.vcap import VCAPFunction
    from showme.server_routes import AppDeps, function_index

    store = SnapshotStore()
    original = store.save(parse_oecd(CSV), origin="official") if seeded else None
    # A cold OECD cache can still have another publisher's local history.
    # That history must survive the unavailable response too.
    store.save({**parse_oecd(CSV), "source_id": "other_research", "source_name": "Other saved research"})
    original_history = store.versions()
    entered, release = threading.Event(), threading.Event()
    downloads = []

    def delayed_download(self, url):
        downloads.append(threading.current_thread())
        entered.set()
        assert release.wait(timeout=5), "test did not release the provider thread"
        if not succeeds:
            raise httpx.ReadTimeout("private upstream URL must not escape")
        return CSV.replace(",8,A,6", ",9,A,6").encode(), {}

    async def dispatch(code, params):
        # Keep the real worker deadline, function, service, store, registered
        # route and sanitizer; unrelated factory discovery is outside this test.
        assert code == "VCAP"
        return await VCAPFunction().execute(**params)

    worker_budget = 0.6
    monkeypatch.setattr(server, "FUNCTION_TIMEOUT_SECONDS", worker_budget)
    monkeypatch.setattr(server, "_execute_showme_function_on_worker", dispatch)
    monkeypatch.setattr(Providers, "_download", delayed_download)
    worker = server._ShowMeFunctionWorker()
    monkeypatch.setattr(server, "_FUNCTION_WORKER", worker)
    app = FastAPI()
    function_index.register(app, AppDeps(boot_state={"engine_attached": True}))
    params = {"refresh": True, "start_year": 2023, "end_year": 2023}

    def assert_fallback(response):
        assert response.status_code == 200
        payload = response.json()
        data, meta = payload["data"], payload["metadata"]
        assert data["status"] == ("ok" if seeded else "provider_unavailable")
        assert {"sources", "snapshots", "series", "summary", "methodology"} <= data.keys()
        assert len(data["sources"]) >= 8
        assert data["snapshots"] == original_history
        assert meta["cached"] is seeded and meta["stale"] is seeded
        assert meta["source_access"]["oecd"]["refresh_in_progress"] is True
        assert "still running" in meta["source_access"]["oecd"]["reason"]
        assert "private upstream" not in json.dumps(payload)
        if seeded:
            assert data["rows"][0]["snapshot_id"] == original["snapshot_id"]
            assert data["rows"][0]["value"] == 8_000_000
            assert data["cache_note"]
        else:
            assert data["rows"] == []
            assert any(s["source_id"] == "other_research" for s in data["snapshots"])
        return payload

    try:
        with TestClient(app) as client:
            # Prime lazy shared-route imports before measuring the scaled
            # worker window; versions never initiates an upstream refresh.
            assert client.post("/api/fn/VCAP", json={"action": "versions"}).status_code == 200
            started = time.monotonic()
            first = assert_fallback(client.post("/api/fn/VCAP", json=params))
            assert time.monotonic() - started < worker_budget + _LOAD_SLACK_S
            assert entered.is_set() and not release.is_set()
            assert len(downloads) == 1 and downloads[0].is_alive()

            # New provider/store instances and a separate asyncio.run loop
            # must join the real download after the initiating HTTP wait ends.
            with ThreadPoolExecutor(max_workers=3) as pool:
                http_calls = [pool.submit(client.post, "/api/fn/VCAP", json=params) for _ in range(2)]
                foreign_loop = pool.submit(asyncio.run, Providers(SnapshotStore()).ensure("oecd", True))
                for response in http_calls:
                    assert_fallback(response.result(timeout=2))
                assert foreign_loop.result(timeout=2)["refresh_in_progress"] is True
            assert len(downloads) == 1 and downloads[0].is_alive()
            assert store.versions() == original_history

            release.set()
            downloads[0].join(timeout=2)
            assert not downloads[0].is_alive()
            completed = client.post("/api/fn/VCAP", json=params).json()
            assert len(downloads) == 1  # completed job's TTL/cooldown still applies
            assert completed["metadata"]["cached"] is (seeded or succeeds)
            assert completed["metadata"]["stale"] is (seeded and not succeeds)
            if succeeds:
                assert completed["data"]["status"] == "ok"
                assert completed["data"]["rows"][0]["value"] == 9_000_000
                assert len(store.versions()) == len(original_history) + 1
                if original:
                    assert store.selected(["oecd"], original["snapshot_id"])[0] == original
                    assert first["data"]["rows"][0]["value"] == 8_000_000
            else:
                assert completed["data"]["status"] == ("ok" if seeded else "provider_unavailable")
                assert store.versions() == original_history
                assert "ReadTimeout" in store.fetch_state("oecd")["error"]
                assert "private upstream" not in json.dumps(completed)
    finally:
        release.set()
        for thread in downloads:
            thread.join(timeout=3)
            assert not thread.is_alive()
        stop_worker(worker)


def test_inner_wait_includes_existing_source_lock_and_survives_loop_shutdown(monkeypatch):
    from showme import server
    from showme.engine.services.vcap import providers

    monkeypatch.setattr(server, "FUNCTION_TIMEOUT_SECONDS", 0.4)
    store = SnapshotStore()
    key = (str(store.path.resolve()), "oecd")
    lock = providers._LOCKS.setdefault(key, threading.Lock())
    entered = []
    downloads = []
    original_ensure = Providers._ensure

    def tracked_ensure(self, source, refresh):
        entered.append(threading.current_thread())
        return original_ensure(self, source, refresh)

    def download(self, url):
        downloads.append(url)
        return CSV.encode(), {}

    monkeypatch.setattr(Providers, "_ensure", tracked_ensure)
    monkeypatch.setattr(Providers, "_download", download)
    lock.acquire()
    try:
        for _ in range(2):
            state = asyncio.run(Providers(SnapshotStore()).ensure("oecd", True))
            assert state["refresh_in_progress"] is True
        assert len(entered) == 1 and entered[0].is_alive()
        assert downloads == []
    finally:
        lock.release()
        for thread in entered:
            thread.join(timeout=2)
            assert not thread.is_alive()
    assert len(downloads) == 1 and len(store.versions()) == 1
    assert asyncio.run(Providers(store).ensure("oecd"))["cached"] is True


@pytest.mark.parametrize("seeded", [False, True], ids=["cold", "stale"])
@pytest.mark.parametrize("succeeds", [True, False], ids=["eventual-success", "eventual-failure"])
def test_default_global_two_sources_share_actual_http_worker_deadline(monkeypatch, seeded, succeeds):
    from showme import server
    from showme.engine.functions.macro.vcap import VCAPFunction
    from showme.engine.services.vcap.nsf import NSF_URLS, parse_nsf
    from showme.server_routes import AppDeps, function_index

    fixture_dir = Path(__file__).parent / "fixtures" / "vcap"
    bodies = {"nsf_ncses_2020": (fixture_dir / "nsb20204-tabs08-062.xlsx").read_bytes(),
              "nsf_ncses": (fixture_dir / "nsb20262-figtrn-028.xlsx").read_bytes()}
    store = SnapshotStore()
    if seeded:
        for source in NSF_URLS:
            store.save(parse_nsf(bodies[source], source), origin="official")
    originals = store.versions()
    entered = {source: threading.Event() for source in NSF_URLS}
    release = threading.Event()
    downloads = []

    def delayed_download(self, url):
        source = next(sid for sid, fixed in NSF_URLS.items() if fixed == url)
        downloads.append(threading.current_thread())
        entered[source].set()
        assert release.wait(timeout=5)
        if not succeeds:
            raise httpx.ReadTimeout("private upstream failure")
        return bodies[source], {}

    async def dispatch(code, params):
        assert code == "VCAP"
        return await VCAPFunction().execute(**params)

    worker_budget = 0.6
    monkeypatch.setattr(server, "FUNCTION_TIMEOUT_SECONDS", worker_budget)
    monkeypatch.setattr(server, "_execute_showme_function_on_worker", dispatch)
    monkeypatch.setattr(Providers, "_download", delayed_download)
    worker = server._ShowMeFunctionWorker()
    monkeypatch.setattr(server, "_FUNCTION_WORKER", worker)
    app = FastAPI()
    function_index.register(app, AppDeps(boot_state={"engine_attached": True}))
    try:
        with TestClient(app) as client:
            assert client.post("/api/fn/VCAP", json={"action": "versions"}).status_code == 200
            started = time.monotonic()
            response = client.post("/api/fn/VCAP", json={"scope": "global", "refresh": True})
            assert time.monotonic() - started < worker_budget + _LOAD_SLACK_S
            assert response.status_code == 200
            payload = response.json()
            data, meta = payload["data"], payload["metadata"]
            assert data["status"] == ("ok" if seeded else "provider_unavailable")
            assert data["query"]["start_year"] == 1999
            assert set(meta["source_access"]) == set(NSF_URLS)
            assert all(event.is_set() for event in entered.values())
            assert len(downloads) == 2 and all(thread.is_alive() for thread in downloads)
            assert all(state["refresh_in_progress"] is True for state in meta["source_access"].values())
            assert meta["cached"] is seeded and meta["stale"] is seeded
            assert len(data["rows"]) == (32 if seeded else 0)
            assert len(data["coverage"]["series"]) == 2
            assert data["snapshots"] == originals and data["summary"]["total"] is None
            assert "private upstream" not in json.dumps(payload)
            release.set()
            for thread in downloads:
                thread.join(timeout=2)
                assert not thread.is_alive()
            completed = client.post("/api/fn/VCAP", json={"scope": "global"}).json()
            assert len(downloads) == 2
            assert completed["data"]["status"] == ("ok" if seeded or succeeds else "provider_unavailable")
            assert completed["metadata"]["stale"] is (seeded and not succeeds)
            assert len(store.versions()) == (2 if seeded or succeeds else 0)
            for original in originals:
                assert store.selected([original["source_id"]], original["snapshot_id"])[0]["snapshot_id"] == original["snapshot_id"]
    finally:
        release.set()
        for thread in downloads:
            thread.join(timeout=3)
            assert not thread.is_alive()
        stop_worker(worker)


@pytest.mark.parametrize("configured,expected_worker,expected_wait", [
    (None, 14.0, 10.0), ("0.8", 0.8, 0.6),
])
def test_loaded_worker_configuration_bounds_vcap_wait_and_network(configured, expected_worker, expected_wait):
    # Fresh imports exercise the actual environment configuration/default,
    # independently of other tests importing or patching the server module.
    script = """
import asyncio, json
import httpx
from showme import server
from showme.engine.services.vcap.providers import Providers, _wait_budget_seconds
from showme.engine.services.vcap.store import SnapshotStore
observed = {}
def handler(request):
    observed.update(request.extensions['timeout'])
    return httpx.Response(500)
with httpx.Client(transport=httpx.MockTransport(handler)) as client:
    asyncio.run(Providers(SnapshotStore(), client).ensure('oecd'))
print(json.dumps([server.FUNCTION_TIMEOUT_SECONDS, _wait_budget_seconds(), observed]))
"""
    env = os.environ.copy()
    if configured is None:
        env.pop("SHOWME_FUNCTION_TIMEOUT_SECONDS", None)
    else:
        env["SHOWME_FUNCTION_TIMEOUT_SECONDS"] = configured
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=120, check=True)  # hang guard only
    worker, wait, network = json.loads(result.stdout.splitlines()[-1])
    assert worker == expected_worker and wait == pytest.approx(expected_wait)
    assert wait <= 10 and wait <= worker * 0.75
    assert network["connect"] == pytest.approx(min(2, wait * 0.2))
    assert network["read"] == network["connect"]
