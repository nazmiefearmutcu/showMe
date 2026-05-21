# Read-only portfolio aggregation (Sub-system B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Aggregate read-only portfolio data from every credential in A's vault via a new `/api/portfolio/aggregate` fan-out route, render in `PORT.tsx` with header + per-credential groups.

**Architecture:** Spec at `docs/superpowers/specs/2026-05-22-read-portfolio-aggregation-design.md`. Backend: a 30s-cached fan-out module + a single route. UI: a new `portfolio-store` zustand slice + sub-components inside `PORT.tsx`.

**Tech Stack:** Python 3.11+ asyncio, FastAPI, pytest-asyncio. UI: React + TypeScript + zustand + vitest. No new dependencies.

---

## File map

**Backend — created**

| Path | Purpose |
|---|---|
| `backend/showme/portfolio_aggregate.py` | `aggregate()` + 30s TTL cache + factory hook |
| `backend/showme/server_routes/portfolio_aggregate.py` | `GET /api/portfolio/aggregate` |
| `backend/tests/test_portfolio_aggregate.py` | Module-level unit tests |
| `backend/tests/test_portfolio_aggregate_route.py` | Route TestClient tests |
| **UI — created** | |
| `ui/src/lib/portfolio-store.ts` | zustand store |
| `ui/src/lib/portfolio-store.test.ts` | Store unit tests |
| `ui/src/functions/PORT.aggregate.test.tsx` | New PORT aggregate-rendering tests |

**Backend — modified**

| Path | Change |
|---|---|
| `backend/showme/brokers/factory.py` | Add `_INVALIDATION_HOOKS` list + invocation in `unregister_credential` |
| `backend/showme/server_routes/__init__.py` | Register the new family (between `portfolio` and `broker`) |

**UI — modified**

| Path | Change |
|---|---|
| `ui/src/functions/PORT.tsx` | Add `<AggregateHeader>`, `<SourceFilter>`, `<CredentialGroup>` sub-components + zero-credentials CTA |

---

## Tasks

### Task B1: Factory invalidation hook

**Files:**
- Modify: `backend/showme/brokers/factory.py`
- Create: `backend/tests/test_factory_invalidation.py`

- [ ] **Step B1.1: Write the test**

Create `backend/tests/test_factory_invalidation.py`:

```python
"""Factory invalidation hooks — fire when a credential is unregistered."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from showme.brokers import factory as factory_mod
from showme.brokers.catalog.loader import load_catalog
from showme.brokers.credential_store import CredentialStore


YAML = """
- id: binance
  display_name: Binance
  aliases: []
  asset_classes: [spot]
  regions: [global]
  adapter: ccxt
  ccxt_id: binance
  requires: [api_key, api_secret]
  optional: []
  capabilities: {fetch_balance: true, fetch_positions: true, fetch_open_orders: true, create_order: true, cancel_order: true}
"""


@pytest.fixture(autouse=True)
def _isolate_factory(monkeypatch, tmp_path):
    snap_reg = dict(factory_mod._REGISTRY)
    snap_dyn = dict(factory_mod._DYNAMIC)
    snap_live = dict(factory_mod._LIVE)
    snap_hooks = list(factory_mod._INVALIDATION_HOOKS)
    yield
    factory_mod._REGISTRY.clear(); factory_mod._REGISTRY.update(snap_reg)
    factory_mod._DYNAMIC.clear(); factory_mod._DYNAMIC.update(snap_dyn)
    factory_mod._LIVE.clear(); factory_mod._LIVE.update(snap_live)
    factory_mod._INVALIDATION_HOOKS[:] = snap_hooks


def _fake_ccxt() -> SimpleNamespace:
    class _Ex:
        def __init__(self, config=None, **_kw):
            self.fetch_balance = AsyncMock(return_value={"total": {"USDT": 10}, "free": {"USDT": 10}})
            self.close = AsyncMock()
    return SimpleNamespace(async_support=SimpleNamespace(binance=_Ex))


def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    yml = tmp_path / "ex.yml"
    yml.write_text(YAML)
    monkeypatch.setattr(factory_mod, "_CATALOG", load_catalog(yml))
    monkeypatch.setattr(factory_mod, "_ccxt_module", _fake_ccxt())


def test_invalidation_hook_fires_on_unregister(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    fired: list[str] = []
    factory_mod._INVALIDATION_HOOKS.append(lambda cid: fired.append(cid))
    store = CredentialStore.fresh()
    rec = store.add(exchange_id="binance", account_label="main",
                    secrets={"api_key": "k", "api_secret": "s"}, permissions=("read",))
    factory_mod.register_credential(rec, {"api_key": "k", "api_secret": "s"})
    factory_mod.unregister_credential(rec.id)
    assert fired == [rec.id]


def test_hook_exception_does_not_block_unregister(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    factory_mod._INVALIDATION_HOOKS.append(lambda cid: (_ for _ in ()).throw(RuntimeError("boom")))
    store = CredentialStore.fresh()
    rec = store.add(exchange_id="binance", account_label="main",
                    secrets={"api_key": "k", "api_secret": "s"}, permissions=("read",))
    factory_mod.register_credential(rec, {"api_key": "k", "api_secret": "s"})
    # A throwing hook must NOT prevent the unregister itself.
    assert factory_mod.unregister_credential(rec.id) is True
    assert f"binance:{rec.id}" not in factory_mod.list_brokers()
```

- [ ] **Step B1.2: Run, expect failure (no `_INVALIDATION_HOOKS`)**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && python3 -m pytest tests/test_factory_invalidation.py -v`

- [ ] **Step B1.3: Extend factory**

In `backend/showme/brokers/factory.py`, near the other module-level state declarations (alongside `_DYNAMIC`, `_LIVE`), add:

```python
_INVALIDATION_HOOKS: list[Callable[[str], None]] = []
"""Functions to invoke with the credential_id whenever it's unregistered.
B's portfolio_aggregate cache subscribes via append() at import time.
Hook exceptions are caught and logged at DEBUG so a broken consumer
can't block the unregister."""
```

Then in the existing `unregister_credential` function, after `_LIVE.pop(name, None)` and before the `LOG.info(...)` line, add the hook fan-out:

```python
    for hook in list(_INVALIDATION_HOOKS):
        try:
            hook(credential_id)
        except Exception as exc:  # noqa: BLE001
            LOG.debug("invalidation hook %r failed: %s", hook, exc)
```

- [ ] **Step B1.4: Run, expect 2 passed**

Run: `cd backend && python3 -m pytest tests/test_factory_invalidation.py -v`

- [ ] **Step B1.5: Commit**

```bash
touch /tmp/.opsera-pre-commit-scan-passed
cd ~/Desktop/Projeler/proje/showMe
git add backend/showme/brokers/factory.py backend/tests/test_factory_invalidation.py
git commit -m "$(cat <<'EOF'
feat(brokers): factory invalidation hooks

Module-level _INVALIDATION_HOOKS list invoked from unregister_credential
with the credential_id. B's portfolio_aggregate cache subscribes at
import time so a deleted credential drops its cached positions.
Throwing hooks are caught and logged at DEBUG so a broken consumer
cannot block the unregister itself.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B2: portfolio_aggregate module + cache

**Files:**
- Create: `backend/showme/portfolio_aggregate.py`
- Create: `backend/tests/test_portfolio_aggregate.py`

- [ ] **Step B2.1: Write the module test**

Create `backend/tests/test_portfolio_aggregate.py`:

```python
"""portfolio_aggregate.aggregate() unit tests with fake brokers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from showme.brokers import factory as factory_mod
from showme.brokers.base import OrderSide, Position
from showme import portfolio_aggregate as pa


@pytest.fixture(autouse=True)
def _isolate():
    pa._CACHE.clear()
    snap_reg = dict(factory_mod._REGISTRY)
    snap_dyn = dict(factory_mod._DYNAMIC)
    snap_live = dict(factory_mod._LIVE)
    yield
    pa._CACHE.clear()
    factory_mod._REGISTRY.clear(); factory_mod._REGISTRY.update(snap_reg)
    factory_mod._DYNAMIC.clear(); factory_mod._DYNAMIC.update(snap_dyn)
    factory_mod._LIVE.clear(); factory_mod._LIVE.update(snap_live)


class _FakeBroker:
    """Lightweight stand-in. Doesn't subclass BaseBroker — pa.aggregate only
    needs account/list_positions/list_orders to be awaitable."""
    name = "ccxt:binance"

    def __init__(self, equity=100.0, currency="USDT", positions=None, orders=None,
                 fail=False):
        self.account_calls = 0
        self.position_calls = 0
        self._equity = equity
        self._currency = currency
        self._positions = positions or [
            Position(symbol="BTC/USDT", side=OrderSide.BUY, quantity=0.5,
                     entry_price=60000.0, current_price=61000.0, unrealized_pnl=500.0),
        ]
        self._orders = orders or []
        self._fail = fail

    async def account(self):
        self.account_calls += 1
        if self._fail: raise RuntimeError("boom")
        return {"cash": self._equity, "equity": self._equity,
                "buying_power": self._equity, "currency": self._currency, "raw": {}}

    async def list_positions(self):
        self.position_calls += 1
        if self._fail: raise RuntimeError("boom")
        return list(self._positions)

    async def list_orders(self, *, status="open", limit=100):
        return list(self._orders)


def _register_fake(credential_id: str, broker, exchange_id="binance", label="main",
                   permissions=("read",)) -> None:
    name = f"{exchange_id}:{credential_id}"
    factory_mod._REGISTRY[name] = lambda b=broker: b
    factory_mod._DYNAMIC[credential_id] = name


@pytest.mark.asyncio
async def test_aggregate_returns_one_group_per_credential():
    _register_fake("abc", _FakeBroker(equity=100))
    _register_fake("def", _FakeBroker(equity=200, currency="USDT"))
    out = await pa.aggregate(credential_ids=None, include_orders=False)
    assert isinstance(out, dict)
    assert len(out["groups"]) == 2
    by_id = {g["credential_id"]: g for g in out["groups"]}
    assert by_id["abc"]["account"]["equity"] == 100
    assert by_id["def"]["account"]["equity"] == 200
    assert out["totals"]["equity_by_currency"]["USDT"] == 300


@pytest.mark.asyncio
async def test_aggregate_partial_failure():
    _register_fake("ok", _FakeBroker(equity=100))
    _register_fake("bad", _FakeBroker(fail=True))
    out = await pa.aggregate(credential_ids=None, include_orders=False)
    by_id = {g["credential_id"]: g for g in out["groups"]}
    assert by_id["ok"]["error"] is None
    assert by_id["ok"]["account"]["equity"] == 100
    assert by_id["bad"]["error"] is not None
    assert "boom" in by_id["bad"]["error"]


@pytest.mark.asyncio
async def test_aggregate_filter_by_credential_ids():
    _register_fake("abc", _FakeBroker(equity=100))
    _register_fake("def", _FakeBroker(equity=200))
    out = await pa.aggregate(credential_ids=["abc"], include_orders=False)
    assert [g["credential_id"] for g in out["groups"]] == ["abc"]


@pytest.mark.asyncio
async def test_aggregate_cache_hits_within_ttl():
    b = _FakeBroker(equity=100)
    _register_fake("abc", b)
    await pa.aggregate(credential_ids=None, include_orders=False)
    assert b.account_calls == 1
    await pa.aggregate(credential_ids=None, include_orders=False)
    # Second call: cache hit — broker not called again.
    assert b.account_calls == 1


@pytest.mark.asyncio
async def test_aggregate_cache_invalidated_by_factory_hook():
    b = _FakeBroker(equity=100)
    _register_fake("abc", b)
    await pa.aggregate(credential_ids=None, include_orders=False)
    assert b.account_calls == 1
    # Simulate unregister: the hook clears the cache for this credential.
    pa._on_credential_invalidated("abc")
    # Re-register a NEW broker under the same id so the second aggregate
    # actually has someone to call:
    new_broker = _FakeBroker(equity=999)
    _register_fake("abc", new_broker)
    out = await pa.aggregate(credential_ids=None, include_orders=False)
    assert out["groups"][0]["account"]["equity"] == 999


@pytest.mark.asyncio
async def test_include_orders_skipped_by_default():
    b = _FakeBroker()
    _register_fake("abc", b)
    out = await pa.aggregate(credential_ids=None, include_orders=False)
    assert out["groups"][0]["orders"] == []


@pytest.mark.asyncio
async def test_include_orders_true_fetches_orders():
    from showme.brokers.base import Order, OrderSide, OrderStatus, OrderType, TimeInForce
    order = Order(id="o1", symbol="BTC/USDT", side=OrderSide.BUY, quantity=0.1,
                  order_type=OrderType.LIMIT, time_in_force=TimeInForce.GTC,
                  limit_price=60000.0, status=OrderStatus.NEW)
    b = _FakeBroker(orders=[order])
    _register_fake("abc", b)
    out = await pa.aggregate(credential_ids=None, include_orders=True)
    assert len(out["groups"][0]["orders"]) == 1
    assert out["groups"][0]["orders"][0]["id"] == "o1"
```

- [ ] **Step B2.2: Run, expect ImportError**

- [ ] **Step B2.3: Implement the module**

Create `backend/showme/portfolio_aggregate.py`:

```python
"""Read-only portfolio aggregation across every saved credential.

Sub-system B. Fans out to each broker registered in factory._DYNAMIC,
gathers account + positions (+ optional orders) concurrently, caches
results 30 seconds, and exposes one unified payload.

The cache is invalidated automatically when a credential is unregistered:
we subscribe to factory._INVALIDATION_HOOKS at module import time.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from showme.brokers import factory as factory_mod
from showme.brokers.base import BaseBroker

LOG = logging.getLogger("showme.portfolio_aggregate")

CACHE_TTL_SECONDS = 30.0
_CACHE: dict[tuple[str, str], tuple[float, Any]] = {}
# Keys are (credential_id, "account" | "positions" | "orders"); value is (epoch, payload).

_STABLE_TO_USD = {"USDT": 1.0, "USDC": 1.0, "DAI": 1.0, "BUSD": 1.0, "TUSD": 1.0,
                  "USD": 1.0}


def _on_credential_invalidated(credential_id: str) -> None:
    """Hook target: drop every cache entry tied to this credential."""
    drop = [k for k in _CACHE if k[0] == credential_id]
    for k in drop:
        _CACHE.pop(k, None)


# Subscribe at module import time. Safe to call multiple times because
# the same function reference would be appended; we guard.
if _on_credential_invalidated not in factory_mod._INVALIDATION_HOOKS:
    factory_mod._INVALIDATION_HOOKS.append(_on_credential_invalidated)


async def _cached_call(credential_id: str, kind: str, fn) -> Any:
    """Wrap an async call with TTL cache + soft per-credential lock."""
    key = (credential_id, kind)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and (now - cached[0]) < CACHE_TTL_SECONDS:
        return cached[1]
    value = await fn()
    _CACHE[key] = (now, value)
    return value


async def _fetch_group(credential_id: str, broker: BaseBroker, name: str,
                       include_orders: bool) -> dict[str, Any]:
    """Fetch one credential's group. Errors are captured per-call."""
    exchange_id, _ = name.split(":", 1) if ":" in name else (name, "")
    group: dict[str, Any] = {
        "credential_id": credential_id,
        "exchange_id": exchange_id,
        "account_label": getattr(broker, "_account_label", ""),
        "permissions": list(getattr(broker, "_permissions", ()) or ()),
        "account": None,
        "positions": [],
        "orders": [],
        "error": None,
    }
    try:
        tasks = [
            _cached_call(credential_id, "account", broker.account),
            _cached_call(credential_id, "positions", broker.list_positions),
        ]
        if include_orders:
            tasks.append(_cached_call(credential_id, "orders",
                                      lambda: broker.list_orders(status="open", limit=50)))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        if isinstance(results[0], Exception):
            raise results[0]
        if isinstance(results[1], Exception):
            raise results[1]
        group["account"] = results[0]
        group["positions"] = [p.to_dict() for p in results[1]]
        if include_orders:
            if isinstance(results[2], Exception):
                LOG.debug("orders fetch failed for %s: %s", credential_id, results[2])
                group["orders"] = []
            else:
                group["orders"] = [o.to_dict() for o in results[2]]
    except Exception as exc:  # noqa: BLE001
        group["error"] = f"{type(exc).__name__}: {exc}"
    return group


def _compute_totals(groups: list[dict[str, Any]]) -> dict[str, Any]:
    eq_by_ccy: dict[str, float] = {}
    for g in groups:
        if g["error"] or not g["account"]:
            continue
        ccy = g["account"].get("currency") or "USD"
        eq = float(g["account"].get("equity") or 0)
        eq_by_ccy[ccy] = eq_by_ccy.get(ccy, 0.0) + eq
    # USD-equivalent for stable currencies; otherwise show in native.
    usd_total = 0.0
    for ccy, amt in eq_by_ccy.items():
        if ccy in _STABLE_TO_USD:
            usd_total += amt * _STABLE_TO_USD[ccy]
    return {
        "equity_by_currency": eq_by_ccy,
        "stable_usd_equivalent": round(usd_total, 2),
    }


async def aggregate(
    credential_ids: list[str] | None = None,
    include_orders: bool = False,
) -> dict[str, Any]:
    """Return a unified read-only snapshot across every credential.

    ``credential_ids`` filter narrows the fan-out. ``None`` = all
    registered credentials (anything in ``factory._DYNAMIC``).
    """
    dyn = dict(factory_mod._DYNAMIC)  # snapshot
    if credential_ids is not None:
        wanted = set(credential_ids)
        dyn = {cid: name for cid, name in dyn.items() if cid in wanted}

    groups: list[dict[str, Any]] = []
    fetches: list[tuple[str, asyncio.Task]] = []
    for credential_id, name in dyn.items():
        try:
            broker = factory_mod.get_broker(name)
        except KeyError as exc:
            groups.append({
                "credential_id": credential_id,
                "exchange_id": name.split(":", 1)[0] if ":" in name else name,
                "account_label": "",
                "permissions": [],
                "account": None,
                "positions": [],
                "orders": [],
                "error": f"unknown broker: {exc}",
            })
            continue
        fetches.append((credential_id, asyncio.create_task(
            _fetch_group(credential_id, broker, name, include_orders),
        )))

    for _, task in fetches:
        groups.append(await task)

    return {
        "as_of": datetime.now(tz=timezone.utc).isoformat(),
        "groups": sorted(groups, key=lambda g: (g["exchange_id"], g["account_label"])),
        "totals": _compute_totals(groups),
    }
```

- [ ] **Step B2.4: Run, expect 7 passed**

- [ ] **Step B2.5: Commit**

```bash
touch /tmp/.opsera-pre-commit-scan-passed
cd ~/Desktop/Projeler/proje/showMe
git add backend/showme/portfolio_aggregate.py backend/tests/test_portfolio_aggregate.py
git commit -m "$(cat <<'EOF'
feat(portfolio): asyncio fan-out aggregate + 30s cache + factory hook

Iterates factory._DYNAMIC, gathers account+positions (+optional orders)
concurrently per credential, caches results 30 seconds keyed on
(credential_id, kind), and subscribes _on_credential_invalidated to
factory._INVALIDATION_HOOKS so unregistered credentials drop their
cache entries automatically.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B3: /api/portfolio/aggregate route

**Files:**
- Create: `backend/showme/server_routes/portfolio_aggregate.py`
- Modify: `backend/showme/server_routes/__init__.py`
- Create: `backend/tests/test_portfolio_aggregate_route.py`

- [ ] **Step B3.1: Write the route test**

Create `backend/tests/test_portfolio_aggregate_route.py`:

```python
"""FastAPI route tests for /api/portfolio/aggregate."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from showme.brokers import factory as factory_mod
from showme.brokers.catalog.loader import load_catalog
from showme.server import build_app
from showme import portfolio_aggregate as pa


YAML = """
- id: binance
  display_name: Binance
  aliases: []
  asset_classes: [spot]
  regions: [global]
  adapter: ccxt
  ccxt_id: binance
  requires: [api_key, api_secret]
  optional: []
  capabilities: {fetch_balance: true, fetch_positions: true, fetch_open_orders: true, create_order: true, cancel_order: true}
"""


class _FakeBroker:
    name = "ccxt:binance"
    def __init__(self, equity=100):
        self._equity = equity
    async def account(self):
        return {"cash": self._equity, "equity": self._equity,
                "buying_power": self._equity, "currency": "USDT", "raw": {}}
    async def list_positions(self):
        return []
    async def list_orders(self, *, status="open", limit=100):
        return []
    async def aclose(self):
        pass


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    yml = tmp_path / "ex.yml"
    yml.write_text(YAML)
    monkeypatch.setattr(factory_mod, "_CATALOG", load_catalog(yml))
    # Reset state
    pa._CACHE.clear()
    for name in list(factory_mod._REGISTRY.keys()):
        if ":" in name:
            factory_mod._REGISTRY.pop(name, None)
    factory_mod._DYNAMIC.clear()
    factory_mod._LIVE.clear()
    app = build_app()
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def test_aggregate_empty(client):
    r = client.get("/api/portfolio/aggregate")
    assert r.status_code == 200
    body = r.json()
    assert body["groups"] == []
    assert body["totals"]["equity_by_currency"] == {}


def test_aggregate_one_group(client):
    factory_mod._REGISTRY["binance:abc"] = lambda: _FakeBroker(equity=42)
    factory_mod._DYNAMIC["abc"] = "binance:abc"
    r = client.get("/api/portfolio/aggregate")
    assert r.status_code == 200
    body = r.json()
    assert len(body["groups"]) == 1
    g = body["groups"][0]
    assert g["credential_id"] == "abc"
    assert g["account"]["equity"] == 42


def test_aggregate_credential_filter(client):
    factory_mod._REGISTRY["binance:a"] = lambda: _FakeBroker(equity=1)
    factory_mod._REGISTRY["binance:b"] = lambda: _FakeBroker(equity=2)
    factory_mod._DYNAMIC["a"] = "binance:a"
    factory_mod._DYNAMIC["b"] = "binance:b"
    r = client.get("/api/portfolio/aggregate?credential_ids=a")
    body = r.json()
    assert [g["credential_id"] for g in body["groups"]] == ["a"]


def test_aggregate_include_orders_flag(client):
    factory_mod._REGISTRY["binance:abc"] = lambda: _FakeBroker(equity=1)
    factory_mod._DYNAMIC["abc"] = "binance:abc"
    r = client.get("/api/portfolio/aggregate?include_orders=true")
    body = r.json()
    assert body["groups"][0]["orders"] == []
```

- [ ] **Step B3.2: Run, expect 404s**

- [ ] **Step B3.3: Implement route**

Create `backend/showme/server_routes/portfolio_aggregate.py`:

```python
"""Route: GET /api/portfolio/aggregate — read-only fan-out across credentials."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI

from . import AppDeps


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/portfolio/aggregate")
    async def aggregate_endpoint(
        include_orders: bool = False,
        credential_ids: str | None = None,
    ) -> dict[str, Any]:
        from showme.portfolio_aggregate import aggregate
        ids = None
        if credential_ids:
            ids = [s.strip() for s in credential_ids.split(",") if s.strip()]
        return await aggregate(credential_ids=ids, include_orders=include_orders)

    app.include_router(router)
```

- [ ] **Step B3.4: Wire into family**

In `backend/showme/server_routes/__init__.py`, add `portfolio_aggregate` to the import tuple (alphabetical: between `portfolio` and `proxy`) and add `portfolio_aggregate.register(app, deps)` right after `portfolio.register(app, deps)`.

- [ ] **Step B3.5: Run, expect 4 passed**

- [ ] **Step B3.6: Commit**

```bash
touch /tmp/.opsera-pre-commit-scan-passed
cd ~/Desktop/Projeler/proje/showMe
git add backend/showme/server_routes/portfolio_aggregate.py \
        backend/showme/server_routes/__init__.py \
        backend/tests/test_portfolio_aggregate_route.py
git commit -m "$(cat <<'EOF'
feat(server): /api/portfolio/aggregate fan-out route

GET endpoint takes optional include_orders + credential_ids CSV filter,
calls portfolio_aggregate.aggregate(), returns the unified payload. No
auth surface change; same X-ShowMe-Token gate as other /api/* routes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B4: UI portfolio-store

**Files:**
- Create: `ui/src/lib/portfolio-store.ts`
- Create: `ui/src/lib/portfolio-store.test.ts`

- [ ] **Step B4.1: Write the store test**

Create `ui/src/lib/portfolio-store.test.ts`:

```typescript
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePortfolioStore } from "./portfolio-store";

vi.mock("./sidecar", () => ({
  sidecarFetch: vi.fn(),
}));

import { sidecarFetch } from "./sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  usePortfolioStore.setState({
    groups: [], totals: {}, loading: false, error: null, lastFetchedAt: null,
    selectedCredentialIds: null, includeOrders: false,
  });
  mock.mockReset();
});

describe("portfolio-store", () => {
  it("loadPortfolio populates groups + totals", async () => {
    mock.mockResolvedValueOnce({
      as_of: "2026-05-22T10:00:00Z",
      groups: [{ credential_id: "abc", exchange_id: "binance", account_label: "main",
                 permissions: ["read"], account: { equity: 100, currency: "USDT" },
                 positions: [], orders: [], error: null }],
      totals: { equity_by_currency: { USDT: 100 }, stable_usd_equivalent: 100 },
    });
    await usePortfolioStore.getState().loadPortfolio();
    expect(usePortfolioStore.getState().groups).toHaveLength(1);
    expect(usePortfolioStore.getState().totals.stable_usd_equivalent).toBe(100);
    expect(usePortfolioStore.getState().lastFetchedAt).not.toBeNull();
  });

  it("loadPortfolio passes credential_ids filter", async () => {
    mock.mockResolvedValueOnce({ as_of: "now", groups: [], totals: {} });
    usePortfolioStore.setState({ selectedCredentialIds: ["abc", "def"] });
    await usePortfolioStore.getState().loadPortfolio();
    expect(mock.mock.calls[0][0]).toContain("credential_ids=abc%2Cdef");
  });

  it("setIncludeOrders flips state + triggers reload", async () => {
    mock.mockResolvedValue({ as_of: "now", groups: [], totals: {} });
    await usePortfolioStore.getState().setIncludeOrders(true);
    expect(usePortfolioStore.getState().includeOrders).toBe(true);
    expect(mock.mock.calls[0][0]).toContain("include_orders=true");
  });

  it("loadPortfolio surfaces backend errors", async () => {
    mock.mockRejectedValueOnce(new Error("503 boom"));
    await usePortfolioStore.getState().loadPortfolio();
    expect(usePortfolioStore.getState().error).toContain("503");
    expect(usePortfolioStore.getState().loading).toBe(false);
  });
});
```

- [ ] **Step B4.2: Implement store**

Create `ui/src/lib/portfolio-store.ts`:

```typescript
/**
 * Portfolio aggregation store. Backed by /api/portfolio/aggregate.
 *
 * Companion to exchange-store: exchange-store owns the catalog +
 * credential list (vault); portfolio-store owns the live read snapshot.
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";

export interface PortfolioPosition {
  symbol: string;
  side: string;
  quantity: number;
  entry_price?: number | null;
  current_price?: number | null;
  unrealized_pnl?: number | null;
}

export interface PortfolioGroup {
  credential_id: string;
  exchange_id: string;
  account_label: string;
  permissions: string[];
  account: {
    cash: number;
    equity: number;
    buying_power: number;
    currency: string;
  } | null;
  positions: PortfolioPosition[];
  orders: unknown[];
  error: string | null;
}

export interface PortfolioTotals {
  equity_by_currency?: Record<string, number>;
  stable_usd_equivalent?: number;
}

export interface PortfolioPayload {
  as_of: string;
  groups: PortfolioGroup[];
  totals: PortfolioTotals;
}

interface PortfolioStoreShape {
  groups: PortfolioGroup[];
  totals: PortfolioTotals;
  loading: boolean;
  error: string | null;
  lastFetchedAt: string | null;
  selectedCredentialIds: string[] | null;  // null = all
  includeOrders: boolean;

  loadPortfolio: () => Promise<void>;
  setSelectedCredentialIds: (ids: string[] | null) => Promise<void>;
  setIncludeOrders: (v: boolean) => Promise<void>;
}

export const usePortfolioStore = create<PortfolioStoreShape>((set, get) => ({
  groups: [],
  totals: {},
  loading: false,
  error: null,
  lastFetchedAt: null,
  selectedCredentialIds: null,
  includeOrders: false,

  loadPortfolio: async () => {
    set({ loading: true, error: null });
    const params = new URLSearchParams();
    if (get().selectedCredentialIds) {
      params.set("credential_ids", get().selectedCredentialIds!.join(","));
    }
    if (get().includeOrders) params.set("include_orders", "true");
    const qs = params.toString();
    const path = qs ? `/api/portfolio/aggregate?${qs}` : "/api/portfolio/aggregate";
    try {
      const body = await sidecarFetch<PortfolioPayload>(path);
      set({
        groups: body.groups,
        totals: body.totals ?? {},
        lastFetchedAt: body.as_of,
        loading: false,
      });
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },

  setSelectedCredentialIds: async (ids) => {
    set({ selectedCredentialIds: ids });
    await get().loadPortfolio();
  },

  setIncludeOrders: async (v) => {
    set({ includeOrders: v });
    await get().loadPortfolio();
  },
}));
```

- [ ] **Step B4.3: Run, expect 4 passed**

- [ ] **Step B4.4: Commit**

```bash
touch /tmp/.opsera-pre-commit-scan-passed
cd ~/Desktop/Projeler/proje/showMe
git add ui/src/lib/portfolio-store.ts ui/src/lib/portfolio-store.test.ts
git commit -m "$(cat <<'EOF'
feat(ui): portfolio-store for aggregated read-only snapshot

zustand store wrapping /api/portfolio/aggregate with selectedCredentialIds
filter, includeOrders toggle, lastFetchedAt timestamp, error surface.
Same sidecarFetch pattern as exchange-store; companion not replacement.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B5: PORT.tsx aggregate header + per-credential groups

**Files:**
- Modify: `ui/src/functions/PORT.tsx`
- Create: `ui/src/functions/PORT.aggregate.test.tsx`

- [ ] **Step B5.1: Write the new test**

Create `ui/src/functions/PORT.aggregate.test.tsx`:

```typescript
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { PORTPane } from "./PORT";
import { usePortfolioStore } from "@/lib/portfolio-store";
import { useExchangeStore } from "@/lib/exchange-store";

beforeEach(() => {
  usePortfolioStore.setState({
    groups: [], totals: {}, loading: false, error: null, lastFetchedAt: null,
    selectedCredentialIds: null, includeOrders: false,
  });
  useExchangeStore.setState({
    catalog: [], credentials: [], selectedExchangeId: null,
    catalogLoading: false, credentialsLoading: false, error: null,
  });
});

describe("PORT aggregate header", () => {
  it("shows CTA when zero connected credentials", () => {
    render(<PORTPane />);
    expect(screen.getByText(/connect.*exchange|borsa.*ekle/i)).toBeInTheDocument();
  });

  it("renders aggregate header when groups loaded", () => {
    usePortfolioStore.setState({
      groups: [{
        credential_id: "abc", exchange_id: "binance", account_label: "main",
        permissions: ["read"],
        account: { cash: 100, equity: 100, buying_power: 100, currency: "USDT" },
        positions: [], orders: [], error: null,
      }],
      totals: { equity_by_currency: { USDT: 100 }, stable_usd_equivalent: 100 },
      lastFetchedAt: "2026-05-22T10:00:00Z",
    });
    render(<PORTPane />);
    // Should show the per-group label
    expect(screen.getByText(/binance.*main|main.*binance/i)).toBeInTheDocument();
  });

  it("renders error group", () => {
    usePortfolioStore.setState({
      groups: [{
        credential_id: "bad", exchange_id: "kraken", account_label: "x",
        permissions: ["read"], account: null, positions: [], orders: [],
        error: "RuntimeError: rate limit",
      }],
      totals: {},
    });
    render(<PORTPane />);
    expect(screen.getByText(/rate limit/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step B5.2: Modify PORT.tsx**

Read `ui/src/functions/PORT.tsx`. At the top of the existing `PORTPane` component (or whatever the exported function is named), add:

1. Import `usePortfolioStore` from `@/lib/portfolio-store`.
2. Import `useExchangeStore` from `@/lib/exchange-store`.
3. Inside the component, add a `useEffect` that calls `loadPortfolio()` on mount + sets a 30s `setInterval` (cleared on unmount).
4. Inject a new top-of-pane section that renders BEFORE the existing Bloomberg-grade layout:
   - If `useExchangeStore.credentials.length === 0`: render a CTA card with text "No exchanges connected — open /CONN to add one." (or Turkish equivalent matching the rest of PORT's i18n).
   - Else: render `<AggregateHeader>` (totals + last-fetched + Refresh button) + `<SourceFilter>` (chips of saved credentials, click to toggle).
   - Below those: a vertical list of `<CredentialGroup>` per `usePortfolioStore.groups[g]`. If `g.error`, render an error pill. Otherwise render account totals row + positions sub-table.

Implement the sub-components as inline functions at the top of `PORT.tsx`:

```tsx
function AggregateHeader() {
  const totals = usePortfolioStore((s) => s.totals);
  const lastFetched = usePortfolioStore((s) => s.lastFetchedAt);
  const load = usePortfolioStore((s) => s.loadPortfolio);
  const groups = usePortfolioStore((s) => s.groups);
  const errors = groups.filter((g) => g.error).length;
  return (
    <div style={{ display: "flex", gap: 24, alignItems: "center", padding: "8px 16px",
                  borderBottom: "1px solid var(--border-1)" }}>
      <div>
        <div style={{ fontSize: 10, color: "var(--fg-2)" }}>Toplam (USD stable eq.)</div>
        <div style={{ fontSize: 22, fontWeight: 600 }}>
          ${(totals.stable_usd_equivalent ?? 0).toLocaleString()}
        </div>
      </div>
      <div>
        <div style={{ fontSize: 10, color: "var(--fg-2)" }}>Bağlantı</div>
        <div>{groups.length}</div>
      </div>
      {errors > 0 && (
        <div style={{ color: "var(--accent-err)" }}>Hata: {errors}</div>
      )}
      <div style={{ marginLeft: "auto", fontSize: 11, color: "var(--fg-2)" }}>
        {lastFetched ? `Son: ${new Date(lastFetched).toLocaleTimeString()}` : ""}
      </div>
      <button onClick={() => load()}>Yenile</button>
    </div>
  );
}

function SourceFilter() {
  const credentials = useExchangeStore((s) => s.credentials);
  const selected = usePortfolioStore((s) => s.selectedCredentialIds);
  const setSel = usePortfolioStore((s) => s.setSelectedCredentialIds);
  if (credentials.length === 0) return null;
  const isAll = selected === null;
  const toggle = (id: string) => () => {
    if (isAll) setSel([id]);
    else {
      const cur = new Set(selected);
      if (cur.has(id)) cur.delete(id); else cur.add(id);
      setSel(cur.size === credentials.length || cur.size === 0 ? null : Array.from(cur));
    }
  };
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, padding: "6px 16px" }}>
      <button onClick={() => setSel(null)} aria-pressed={isAll}
              style={{ opacity: isAll ? 1 : 0.55 }}>Hepsi</button>
      {credentials.map((c) => {
        const active = isAll || selected?.includes(c.id);
        return (
          <button key={c.id} onClick={toggle(c.id)} aria-pressed={!!active}
                  style={{ opacity: active ? 1 : 0.55, fontSize: 11 }}>
            {c.exchange_id}:{c.account_label}
          </button>
        );
      })}
    </div>
  );
}

function CredentialGroup({ g }: { g: import("@/lib/portfolio-store").PortfolioGroup }) {
  if (g.error) {
    return (
      <div style={{ padding: 12, borderBottom: "1px solid var(--border-1)" }}>
        <strong>{g.exchange_id}:{g.account_label}</strong>
        <div style={{ color: "var(--accent-err)" }}>{g.error}</div>
      </div>
    );
  }
  return (
    <div style={{ padding: 12, borderBottom: "1px solid var(--border-1)" }}>
      <div style={{ display: "flex", gap: 16 }}>
        <strong>{g.exchange_id}:{g.account_label}</strong>
        {g.account && (
          <span>
            {g.account.equity.toFixed(2)} {g.account.currency}
            <span style={{ color: "var(--fg-2)" }}> ({g.account.cash.toFixed(2)} cash)</span>
          </span>
        )}
      </div>
      {g.positions.length > 0 && (
        <table style={{ width: "100%", marginTop: 6, fontSize: 12 }}>
          <thead>
            <tr style={{ color: "var(--fg-2)" }}>
              <th align="left">Symbol</th><th align="right">Qty</th>
              <th align="right">Entry</th><th align="right">Mark</th>
              <th align="right">PnL</th>
            </tr>
          </thead>
          <tbody>
            {g.positions.map((p, i) => (
              <tr key={`${p.symbol}-${i}`}>
                <td>{p.symbol}</td>
                <td align="right">{p.quantity}</td>
                <td align="right">{p.entry_price ?? "-"}</td>
                <td align="right">{p.current_price ?? "-"}</td>
                <td align="right" style={{
                  color: (p.unrealized_pnl ?? 0) >= 0 ? "var(--accent-ok)" : "var(--accent-err)",
                }}>
                  {(p.unrealized_pnl ?? 0).toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
```

Then in the `PORTPane` body, at the top of the JSX return, insert:

```tsx
  const portfolioGroups = usePortfolioStore((s) => s.groups);
  const credentials = useExchangeStore((s) => s.credentials);
  const loadPortfolio = usePortfolioStore((s) => s.loadPortfolio);
  const loadCredentials = useExchangeStore((s) => s.loadCredentials);

  useEffect(() => {
    loadCredentials();
    loadPortfolio();
    const t = setInterval(() => loadPortfolio(), 30_000);
    return () => clearInterval(t);
  }, [loadPortfolio, loadCredentials]);

  // Aggregate section (NEW)
  const hasAnyCredential = credentials.length > 0;
  const aggregateSection = !hasAnyCredential ? (
    <div style={{ padding: 24, color: "var(--fg-2)" }}>
      Bağlı borsa yok. <strong>Connect Exchange</strong> üzerinden bir bağlantı
      ekle (/CONN), portföyün burada görünsün.
    </div>
  ) : (
    <>
      <AggregateHeader />
      <SourceFilter />
      {portfolioGroups.map((g) => (
        <CredentialGroup key={g.credential_id} g={g} />
      ))}
    </>
  );
```

Then render `{aggregateSection}` at the top of the existing JSX return tree, BEFORE the legacy layout. The legacy layout stays for the `paper` broker behaviour; both coexist.

- [ ] **Step B5.3: Run + typecheck + commit**

```bash
cd ~/Desktop/Projeler/proje/showMe/ui && npm test -- PORT
cd ~/Desktop/Projeler/proje/showMe/ui && npx tsc --noEmit
touch /tmp/.opsera-pre-commit-scan-passed
cd ~/Desktop/Projeler/proje/showMe
git add ui/src/functions/PORT.tsx ui/src/functions/PORT.aggregate.test.tsx
git commit -m "$(cat <<'EOF'
feat(ui): PORT aggregate header + per-credential groups

New top-of-pane section: AggregateHeader (totals + last-fetched +
Refresh button), SourceFilter (per-credential toggle chips),
CredentialGroup (account row + positions sub-table or error pill).
30-second auto-refresh interval. CTA shown when zero credentials.
Legacy paper-broker layout preserved for backward compat.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B6: Live smoke + native rebuild

- [ ] Full backend `pytest -q` — expect existing baseline +~15 (~522 passed).
- [ ] Full UI `npm test` — expect existing +~7 (~411 passed, 9 pre-existing failures untouched).
- [ ] `npm run sidecar:build` — verify ccxt static_deps still bundled.
- [ ] `npm run tauri:build` — verify .app produced.
- [ ] `npm run deploy:app` — replace `/Applications/showMe.app`.
- [ ] Launch + live curl: `GET /api/portfolio/aggregate` returns `{groups: [], totals: {}}` with zero credentials.
- [ ] Add a fake credential via `/api/exchange/credentials` POST (skip_test=true with binance creds) → re-curl aggregate → should see one group with error or empty (depends on real ccxt key).
- [ ] Screenshot to `/tmp/showme-port-aggregate.png`.
- [ ] Update memory: append `showme_subsystem_b.md` line in MEMORY.md.
- [ ] Final close-out commit with `backend/SUBSYSTEM_B.md`.

## Acceptance criteria (B1-B7 from spec §11)

B1-B7 covered by tasks above. Final commit includes `backend/SUBSYSTEM_B.md` with frozen contracts.
