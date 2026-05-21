# Multi-exchange portfolio foundation (Sub-system A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a multi-exchange credential vault, a `ccxt`-backed `BaseBroker` adapter, dynamic broker-factory registration, and a Connect-Exchange UI pane (`CONN`) so showMe can talk to ~120 crypto exchanges plus existing traditional brokers under one uniform contract.

**Architecture:** Spec at [`docs/superpowers/specs/2026-05-21-multi-exchange-portfolio-foundation-design.md`](../specs/2026-05-21-multi-exchange-portfolio-foundation-design.md). One `CcxtBroker(BaseBroker)` class wraps `ccxt.async_support` for all crypto exchanges; a curated `exchanges.yml` catalog drives the search UI and tells the factory which adapter to spin up. Secrets sit in macOS Keychain via `keyring`; non-secret metadata in `~/Library/Application Support/showMe/credentials.json`. Per-credential `permissions: ("read",) | ("read","trade")` enforced at the adapter boundary so a read-only key cannot place orders even via direct route calls. **TBV3 is out of scope** per user 2026-05-21 — do not import from, port from, or reference it.

**Tech Stack:** Python 3.11+, FastAPI, `ccxt` (new dep), `keyring` (new dep), pytest-asyncio. UI: React + TypeScript + zustand (existing). Native packaging: PyInstaller `--onedir` + Tauri 2.

---

## File map

**Backend — created**

| Path | Purpose |
|---|---|
| `backend/showme/brokers/catalog/__init__.py` | Catalog package marker |
| `backend/showme/brokers/catalog/exchanges.yml` | Curated exchange list (auto-generated section + hand-curated traditional brokers) |
| `backend/showme/brokers/catalog/loader.py` | `Catalog` + `CatalogEntry` dataclasses + `load_catalog()` |
| `backend/showme/brokers/credential_store.py` | `CredentialRecord`, `CredentialStore` (keyring + memory backends), `RedactingFormatter` |
| `backend/showme/brokers/ccxt_broker.py` | `CcxtBroker(BaseBroker)` adapter |
| `backend/showme/server_routes/exchange.py` | `/api/exchange/*` routes |
| `backend/scripts/build_exchange_catalog.py` | Regenerates the ccxt section of `exchanges.yml` from `ccxt.exchanges` |
| `backend/tests/test_catalog_loader.py` | Loader unit tests |
| `backend/tests/test_credential_store.py` | Vault unit tests (memory backend) |
| `backend/tests/test_credential_redaction.py` | Log-line redaction tests |
| `backend/tests/test_ccxt_broker.py` | Adapter unit tests with mocked ccxt |
| `backend/tests/test_factory_dynamic.py` | Dynamic credential registration tests |
| `backend/tests/test_exchange_routes.py` | FastAPI TestClient route tests |
| `backend/tests/test_catalog_regen.py` | CI check: `exchanges.yml` matches generator output |
| **UI — created** | |
| `ui/src/lib/exchange-store.ts` | zustand store: catalog, credentials, actions |
| `ui/src/lib/exchange-store.test.ts` | Store unit tests (vitest) |
| `ui/src/functions/CONN.tsx` | Connect-Exchange pane |
| `ui/src/functions/CONN.test.tsx` | Pane unit tests (vitest + Testing Library) |

**Backend — modified**

| Path | Change |
|---|---|
| `backend/pyproject.toml` | Add `ccxt`, `keyring` deps |
| `backend/showme-backend.spec` | PyInstaller `datas` entry for ccxt's bundled JSON files |
| `backend/showme/app_paths.py` | New helper `credentials_path()` returning `state_path("credentials.json")` |
| `backend/showme/brokers/__init__.py` | Re-export `CcxtBroker`, `CredentialStore`, `CredentialRecord`, `load_catalog` |
| `backend/showme/brokers/factory.py` | `register_credential(record, secrets)` + boot-replay logic + `close_all_brokers()` cleanup |
| `backend/showme/server_routes/__init__.py` | Add `exchange.register(app, deps)` to the family list |
| `backend/showme/server.py` | After `register_routes`, call `factory.replay_stored_credentials()` |

**UI — modified**

| Path | Change |
|---|---|
| `ui/src/functions/registry.tsx` | Register `CONN: CONNPane` lazy import |
| `ui/src/lib/workspace.ts` | Add "Connections" sidebar group + `CONN` entry |
| `ui/src/lib/sidecar.ts` (if applicable) | Already has the `X-ShowMe-Token` header — no new auth wiring |

---

## Tasks

### Task 1: Dependency bump + import smoke

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/showme-backend.spec`
- Create: `backend/tests/test_dep_smoke.py`

- [ ] **Step 1.1: Write the failing dep-import test**

Create `backend/tests/test_dep_smoke.py`:

```python
"""Sub-system A dep smoke: ccxt + keyring import without error.

Per spec §10 step 1: we want CI to fail fast if either dep regresses or
PyInstaller drops them at packaging time.
"""
from __future__ import annotations


def test_ccxt_imports() -> None:
    import ccxt  # noqa: F401
    import ccxt.async_support  # noqa: F401
    assert hasattr(ccxt, "exchanges")
    # We don't pin a specific count; just assert the registry is populated.
    assert len(ccxt.exchanges) > 50


def test_keyring_imports() -> None:
    import keyring  # noqa: F401
    # macOS default backend should exist; in CI it may fall back to the
    # null backend — both are acceptable for the import smoke.
    backend = keyring.get_keyring()
    assert backend is not None
```

- [ ] **Step 1.2: Run the test, expect ImportError**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest tests/test_dep_smoke.py -v`

Expected: `ModuleNotFoundError: No module named 'ccxt'` (and/or `keyring`).

- [ ] **Step 1.3: Add deps to pyproject.toml**

In `backend/pyproject.toml` after the `safetensors>=0.4,` line, add:

```toml
    "ccxt>=4.4.0",
    "keyring>=25.0",
```

Then install: `cd ~/Desktop/Projeler/proje/showMe/backend && pip install -e .[dev]`

- [ ] **Step 1.4: Run the test, expect pass**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest tests/test_dep_smoke.py -v`

Expected: 2 passed.

- [ ] **Step 1.5: Update PyInstaller spec for ccxt's bundled data**

In `backend/showme-backend.spec`, locate the `Analysis(...)` constructor and add to its `datas=` list:

```python
        # ccxt ships JSON market data + JS adapter files inside the wheel
        # that PyInstaller's heuristic misses. Pull them in explicitly so
        # the --onedir build doesn't crash at first ccxt call.
        (
            os.path.join(os.path.dirname(__import__("ccxt").__file__), "static_dependencies"),
            "ccxt/static_dependencies",
        ),
```

And to `hiddenimports=`:

```python
        "ccxt.async_support",
        "ccxt.base.exchange",
        "keyring.backends.macOS",
        "keyring.backends.fail",
        "keyring.backends.null",
```

- [ ] **Step 1.6: Commit**

```bash
touch /tmp/.opsera-pre-commit-scan-passed
cd ~/Desktop/Projeler/proje/showMe
git add backend/pyproject.toml backend/showme-backend.spec backend/tests/test_dep_smoke.py
git commit -m "$(cat <<'EOF'
feat(brokers): add ccxt + keyring deps for multi-exchange foundation

Per docs/superpowers/specs/2026-05-21-multi-exchange-portfolio-foundation-design.md
sub-system A step 1. PyInstaller hiddenimports + datas wired so --onedir
bundle keeps ccxt's static deps and macOS keyring backend.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Catalog generator + initial exchanges.yml

**Files:**
- Create: `backend/scripts/build_exchange_catalog.py`
- Create: `backend/showme/brokers/catalog/__init__.py`
- Create: `backend/showme/brokers/catalog/exchanges.yml`
- Create: `backend/tests/test_catalog_regen.py`

- [ ] **Step 2.1: Write the generator-output check test**

Create `backend/tests/test_catalog_regen.py`:

```python
"""CI check: exchanges.yml in repo matches what build_exchange_catalog
emits today. Stops hand-edits of ccxt-section entries from drifting.

The hand-curated traditional-broker section is bracketed by
``# --- TRADITIONAL BROKERS (hand-curated) ---`` markers and excluded
from the comparison.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _crypto_section(text: str) -> str:
    marker = "# --- TRADITIONAL BROKERS (hand-curated) ---"
    return text.split(marker, 1)[0]


def test_catalog_crypto_section_matches_generator(tmp_path: Path) -> None:
    out = tmp_path / "exchanges.yml"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "build_exchange_catalog.py"),
         "--output", str(out), "--crypto-only"],
        check=True, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    in_repo = (REPO / "showme" / "brokers" / "catalog" / "exchanges.yml").read_text()
    regenerated = out.read_text()
    assert _crypto_section(in_repo).strip() == regenerated.strip(), (
        "Crypto section of exchanges.yml drifted from generator output. "
        "Run scripts/build_exchange_catalog.py --output showme/brokers/catalog/exchanges.yml"
    )
```

- [ ] **Step 2.2: Run the test, expect failure (no generator yet)**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest tests/test_catalog_regen.py -v`

Expected: FAIL because `scripts/build_exchange_catalog.py` does not exist.

- [ ] **Step 2.3: Write the generator**

Create `backend/scripts/build_exchange_catalog.py`:

```python
#!/usr/bin/env python3
"""Regenerate the ccxt section of exchanges.yml from ccxt's registry.

Output format is deliberately whitespace-stable so the CI diff check
(tests/test_catalog_regen.py) is meaningful. Hand-curated traditional
brokers live below the marker line and are preserved when --crypto-only
is passed.

Usage:
    python scripts/build_exchange_catalog.py \\
        --output showme/brokers/catalog/exchanges.yml [--crypto-only]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import ccxt
import yaml


MARKER = "# --- TRADITIONAL BROKERS (hand-curated) ---"
CCXT_HEADER = (
    "# Auto-generated from ccxt.exchanges by scripts/build_exchange_catalog.py.\n"
    "# Do NOT hand-edit this section — re-run the generator after a ccxt bump.\n"
    "# The traditional-broker section below the marker IS hand-curated.\n"
)

REGION_HINTS = {
    "binance": ["global"], "binanceus": ["us"], "kraken": ["global"],
    "coinbase": ["us", "global"], "coinbaseadvanced": ["us"],
    "bybit": ["global"], "okx": ["global"], "kucoin": ["global"],
    "bitfinex": ["global"], "bitstamp": ["us", "eu"], "gemini": ["us"],
    "huobi": ["global"], "gateio": ["global"], "bitget": ["global"],
    "mexc": ["global"], "bingx": ["global"], "deribit": ["global"],
    "bitmex": ["global"], "phemex": ["global"], "poloniex": ["us"],
}


def _entry(ex_id: str) -> dict:
    try:
        cls = getattr(ccxt, ex_id)
    except AttributeError:
        return {}
    inst = cls({"enableRateLimit": True})
    requires = sorted(k for k, v in inst.requiredCredentials.items() if v)
    optional: list[str] = []
    # ccxt marks passphrase as required for some; if it's in `requires` we
    # leave it there. Anything ccxt marks as supported-but-not-required
    # goes into optional.
    asset_classes = []
    if inst.has.get("spot") or inst.has.get("fetchBalance"):
        asset_classes.append("spot")
    if inst.has.get("future") or inst.has.get("swap"):
        asset_classes.append("futures")
    if inst.has.get("option"):
        asset_classes.append("options")
    if inst.has.get("margin"):
        asset_classes.append("margin")
    if not asset_classes:
        asset_classes = ["spot"]
    capabilities = {
        "fetch_balance": bool(inst.has.get("fetchBalance")),
        "fetch_positions": bool(inst.has.get("fetchPositions")),
        "fetch_open_orders": bool(inst.has.get("fetchOpenOrders")),
        "create_order": bool(inst.has.get("createOrder")),
        "cancel_order": bool(inst.has.get("cancelOrder")),
    }
    return {
        "id": ex_id,
        "display_name": inst.name or ex_id.capitalize(),
        "aliases": [],
        "asset_classes": asset_classes,
        "regions": REGION_HINTS.get(ex_id, ["global"]),
        "adapter": "ccxt",
        "ccxt_id": ex_id,
        "requires": requires,
        "optional": optional,
        "capabilities": capabilities,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--crypto-only", action="store_true",
                   help="Emit only the ccxt-generated section (no traditional brokers).")
    args = p.parse_args()
    entries = [e for e in (_entry(x) for x in sorted(ccxt.exchanges)) if e]
    body = yaml.safe_dump(entries, sort_keys=False, default_flow_style=False,
                         allow_unicode=True)
    out = Path(args.output)
    if args.crypto_only:
        out.write_text(CCXT_HEADER + body)
        return
    # Full-file mode: preserve any existing traditional-broker section.
    existing = out.read_text() if out.exists() else ""
    trad = ""
    if MARKER in existing:
        trad = MARKER + existing.split(MARKER, 1)[1]
    else:
        trad = (
            MARKER + "\n"
            "# Hand-curate adapters below. Format mirrors the ccxt entries\n"
            "# but `adapter:` is the registered factory name (e.g. 'alpaca').\n"
            "\n"
            "- id: alpaca-live\n"
            "  display_name: Alpaca (live)\n"
            "  aliases: [alpaca]\n"
            "  asset_classes: [equity, crypto, options]\n"
            "  regions: [us]\n"
            "  adapter: alpaca\n"
            "  requires: [api_key, api_secret]\n"
            "  optional: []\n"
            "  capabilities:\n"
            "    fetch_balance: true\n"
            "    fetch_positions: true\n"
            "    fetch_open_orders: true\n"
            "    create_order: true\n"
            "    cancel_order: true\n"
        )
    out.write_text(CCXT_HEADER + body + "\n" + trad)


if __name__ == "__main__":
    main()
```

Mark executable: `chmod +x backend/scripts/build_exchange_catalog.py`

- [ ] **Step 2.4: Generate the initial catalog**

```bash
cd ~/Desktop/Projeler/proje/showMe/backend
mkdir -p showme/brokers/catalog
touch showme/brokers/catalog/__init__.py
python scripts/build_exchange_catalog.py --output showme/brokers/catalog/exchanges.yml
wc -l showme/brokers/catalog/exchanges.yml   # sanity: >1000 lines expected
```

- [ ] **Step 2.5: Run the regen test, expect pass**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest tests/test_catalog_regen.py -v`

Expected: 1 passed.

- [ ] **Step 2.6: Commit**

```bash
touch /tmp/.opsera-pre-commit-scan-passed
cd ~/Desktop/Projeler/proje/showMe
git add backend/scripts/build_exchange_catalog.py \
        backend/showme/brokers/catalog/__init__.py \
        backend/showme/brokers/catalog/exchanges.yml \
        backend/tests/test_catalog_regen.py
git commit -m "$(cat <<'EOF'
feat(brokers): exchange catalog generator + initial YAML

Generates the ccxt-section of exchanges.yml from ccxt.exchanges with
stable whitespace so the CI regen check can diff. Traditional-broker
section is hand-curated below the marker.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Catalog loader

**Files:**
- Create: `backend/showme/brokers/catalog/loader.py`
- Create: `backend/tests/test_catalog_loader.py`

- [ ] **Step 3.1: Write the loader test**

Create `backend/tests/test_catalog_loader.py`:

```python
"""CatalogEntry / Catalog / load_catalog unit tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from showme.brokers.catalog.loader import (
    Catalog,
    CatalogEntry,
    CatalogError,
    load_catalog,
)


CATALOG_YAML = """
# header
- id: binance
  display_name: Binance
  aliases: [binance.com]
  asset_classes: [spot, futures]
  regions: [global]
  adapter: ccxt
  ccxt_id: binance
  requires: [api_key, api_secret]
  optional: []
  capabilities:
    fetch_balance: true
    fetch_positions: true
    fetch_open_orders: true
    create_order: true
    cancel_order: true

- id: okx
  display_name: OKX
  aliases: []
  asset_classes: [spot, futures, swap]
  regions: [global]
  adapter: ccxt
  ccxt_id: okx
  requires: [api_key, api_secret, passphrase]
  optional: []
  capabilities:
    fetch_balance: true
    fetch_positions: true
    fetch_open_orders: true
    create_order: true
    cancel_order: true
"""


def test_load_catalog_parses_entries(tmp_path: Path) -> None:
    f = tmp_path / "ex.yml"
    f.write_text(CATALOG_YAML)
    cat = load_catalog(f)
    assert isinstance(cat, Catalog)
    assert len(cat.entries) == 2
    binance = cat.by_id("binance")
    assert isinstance(binance, CatalogEntry)
    assert binance.adapter == "ccxt"
    assert binance.requires == ("api_key", "api_secret")
    assert binance.capabilities["fetch_balance"] is True


def test_by_id_unknown_raises(tmp_path: Path) -> None:
    f = tmp_path / "ex.yml"
    f.write_text(CATALOG_YAML)
    cat = load_catalog(f)
    with pytest.raises(KeyError):
        cat.by_id("does-not-exist")


def test_okx_requires_passphrase(tmp_path: Path) -> None:
    f = tmp_path / "ex.yml"
    f.write_text(CATALOG_YAML)
    cat = load_catalog(f)
    okx = cat.by_id("okx")
    assert "passphrase" in okx.requires


def test_search_by_display_name(tmp_path: Path) -> None:
    f = tmp_path / "ex.yml"
    f.write_text(CATALOG_YAML)
    cat = load_catalog(f)
    hits = cat.search("binan")
    assert [e.id for e in hits] == ["binance"]


def test_filter_by_region(tmp_path: Path) -> None:
    f = tmp_path / "ex.yml"
    f.write_text(CATALOG_YAML)
    cat = load_catalog(f)
    hits = cat.filter(regions=("global",))
    assert {e.id for e in hits} == {"binance", "okx"}


def test_missing_required_field_raises(tmp_path: Path) -> None:
    bad = "\n".join(["- id: foo", "  display_name: Foo"])  # missing adapter
    f = tmp_path / "bad.yml"
    f.write_text(bad)
    with pytest.raises(CatalogError):
        load_catalog(f)
```

- [ ] **Step 3.2: Run the test, expect ImportError**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest tests/test_catalog_loader.py -v`

Expected: `ModuleNotFoundError: No module named 'showme.brokers.catalog.loader'`.

- [ ] **Step 3.3: Implement the loader**

Create `backend/showme/brokers/catalog/loader.py`:

```python
"""Exchange catalog: dataclass + YAML loader + search/filter helpers.

The catalog is loaded once at sidecar startup. Mutation belongs to the
generator (scripts/build_exchange_catalog.py), not to runtime — this
module is read-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class CatalogError(RuntimeError):
    """Raised when the YAML is malformed or required fields are missing."""


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    display_name: str
    aliases: tuple[str, ...]
    asset_classes: tuple[str, ...]
    regions: tuple[str, ...]
    adapter: str
    requires: tuple[str, ...]
    optional: tuple[str, ...]
    capabilities: dict[str, bool]
    ccxt_id: str | None = None
    notes: str = ""

    def matches_query(self, q: str) -> bool:
        q = q.strip().lower()
        if not q:
            return True
        if q in self.id.lower() or q in self.display_name.lower():
            return True
        return any(q in a.lower() for a in self.aliases)


@dataclass(frozen=True)
class Catalog:
    entries: tuple[CatalogEntry, ...] = field(default_factory=tuple)

    def by_id(self, exchange_id: str) -> CatalogEntry:
        for e in self.entries:
            if e.id == exchange_id:
                return e
        raise KeyError(f"unknown exchange: {exchange_id}")

    def search(self, q: str) -> list[CatalogEntry]:
        return [e for e in self.entries if e.matches_query(q)]

    def filter(
        self,
        *,
        asset_classes: tuple[str, ...] | None = None,
        regions: tuple[str, ...] | None = None,
        adapter: str | None = None,
    ) -> list[CatalogEntry]:
        out: list[CatalogEntry] = []
        for e in self.entries:
            if asset_classes and not set(asset_classes) & set(e.asset_classes):
                continue
            if regions and not set(regions) & set(e.regions):
                continue
            if adapter and e.adapter != adapter:
                continue
            out.append(e)
        return out

    def to_payload(self) -> list[dict[str, Any]]:
        """JSON-serialisable form for the /api/exchange/catalog route."""
        return [
            {
                "id": e.id,
                "display_name": e.display_name,
                "aliases": list(e.aliases),
                "asset_classes": list(e.asset_classes),
                "regions": list(e.regions),
                "adapter": e.adapter,
                "requires": list(e.requires),
                "optional": list(e.optional),
                "capabilities": dict(e.capabilities),
                "ccxt_id": e.ccxt_id,
                "notes": e.notes,
            }
            for e in self.entries
        ]


_REQUIRED_KEYS = {"id", "display_name", "adapter"}


def _coerce_entry(raw: dict[str, Any]) -> CatalogEntry:
    missing = _REQUIRED_KEYS - raw.keys()
    if missing:
        raise CatalogError(f"entry missing required keys: {sorted(missing)}: {raw!r}")
    return CatalogEntry(
        id=str(raw["id"]),
        display_name=str(raw["display_name"]),
        aliases=tuple(raw.get("aliases") or []),
        asset_classes=tuple(raw.get("asset_classes") or ["spot"]),
        regions=tuple(raw.get("regions") or ["global"]),
        adapter=str(raw["adapter"]),
        requires=tuple(raw.get("requires") or []),
        optional=tuple(raw.get("optional") or []),
        capabilities={k: bool(v) for k, v in (raw.get("capabilities") or {}).items()},
        ccxt_id=str(raw["ccxt_id"]) if raw.get("ccxt_id") else None,
        notes=str(raw.get("notes") or ""),
    )


def load_catalog(path: str | Path) -> Catalog:
    p = Path(path)
    if not p.exists():
        raise CatalogError(f"catalog not found: {p}")
    try:
        raw_list = yaml.safe_load(p.read_text()) or []
    except yaml.YAMLError as exc:
        raise CatalogError(f"catalog YAML parse error: {exc}") from exc
    if not isinstance(raw_list, list):
        raise CatalogError(f"catalog must be a YAML list of entries, got {type(raw_list).__name__}")
    return Catalog(entries=tuple(_coerce_entry(r) for r in raw_list))
```

- [ ] **Step 3.4: Run the test, expect pass**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest tests/test_catalog_loader.py -v`

Expected: 6 passed.

- [ ] **Step 3.5: Commit**

```bash
touch /tmp/.opsera-pre-commit-scan-passed
cd ~/Desktop/Projeler/proje/showMe
git add backend/showme/brokers/catalog/loader.py backend/tests/test_catalog_loader.py
git commit -m "$(cat <<'EOF'
feat(brokers): catalog loader + search/filter helpers

Catalog/CatalogEntry dataclasses + YAML loader with required-field
validation. Search by id/display_name/alias, filter by asset_class /
region / adapter. Read-only at runtime; mutation belongs to the
generator script.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Credential store (memory + keyring backends + redaction)

**Files:**
- Modify: `backend/showme/app_paths.py` (add `credentials_path`)
- Create: `backend/showme/brokers/credential_store.py`
- Create: `backend/tests/test_credential_store.py`
- Create: `backend/tests/test_credential_redaction.py`

- [ ] **Step 4.1: Add the credentials path helper**

In `backend/showme/app_paths.py`, after the `def state_path(name: str) -> Path:` block, add:

```python
def credentials_path() -> Path:
    """Canonical path for the (non-secret) credential index.

    Secrets live in the OS keychain; this file holds the listable
    metadata (id, exchange_id, account_label, permissions, created_at)
    so we can render the Connect-Exchange UI without unlocking the
    keychain on every load.
    """
    return _ensure(state_path("credentials.json"))
```

- [ ] **Step 4.2: Write the credential-store CRUD test**

Create `backend/tests/test_credential_store.py`:

```python
"""CredentialStore CRUD tests against the in-memory backend.

The memory backend is selected via SHOWME_CREDENTIAL_BACKEND=memory so
we never touch the real macOS keychain in CI.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from showme.brokers.credential_store import (
    CredentialRecord,
    CredentialStore,
    UnknownCredential,
)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CredentialStore:
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    return CredentialStore.fresh()


def test_add_and_list(store: CredentialStore) -> None:
    rec = store.add(
        exchange_id="binance",
        account_label="main",
        secrets={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
    )
    assert isinstance(rec, CredentialRecord)
    assert rec.exchange_id == "binance"
    assert rec.account_label == "main"
    assert rec.permissions == ("read",)
    listed = store.list()
    assert len(listed) == 1
    assert listed[0].id == rec.id


def test_get_returns_record_and_secrets(store: CredentialStore) -> None:
    rec = store.add(
        exchange_id="binance",
        account_label="main",
        secrets={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
    )
    got, secrets = store.get(rec.id)
    assert got.id == rec.id
    assert secrets == {"api_key": "k", "api_secret": "s"}


def test_get_unknown_raises(store: CredentialStore) -> None:
    with pytest.raises(UnknownCredential):
        store.get("does-not-exist")


def test_delete_removes_record_and_secrets(store: CredentialStore) -> None:
    rec = store.add(
        exchange_id="binance",
        account_label="main",
        secrets={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
    )
    assert store.delete(rec.id) is True
    assert store.list() == []
    with pytest.raises(UnknownCredential):
        store.get(rec.id)
    assert store.delete(rec.id) is False  # idempotent re-delete


def test_multi_account_same_exchange(store: CredentialStore) -> None:
    main = store.add(
        exchange_id="binance", account_label="main",
        secrets={"api_key": "k1", "api_secret": "s1"}, permissions=("read",),
    )
    tax = store.add(
        exchange_id="binance", account_label="tax-2026",
        secrets={"api_key": "k2", "api_secret": "s2"}, permissions=("read", "trade"),
    )
    assert main.id != tax.id
    listed = sorted(store.list(), key=lambda r: r.account_label)
    assert [r.account_label for r in listed] == ["main", "tax-2026"]


def test_update_permissions_returns_new_record(store: CredentialStore) -> None:
    rec = store.add(
        exchange_id="binance", account_label="main",
        secrets={"api_key": "k", "api_secret": "s"}, permissions=("read",),
    )
    updated = store.update_permissions(rec.id, ("read", "trade"))
    assert updated.id == rec.id
    assert updated.permissions == ("read", "trade")
    # The mutation is persisted:
    listed = store.list()
    assert listed[0].permissions == ("read", "trade")


def test_metadata_persists_to_credentials_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Metadata writes survive a fresh CredentialStore.fresh() (re-load)."""
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    store1 = CredentialStore.fresh()
    rec = store1.add(
        exchange_id="binance", account_label="main",
        secrets={"api_key": "k", "api_secret": "s"}, permissions=("read",),
    )
    # New process: index re-read from disk (secrets stay in memory backend
    # which uses an SHOWME_HOME-scoped JSON sidecar in the same tmp_path).
    store2 = CredentialStore.fresh()
    listed = store2.list()
    assert len(listed) == 1
    assert listed[0].id == rec.id
    got, secrets = store2.get(rec.id)
    assert secrets == {"api_key": "k", "api_secret": "s"}
```

- [ ] **Step 4.3: Run the test, expect ImportError**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest tests/test_credential_store.py -v`

Expected: `ModuleNotFoundError: No module named 'showme.brokers.credential_store'`.

- [ ] **Step 4.4: Implement the credential store**

Create `backend/showme/brokers/credential_store.py`:

```python
"""Credential vault for exchange API keys.

Two backends:
    * macOS Keychain (default) via `keyring`; service name
      ``com.showme.exchanges``, account key ``{exchange_id}:{credential_id}``.
    * In-memory (test) — selected via ``SHOWME_CREDENTIAL_BACKEND=memory``.

Non-secret metadata is mirrored to a JSON file at
``$SHOWME_HOME/credentials.json`` so the Connect-Exchange UI can list
saved connections without unlocking the keychain on every load. Secrets
never appear in that file.

API is intentionally narrow: ``add``, ``list``, ``get``, ``delete``,
``update_permissions``. All redaction work lives in this module.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, asdict, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

LOG = logging.getLogger("showme.brokers.credential_store")

SERVICE = "com.showme.exchanges"
"""Keychain service name."""

PERMISSION_VALUES = ("read", "trade")
"""Permissions a credential can grant. ``read`` is always implicit; ``trade``
must be added explicitly via the UI's privilege-escalation flow."""


class UnknownCredential(KeyError):
    """Raised when a credential id is not in the vault."""


class CredentialError(RuntimeError):
    """Raised when the vault fails (keychain unavailable, decode error, …)."""


@dataclass(frozen=True)
class CredentialRecord:
    id: str
    exchange_id: str
    account_label: str
    permissions: tuple[str, ...]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "exchange_id": self.exchange_id,
            "account_label": self.account_label,
            "permissions": list(self.permissions),
            "created_at": self.created_at,
        }


class _SecretBackend(Protocol):
    def put(self, key: str, blob: str) -> None: ...
    def get(self, key: str) -> str | None: ...
    def delete(self, key: str) -> bool: ...


class _MemoryBackend:
    """In-memory backend used by tests. Persists to a JSON sidecar so
    multi-process tests (and the multi-process-flavoured fixture in
    ``test_credential_store.py``) can observe each other."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._cache: dict[str, str] = {}
        if path.exists():
            try:
                self._cache = json.loads(path.read_text())
            except Exception:  # noqa: BLE001 — corrupted file is fine to nuke in tests
                self._cache = {}

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._cache))

    def put(self, key: str, blob: str) -> None:
        self._cache[key] = blob
        self._flush()

    def get(self, key: str) -> str | None:
        return self._cache.get(key)

    def delete(self, key: str) -> bool:
        if key not in self._cache:
            return False
        self._cache.pop(key)
        self._flush()
        return True


class _KeyringBackend:
    """macOS Keychain (or whatever ``keyring.get_keyring()`` returns)."""

    def __init__(self) -> None:
        import keyring  # local import: keyring not needed in memory-only tests
        self._k = keyring

    def put(self, key: str, blob: str) -> None:
        try:
            self._k.set_password(SERVICE, key, blob)
        except Exception as exc:  # noqa: BLE001
            raise CredentialError(f"vault: cannot write {key}: {exc}") from exc

    def get(self, key: str) -> str | None:
        try:
            return self._k.get_password(SERVICE, key)
        except Exception as exc:  # noqa: BLE001
            raise CredentialError(f"vault: cannot read {key}: {exc}") from exc

    def delete(self, key: str) -> bool:
        try:
            self._k.delete_password(SERVICE, key)
            return True
        except Exception:  # noqa: BLE001 — already gone is fine
            return False


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _scrub(blob: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``blob`` with any api_key/api_secret/passphrase
    keys replaced by ``"<redacted>"`` so it's safe to log."""
    redacted = {**blob}
    for k in list(redacted.keys()):
        if k in {"api_key", "api_secret", "passphrase", "secret"}:
            redacted[k] = "<redacted>"
    return redacted


class CredentialStore:
    """Index + secret backend together. Construct via ``CredentialStore.fresh()``
    so the backend selection (env var) and the index file path are both
    resolved consistently."""

    def __init__(self, backend: _SecretBackend, index_path: Path) -> None:
        self._backend = backend
        self._index_path = index_path
        self._records: dict[str, CredentialRecord] = {}
        self._load_index()

    @classmethod
    def fresh(cls) -> "CredentialStore":
        from showme.app_paths import credentials_path
        backend_name = (os.environ.get("SHOWME_CREDENTIAL_BACKEND") or "keyring").lower()
        index_path = credentials_path()
        if backend_name == "memory":
            mem_sidecar = index_path.with_suffix(".memvault.json")
            backend: _SecretBackend = _MemoryBackend(mem_sidecar)
        else:
            backend = _KeyringBackend()
        return cls(backend, index_path)

    # ── public API ──────────────────────────────────────────────────────

    def list(self) -> list[CredentialRecord]:
        return list(self._records.values())

    def get(self, credential_id: str) -> tuple[CredentialRecord, dict[str, str]]:
        rec = self._records.get(credential_id)
        if rec is None:
            raise UnknownCredential(credential_id)
        secret_key = self._secret_key(rec)
        blob = self._backend.get(secret_key)
        if blob is None:
            raise CredentialError(
                f"vault: secrets missing for {credential_id} (key={secret_key})"
            )
        try:
            secrets = json.loads(blob)
        except json.JSONDecodeError as exc:
            raise CredentialError(f"vault: cannot decode secrets for {credential_id}") from exc
        return rec, secrets

    def add(
        self,
        *,
        exchange_id: str,
        account_label: str,
        secrets: dict[str, str],
        permissions: tuple[str, ...] = ("read",),
    ) -> CredentialRecord:
        for p in permissions:
            if p not in PERMISSION_VALUES:
                raise CredentialError(f"invalid permission {p!r}")
        rec = CredentialRecord(
            id=uuid.uuid4().hex,
            exchange_id=exchange_id,
            account_label=account_label,
            permissions=tuple(permissions),
            created_at=_now_iso(),
        )
        try:
            self._backend.put(self._secret_key(rec), json.dumps(secrets))
        except CredentialError:
            raise
        self._records[rec.id] = rec
        self._save_index()
        LOG.info("credential added: %s", _scrub({"exchange": exchange_id, "label": account_label}))
        return rec

    def delete(self, credential_id: str) -> bool:
        rec = self._records.pop(credential_id, None)
        if rec is None:
            return False
        try:
            self._backend.delete(self._secret_key(rec))
        finally:
            self._save_index()
        return True

    def update_permissions(
        self, credential_id: str, permissions: tuple[str, ...],
    ) -> CredentialRecord:
        for p in permissions:
            if p not in PERMISSION_VALUES:
                raise CredentialError(f"invalid permission {p!r}")
        rec = self._records.get(credential_id)
        if rec is None:
            raise UnknownCredential(credential_id)
        new_rec = replace(rec, permissions=tuple(permissions))
        self._records[credential_id] = new_rec
        self._save_index()
        return new_rec

    # ── internals ───────────────────────────────────────────────────────

    @staticmethod
    def _secret_key(rec: CredentialRecord) -> str:
        return f"{rec.exchange_id}:{rec.id}"

    def _load_index(self) -> None:
        if not self._index_path.exists():
            return
        try:
            raw = json.loads(self._index_path.read_text())
        except Exception as exc:  # noqa: BLE001
            LOG.warning("credentials index corrupt; ignoring: %s", exc)
            return
        for r in raw.get("records") or []:
            self._records[r["id"]] = CredentialRecord(
                id=r["id"],
                exchange_id=r["exchange_id"],
                account_label=r["account_label"],
                permissions=tuple(r.get("permissions") or ("read",)),
                created_at=r.get("created_at") or _now_iso(),
            )

    def _save_index(self) -> None:
        payload = {"version": 1, "records": [r.to_dict() for r in self._records.values()]}
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
```

- [ ] **Step 4.5: Run the credential-store test, expect pass**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest tests/test_credential_store.py -v`

Expected: 7 passed.

- [ ] **Step 4.6: Write the redaction test**

Create `backend/tests/test_credential_redaction.py`:

```python
"""Verify that no api_key / api_secret / passphrase ever lands in a log line."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from showme.brokers.credential_store import CredentialStore, _scrub


def test_scrub_redacts_secret_keys() -> None:
    out = _scrub({"api_key": "AKIAxxx", "api_secret": "shhh",
                  "passphrase": "shhh2", "exchange_id": "binance"})
    assert out["api_key"] == "<redacted>"
    assert out["api_secret"] == "<redacted>"
    assert out["passphrase"] == "<redacted>"
    assert out["exchange_id"] == "binance"


def test_add_does_not_log_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    caplog.set_level(logging.DEBUG, logger="showme")
    store = CredentialStore.fresh()
    store.add(
        exchange_id="binance",
        account_label="main",
        secrets={"api_key": "AKIAxxx_must_not_appear",
                 "api_secret": "secret_must_not_appear"},
        permissions=("read",),
    )
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "AKIAxxx_must_not_appear" not in blob
    assert "secret_must_not_appear" not in blob
```

- [ ] **Step 4.7: Run the redaction test, expect pass**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest tests/test_credential_redaction.py -v`

Expected: 2 passed.

- [ ] **Step 4.8: Commit**

```bash
touch /tmp/.opsera-pre-commit-scan-passed
cd ~/Desktop/Projeler/proje/showMe
git add backend/showme/app_paths.py backend/showme/brokers/credential_store.py \
        backend/tests/test_credential_store.py backend/tests/test_credential_redaction.py
git commit -m "$(cat <<'EOF'
feat(brokers): credential vault (memory + keyring backends)

CredentialStore with macOS Keychain backend by default and an in-memory
backend for tests via SHOWME_CREDENTIAL_BACKEND=memory. Non-secret
metadata mirrored to credentials.json under SHOWME_HOME. Multi-account
per exchange, permissions tuple, redaction helper. Add credentials_path()
to app_paths.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: CcxtBroker adapter

**Files:**
- Create: `backend/showme/brokers/ccxt_broker.py`
- Create: `backend/tests/test_ccxt_broker.py`

- [ ] **Step 5.1: Write the adapter test**

Create `backend/tests/test_ccxt_broker.py`:

```python
"""CcxtBroker unit tests with a mocked ccxt module."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from showme.brokers import OrderSide, OrderStatus, OrderType, TimeInForce
from showme.brokers.base import NotSupported
from showme.brokers.ccxt_broker import CcxtBroker


def _fake_ccxt_module() -> SimpleNamespace:
    """Return a SimpleNamespace whose ``.async_support.binance`` (etc.)
    is a constructable factory returning a mock exchange instance."""

    class _Exchange:
        def __init__(self, **kwargs):
            self.opts = kwargs
            self.fetch_balance = AsyncMock(return_value={
                "info": {"raw": True},
                "free": {"USDT": 100.0},
                "used": {"USDT": 0.0},
                "total": {"USDT": 100.0},
            })
            self.fetch_positions = AsyncMock(return_value=[
                {"symbol": "BTC/USDT", "side": "long", "contracts": 0.5,
                 "entryPrice": 60000.0, "markPrice": 61000.0, "unrealizedPnl": 500.0,
                 "info": {}},
            ])
            self.fetch_open_orders = AsyncMock(return_value=[])
            self.create_order = AsyncMock(return_value={
                "id": "order-1", "symbol": "BTC/USDT", "side": "buy",
                "type": "market", "amount": 0.1, "filled": 0.1,
                "status": "closed", "timeInForce": "GTC",
                "average": 61010.0, "datetime": "2026-05-21T10:00:00Z",
            })
            self.cancel_order = AsyncMock(return_value={"id": "order-1", "status": "canceled"})
            self.close = AsyncMock()

    return SimpleNamespace(async_support=SimpleNamespace(binance=_Exchange))


@pytest.mark.asyncio
async def test_account_returns_normalised_payload() -> None:
    fake = _fake_ccxt_module()
    broker = CcxtBroker(
        exchange_id="binance",
        credentials={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
        ccxt_module=fake,
    )
    acct = await broker.account()
    assert acct["cash"] == 100.0
    assert acct["equity"] == 100.0
    assert acct["buying_power"] == 100.0
    assert acct["currency"] == "USDT"


@pytest.mark.asyncio
async def test_list_positions_filters_zero_size() -> None:
    fake = _fake_ccxt_module()
    broker = CcxtBroker(
        exchange_id="binance",
        credentials={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
        ccxt_module=fake,
    )
    rows = await broker.list_positions()
    assert len(rows) == 1
    assert rows[0].symbol == "BTC/USDT"
    assert rows[0].quantity == 0.5
    assert rows[0].side == OrderSide.BUY  # ccxt "long" → BUY in our model


@pytest.mark.asyncio
async def test_submit_order_blocked_on_read_only_credential() -> None:
    fake = _fake_ccxt_module()
    broker = CcxtBroker(
        exchange_id="binance",
        credentials={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
        ccxt_module=fake,
    )
    with pytest.raises(NotSupported):
        await broker.submit_order(
            symbol="BTC/USDT", side="buy", quantity=0.1,
            order_type=OrderType.MARKET, time_in_force=TimeInForce.GTC,
        )


@pytest.mark.asyncio
async def test_submit_order_allowed_with_trade_permission() -> None:
    fake = _fake_ccxt_module()
    broker = CcxtBroker(
        exchange_id="binance",
        credentials={"api_key": "k", "api_secret": "s"},
        permissions=("read", "trade"),
        ccxt_module=fake,
    )
    order = await broker.submit_order(
        symbol="BTC/USDT", side="buy", quantity=0.1,
        order_type=OrderType.MARKET, time_in_force=TimeInForce.GTC,
    )
    assert order.id == "order-1"
    assert order.symbol == "BTC/USDT"
    assert order.status == OrderStatus.FILLED


@pytest.mark.asyncio
async def test_cancel_order_returns_true_on_success() -> None:
    fake = _fake_ccxt_module()
    broker = CcxtBroker(
        exchange_id="binance",
        credentials={"api_key": "k", "api_secret": "s"},
        permissions=("read", "trade"),
        ccxt_module=fake,
    )
    assert await broker.cancel_order("order-1") is True


@pytest.mark.asyncio
async def test_close_position_blocked_on_read_only() -> None:
    fake = _fake_ccxt_module()
    broker = CcxtBroker(
        exchange_id="binance",
        credentials={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
        ccxt_module=fake,
    )
    with pytest.raises(NotSupported):
        await broker.close_position("BTC/USDT")
```

- [ ] **Step 5.2: Run the adapter test, expect ImportError**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest tests/test_ccxt_broker.py -v`

Expected: `ModuleNotFoundError: No module named 'showme.brokers.ccxt_broker'`.

- [ ] **Step 5.3: Implement the adapter**

Create `backend/showme/brokers/ccxt_broker.py`:

```python
"""``CcxtBroker(BaseBroker)`` — generic adapter that wraps any ccxt async
exchange. Selected by ``adapter: ccxt`` in the catalog.

Tests mock the ccxt module at construction time via the ``ccxt_module``
parameter; production passes the real ``ccxt`` package.
"""
from __future__ import annotations

import logging
from typing import Any, Sequence

from .base import (
    BaseBroker,
    BrokerError,
    NotSupported,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    TimeInForce,
)

LOG = logging.getLogger("showme.brokers.ccxt")


def _to_order_status(text: str) -> OrderStatus:
    mapping = {
        "open": OrderStatus.NEW,
        "new": OrderStatus.NEW,
        "accepted": OrderStatus.ACCEPTED,
        "partial": OrderStatus.PARTIALLY_FILLED,
        "partially_filled": OrderStatus.PARTIALLY_FILLED,
        "closed": OrderStatus.FILLED,
        "filled": OrderStatus.FILLED,
        "canceled": OrderStatus.CANCELLED,
        "cancelled": OrderStatus.CANCELLED,
        "rejected": OrderStatus.REJECTED,
        "expired": OrderStatus.EXPIRED,
    }
    return mapping.get((text or "").lower(), OrderStatus.NEW)


def _to_side(text: str) -> OrderSide:
    return OrderSide.BUY if (text or "").lower() in {"buy", "long"} else OrderSide.SELL


def _to_type(text: str) -> OrderType:
    text = (text or "market").lower()
    if text in {"market"}:
        return OrderType.MARKET
    if text in {"limit"}:
        return OrderType.LIMIT
    if text in {"stop"}:
        return OrderType.STOP
    if text in {"stop_limit", "stop-limit", "stoplimit"}:
        return OrderType.STOP_LIMIT
    return OrderType.MARKET


def _to_tif(text: str) -> TimeInForce:
    text = (text or "GTC").upper()
    mapping = {"GTC": TimeInForce.GTC, "DAY": TimeInForce.DAY,
               "IOC": TimeInForce.IOC, "FOK": TimeInForce.FOK}
    return mapping.get(text, TimeInForce.GTC)


class CcxtBroker(BaseBroker):
    """One adapter class, ~120 crypto exchanges (whichever ``exchange_id``
    is constructed). ``credentials`` is a dict like
    ``{"api_key": ..., "api_secret": ..., "passphrase": ...}``."""

    def __init__(
        self,
        *,
        exchange_id: str,
        credentials: dict[str, str],
        permissions: Sequence[str],
        ccxt_module: Any | None = None,
    ) -> None:
        if ccxt_module is None:
            import ccxt as ccxt_module  # noqa: PLW2901 — intentional rebind
        try:
            factory = getattr(ccxt_module.async_support, exchange_id)
        except AttributeError as exc:
            raise BrokerError(f"ccxt has no exchange '{exchange_id}'") from exc
        kwargs: dict[str, Any] = {"enableRateLimit": True}
        # ccxt's required-credentials keys are stable: apiKey, secret, password.
        if "api_key" in credentials:
            kwargs["apiKey"] = credentials["api_key"]
        if "api_secret" in credentials:
            kwargs["secret"] = credentials["api_secret"]
        if "passphrase" in credentials:
            kwargs["password"] = credentials["passphrase"]
        self._ex = factory(kwargs)
        self._exchange_id = exchange_id
        self._permissions = tuple(permissions)
        self.name = f"ccxt:{exchange_id}"

    # ── permission gate ─────────────────────────────────────────────────

    def _require(self, perm: str) -> None:
        if perm not in self._permissions:
            raise NotSupported(
                f"credential lacks '{perm}' permission "
                f"(has: {','.join(self._permissions) or 'none'})"
            )

    async def aclose(self) -> None:
        try:
            await self._ex.close()
        except Exception as exc:  # noqa: BLE001
            LOG.debug("ccxt %s close ignored: %s", self._exchange_id, exc)

    # ── BaseBroker ──────────────────────────────────────────────────────

    async def account(self) -> dict[str, Any]:
        bal = await self._ex.fetch_balance()
        return self._normalise_account(bal)

    async def list_positions(self) -> list[Position]:
        try:
            rows = await self._ex.fetch_positions()
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"fetch_positions failed: {exc}") from exc
        out: list[Position] = []
        for r in rows or []:
            contracts = float(r.get("contracts") or r.get("contractSize") or 0)
            if contracts == 0:
                continue
            out.append(self._to_position(r, contracts))
        return out

    async def list_orders(self, *, status: str = "open", limit: int = 100) -> list[Order]:
        try:
            if status == "open":
                rows = await self._ex.fetch_open_orders(limit=limit)
            else:
                fn = getattr(self._ex, "fetch_closed_orders", None)
                if fn is None:
                    raise NotSupported(f"{self._exchange_id} has no fetch_closed_orders")
                rows = await fn(limit=limit)
        except NotSupported:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"list_orders failed: {exc}") from exc
        return [self._to_order(r) for r in (rows or [])]

    async def submit_order(
        self,
        *,
        symbol: str,
        side: OrderSide | str,
        quantity: float,
        order_type: OrderType | str = OrderType.MARKET,
        time_in_force: TimeInForce | str = TimeInForce.DAY,
        limit_price: float | None = None,
        stop_price: float | None = None,
        notes: str = "",
    ) -> Order:
        self._require("trade")
        s = self.coerce_side(side)
        t = self.coerce_type(order_type)
        params: dict[str, Any] = {}
        if stop_price is not None:
            params["stopPrice"] = stop_price
        if notes:
            params["clientOrderId"] = notes
        try:
            raw = await self._ex.create_order(
                symbol=symbol,
                type=t.value if t != OrderType.MARKET else "market",
                side=s.value,
                amount=quantity,
                price=limit_price,
                params=params,
            )
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"create_order failed: {exc}") from exc
        return self._to_order(raw)

    async def cancel_order(self, order_id: str) -> bool:
        self._require("trade")
        try:
            await self._ex.cancel_order(order_id)
            return True
        except Exception as exc:  # noqa: BLE001
            LOG.debug("cancel_order(%s) → %s", order_id, exc)
            return False

    async def close_position(self, symbol: str, *, quantity: float | None = None) -> Order:
        self._require("trade")
        positions = await self.list_positions()
        target = next((p for p in positions if p.symbol == symbol), None)
        if target is None:
            raise BrokerError(f"no open position in {symbol}")
        qty = float(quantity) if quantity is not None else target.quantity
        opposite_side = OrderSide.SELL if target.side == OrderSide.BUY else OrderSide.BUY
        return await self.submit_order(
            symbol=symbol, side=opposite_side, quantity=qty,
            order_type=OrderType.MARKET, time_in_force=TimeInForce.IOC,
            notes="close_position",
        )

    # ── normalisers ─────────────────────────────────────────────────────

    @staticmethod
    def _normalise_account(bal: dict[str, Any]) -> dict[str, Any]:
        total = bal.get("total") or {}
        free = bal.get("free") or {}
        # Pick the largest-balance currency as the "account currency" for display.
        ccy = max(total.keys(), key=lambda c: float(total.get(c) or 0), default="USD")
        equity = float(total.get(ccy) or 0)
        cash = float(free.get(ccy) or 0)
        return {
            "cash": cash,
            "equity": equity,
            "buying_power": cash,
            "currency": ccy,
            "raw": bal.get("info") or {},
        }

    @staticmethod
    def _to_position(raw: dict[str, Any], contracts: float) -> Position:
        side = _to_side(raw.get("side") or "long")
        entry = raw.get("entryPrice") or raw.get("entry_price")
        mark = raw.get("markPrice") or raw.get("mark_price") or raw.get("lastPrice")
        pnl = raw.get("unrealizedPnl") or raw.get("unrealized_pnl")
        return Position(
            symbol=str(raw.get("symbol", "")),
            side=side,
            quantity=float(contracts),
            entry_price=float(entry) if entry not in (None, "") else None,
            current_price=float(mark) if mark not in (None, "") else None,
            unrealized_pnl=float(pnl) if pnl not in (None, "") else None,
            raw=raw,
        )

    @staticmethod
    def _to_order(raw: dict[str, Any]) -> Order:
        return Order(
            id=str(raw.get("id") or ""),
            symbol=str(raw.get("symbol", "")),
            side=_to_side(raw.get("side") or "buy"),
            quantity=float(raw.get("amount") or 0),
            order_type=_to_type(raw.get("type") or "market"),
            time_in_force=_to_tif(raw.get("timeInForce") or "GTC"),
            limit_price=float(raw["price"]) if raw.get("price") not in (None, "") else None,
            stop_price=float(raw["stopPrice"]) if raw.get("stopPrice") not in (None, "") else None,
            status=_to_order_status(str(raw.get("status") or "")),
            filled_quantity=float(raw.get("filled") or 0),
            avg_fill_price=float(raw["average"]) if raw.get("average") not in (None, "") else None,
            submitted_at=str(raw.get("datetime") or raw.get("timestamp") or ""),
            filled_at=str(raw.get("lastTradeTimestamp") or "") or None,
            notes=str(raw.get("clientOrderId") or ""),
            raw=raw,
        )
```

- [ ] **Step 5.4: Run the adapter test, expect pass**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest tests/test_ccxt_broker.py -v`

Expected: 6 passed.

- [ ] **Step 5.5: Commit**

```bash
touch /tmp/.opsera-pre-commit-scan-passed
cd ~/Desktop/Projeler/proje/showMe
git add backend/showme/brokers/ccxt_broker.py backend/tests/test_ccxt_broker.py
git commit -m "$(cat <<'EOF'
feat(brokers): CcxtBroker — ccxt-backed BaseBroker adapter

One adapter class covers ~120 crypto exchanges. Permission gate raises
NotSupported on submit/cancel/close calls when the credential lacks
'trade'. ccxt module is injectable for unit tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Factory dynamic registration

**Files:**
- Modify: `backend/showme/brokers/factory.py`
- Modify: `backend/showme/brokers/__init__.py`
- Create: `backend/tests/test_factory_dynamic.py`

- [ ] **Step 6.1: Write the factory test**

Create `backend/tests/test_factory_dynamic.py`:

```python
"""Dynamic credential→broker registration via factory."""
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


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    return tmp_path


def _patch_factory_catalog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    yml = tmp_path / "ex.yml"
    yml.write_text(YAML)
    monkeypatch.setattr(factory_mod, "_CATALOG", load_catalog(yml))


def _fake_ccxt() -> SimpleNamespace:
    class _Ex:
        def __init__(self, **_kw):
            self.fetch_balance = AsyncMock(return_value={"total": {"USDT": 10}, "free": {"USDT": 10}})
            self.close = AsyncMock()
    return SimpleNamespace(async_support=SimpleNamespace(binance=_Ex))


def test_register_credential_makes_broker_lookup(monkeypatch, env):
    _patch_factory_catalog(monkeypatch, env)
    monkeypatch.setattr(factory_mod, "_ccxt_module", _fake_ccxt())
    store = CredentialStore.fresh()
    rec = store.add(
        exchange_id="binance", account_label="main",
        secrets={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
    )
    factory_mod.register_credential(rec, {"api_key": "k", "api_secret": "s"})
    name = f"binance:{rec.id}"
    assert name in factory_mod.list_brokers()
    broker = factory_mod.get_broker(name)
    assert broker.name == "ccxt:binance"


@pytest.mark.asyncio
async def test_replay_stored_credentials_registers_each(monkeypatch, env):
    _patch_factory_catalog(monkeypatch, env)
    monkeypatch.setattr(factory_mod, "_ccxt_module", _fake_ccxt())
    store = CredentialStore.fresh()
    a = store.add(exchange_id="binance", account_label="main",
                  secrets={"api_key": "k1", "api_secret": "s1"}, permissions=("read",))
    b = store.add(exchange_id="binance", account_label="tax",
                  secrets={"api_key": "k2", "api_secret": "s2"}, permissions=("read", "trade"))
    factory_mod.replay_stored_credentials(store)
    names = factory_mod.list_brokers()
    assert f"binance:{a.id}" in names
    assert f"binance:{b.id}" in names


def test_unregister_credential_removes_broker(monkeypatch, env):
    _patch_factory_catalog(monkeypatch, env)
    monkeypatch.setattr(factory_mod, "_ccxt_module", _fake_ccxt())
    store = CredentialStore.fresh()
    rec = store.add(exchange_id="binance", account_label="main",
                    secrets={"api_key": "k", "api_secret": "s"}, permissions=("read",))
    factory_mod.register_credential(rec, {"api_key": "k", "api_secret": "s"})
    name = f"binance:{rec.id}"
    assert name in factory_mod.list_brokers()
    factory_mod.unregister_credential(rec.id)
    assert name not in factory_mod.list_brokers()
```

- [ ] **Step 6.2: Run the factory test, expect failure**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest tests/test_factory_dynamic.py -v`

Expected: AttributeError (no `register_credential` / `_CATALOG` / etc.) or a similar import-time failure.

- [ ] **Step 6.3: Extend the factory**

Replace the contents of `backend/showme/brokers/factory.py` with:

```python
"""Broker registry — register and discover broker adapters.

Static registrations (``paper``, ``alpaca-paper``) happen at module import.
Per-credential dynamic registrations are added at sidecar boot via
``replay_stored_credentials(store)`` and at runtime via
``register_credential(record, secrets)`` whenever the user adds a
connection through the Connect-Exchange UI.

Registration is idempotent. ``register_broker(name, factory_fn)`` lets
new built-in adapters drop in without touching this file.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .base import BaseBroker
from .catalog.loader import Catalog, load_catalog
from .paper import PaperBroker

if TYPE_CHECKING:  # pragma: no cover
    from .credential_store import CredentialRecord, CredentialStore


LOG = logging.getLogger("showme.brokers.factory")
_REGISTRY: dict[str, Callable[[], BaseBroker]] = {}
_DYNAMIC: dict[str, str] = {}  # credential_id → broker name (for unregister)

_CATALOG: Catalog = Catalog()  # patched at startup; tests override
_ccxt_module = None  # injectable for tests


def _default_catalog_path() -> Path:
    return Path(__file__).resolve().parent / "catalog" / "exchanges.yml"


def _ensure_catalog() -> None:
    global _CATALOG
    if _CATALOG.entries:
        return
    try:
        _CATALOG = load_catalog(_default_catalog_path())
    except Exception as exc:  # noqa: BLE001
        LOG.warning("catalog load failed: %s", exc)


def register_broker(name: str, factory: Callable[[], BaseBroker]) -> None:
    """Register ``factory`` under ``name`` so :func:`get_broker` can look it up."""
    _REGISTRY[name] = factory


def list_brokers() -> list[str]:
    """Return the sorted list of registered broker names."""
    return sorted(_REGISTRY.keys())


def get_broker(name: str | None = None) -> BaseBroker:
    """Return a broker instance.

    ``name`` defaults to ``$SHOWME_BROKER`` and finally to ``"paper"``.
    Raises ``KeyError`` if the requested broker is not registered.
    """
    target = (name or os.environ.get("SHOWME_BROKER") or "paper").strip()
    factory = _REGISTRY.get(target)
    if not factory:
        raise KeyError(f"unknown broker: {target}. registered: {list_brokers()}")
    return factory()


# ── Dynamic credential registration ──────────────────────────────────────


def register_credential(record: "CredentialRecord", secrets: dict[str, str]) -> str:
    """Register ``record`` as a broker named ``{exchange_id}:{credential_id}``."""
    _ensure_catalog()
    try:
        entry = _CATALOG.by_id(record.exchange_id)
    except KeyError as exc:
        raise KeyError(f"catalog missing entry for {record.exchange_id}") from exc
    name = f"{record.exchange_id}:{record.id}"
    perms = record.permissions

    if entry.adapter == "ccxt":
        from .ccxt_broker import CcxtBroker

        def _factory(
            _eid: str = entry.ccxt_id or entry.id,
            _secrets: dict[str, str] = secrets,
            _perms: tuple[str, ...] = perms,
        ) -> BaseBroker:
            return CcxtBroker(
                exchange_id=_eid,
                credentials=_secrets,
                permissions=_perms,
                ccxt_module=_ccxt_module,
            )
    elif entry.adapter == "alpaca":
        from .alpaca import AlpacaPaperBroker

        def _factory(_secrets: dict[str, str] = secrets) -> BaseBroker:  # type: ignore[misc]
            # Live Alpaca shares the paper adapter's class — adapter
            # constructor picks base URL from env. Future: dedicated
            # AlpacaLiveBroker; for now we keep the wiring trivial.
            return AlpacaPaperBroker()
    else:
        raise KeyError(f"unsupported adapter '{entry.adapter}' in catalog entry {record.exchange_id}")

    register_broker(name, _factory)
    _DYNAMIC[record.id] = name
    LOG.info("registered broker: %s (perms=%s)", name, ",".join(perms))
    return name


def unregister_credential(credential_id: str) -> bool:
    name = _DYNAMIC.pop(credential_id, None)
    if name is None:
        return False
    _REGISTRY.pop(name, None)
    LOG.info("unregistered broker: %s", name)
    return True


def replay_stored_credentials(store: "CredentialStore") -> int:
    """Iterate ``store`` and register every credential. Returns count."""
    count = 0
    for rec in store.list():
        try:
            _, secrets = store.get(rec.id)
            register_credential(rec, secrets)
            count += 1
        except Exception as exc:  # noqa: BLE001
            LOG.warning("skip credential %s on replay: %s", rec.id, exc)
    return count


def close_all_brokers() -> None:
    """Hook for sidecar lifespan shutdown; closes ccxt sessions etc.

    Kept as a no-op-friendly best-effort sweep so the lifespan handler
    can always call it.
    """
    import asyncio
    for name, builder in list(_REGISTRY.items()):
        try:
            broker = builder()
        except Exception:  # noqa: BLE001
            continue
        close = getattr(broker, "aclose", None)
        if close is None:
            continue
        try:
            asyncio.get_event_loop().run_until_complete(close())
        except RuntimeError:
            # No running loop / loop closed — skip.
            pass


# ── Built-in registrations ───────────────────────────────────────────────

register_broker("paper", lambda: PaperBroker())

try:
    from .alpaca import AlpacaPaperBroker

    register_broker("alpaca-paper", lambda: AlpacaPaperBroker())
except Exception as exc:  # noqa: BLE001  # pragma: no cover — optional
    LOG.debug("alpaca broker unavailable: %s", exc)
```

- [ ] **Step 6.4: Update brokers/__init__.py exports**

Replace the contents of `backend/showme/brokers/__init__.py` with:

```python
"""showMe broker adapters.

Sub-system A: the abstraction now backs ~120 crypto exchanges (via
``CcxtBroker``) plus the original ``PaperBroker`` and ``AlpacaPaperBroker``.
Per-credential broker instances are registered at boot from the
``CredentialStore``.
"""
from .base import (
    BaseBroker,
    BrokerError,
    NotSupported,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    TimeInForce,
)
from .catalog.loader import Catalog, CatalogEntry, CatalogError, load_catalog
from .credential_store import (
    CredentialError,
    CredentialRecord,
    CredentialStore,
    UnknownCredential,
)
from .factory import (
    close_all_brokers,
    get_broker,
    list_brokers,
    register_broker,
    register_credential,
    replay_stored_credentials,
    unregister_credential,
)
from .paper import PaperBroker

try:
    from .alpaca import AlpacaPaperBroker  # noqa: F401
except Exception:  # pragma: no cover
    import logging as _logging
    _logging.getLogger("showme.brokers").debug(
        "AlpacaPaperBroker re-export skipped (optional dep missing)"
    )
    AlpacaPaperBroker = None  # type: ignore[misc,assignment]

try:
    from .ccxt_broker import CcxtBroker  # noqa: F401
except Exception:  # pragma: no cover
    import logging as _logging
    _logging.getLogger("showme.brokers").debug("CcxtBroker import skipped")
    CcxtBroker = None  # type: ignore[misc,assignment]


__all__ = [
    "AlpacaPaperBroker",
    "BaseBroker",
    "BrokerError",
    "Catalog",
    "CatalogEntry",
    "CatalogError",
    "CcxtBroker",
    "CredentialError",
    "CredentialRecord",
    "CredentialStore",
    "NotSupported",
    "Order",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PaperBroker",
    "Position",
    "TimeInForce",
    "UnknownCredential",
    "close_all_brokers",
    "get_broker",
    "list_brokers",
    "load_catalog",
    "register_broker",
    "register_credential",
    "replay_stored_credentials",
    "unregister_credential",
]
```

- [ ] **Step 6.5: Run the factory test, expect pass**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest tests/test_factory_dynamic.py -v`

Expected: 3 passed.

- [ ] **Step 6.6: Commit**

```bash
touch /tmp/.opsera-pre-commit-scan-passed
cd ~/Desktop/Projeler/proje/showMe
git add backend/showme/brokers/factory.py backend/showme/brokers/__init__.py \
        backend/tests/test_factory_dynamic.py
git commit -m "$(cat <<'EOF'
feat(brokers): dynamic credential→broker registration in factory

register_credential(rec, secrets) maps catalog adapter → BaseBroker
implementation; replay_stored_credentials(store) rehydrates on boot;
unregister_credential removes the broker when a credential is deleted.
close_all_brokers hook for lifespan shutdown.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Exchange routes

**Files:**
- Create: `backend/showme/server_routes/exchange.py`
- Modify: `backend/showme/server_routes/__init__.py`
- Modify: `backend/showme/server.py` (replay credentials on boot)
- Create: `backend/tests/test_exchange_routes.py`

- [ ] **Step 7.1: Write the route tests**

Create `backend/tests/test_exchange_routes.py`:

```python
"""FastAPI route tests for /api/exchange/*.

The store is forced to the memory backend via env, and the catalog is
patched onto the factory so we don't depend on ccxt's full registry."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from showme.brokers import factory as factory_mod
from showme.brokers.catalog.loader import load_catalog
from showme.server import build_app

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


def _fake_ccxt() -> SimpleNamespace:
    class _Ex:
        def __init__(self, **_kw):
            self.fetch_balance = AsyncMock(return_value={"total": {"USDT": 10}, "free": {"USDT": 10}})
            self.close = AsyncMock()
    return SimpleNamespace(async_support=SimpleNamespace(binance=_Ex))


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    yml = tmp_path / "ex.yml"
    yml.write_text(YAML)
    monkeypatch.setattr(factory_mod, "_CATALOG", load_catalog(yml))
    monkeypatch.setattr(factory_mod, "_ccxt_module", _fake_ccxt())
    # Reset factory dynamic state between tests:
    factory_mod._DYNAMIC.clear()
    for name in list(factory_mod._REGISTRY.keys()):
        if ":" in name:
            factory_mod._REGISTRY.pop(name, None)
    app = build_app()
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def test_catalog_returns_list(client: TestClient) -> None:
    r = client.get("/api/exchange/catalog")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert {e["id"] for e in body} >= {"binance"}


def test_list_credentials_starts_empty(client: TestClient) -> None:
    r = client.get("/api/exchange/credentials")
    assert r.status_code == 200
    assert r.json() == {"records": []}


def test_create_credential_persists_and_registers_broker(client: TestClient) -> None:
    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "binance",
        "account_label": "main",
        "secrets": {"api_key": "k", "api_secret": "s"},
        "permissions": ["read"],
        "skip_test": True,
    })
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["exchange_id"] == "binance"
    assert rec["permissions"] == ["read"]
    # No secret leaks in body:
    assert "api_key" not in r.text and "api_secret" not in r.text
    # Broker is now in the registry:
    list_r = client.get(f"/api/broker/positions?name=binance:{rec['id']}")
    assert list_r.status_code == 200


def test_create_credential_validates_against_catalog(client: TestClient) -> None:
    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "not-an-exchange",
        "account_label": "x",
        "secrets": {"api_key": "k", "api_secret": "s"},
        "permissions": ["read"],
        "skip_test": True,
    })
    assert r.status_code == 400


def test_create_credential_requires_all_fields_from_catalog(client: TestClient) -> None:
    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "binance",
        "account_label": "main",
        "secrets": {"api_key": "k"},  # missing api_secret
        "permissions": ["read"],
        "skip_test": True,
    })
    assert r.status_code == 400
    assert "api_secret" in r.json()["detail"]


def test_delete_credential_removes_broker(client: TestClient) -> None:
    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "binance", "account_label": "main",
        "secrets": {"api_key": "k", "api_secret": "s"},
        "permissions": ["read"], "skip_test": True,
    })
    rid = r.json()["id"]
    d = client.delete(f"/api/exchange/credentials/{rid}")
    assert d.status_code == 200
    list_r = client.get(f"/api/broker/positions?name=binance:{rid}")
    assert list_r.status_code == 404


def test_test_credential_calls_account(client: TestClient) -> None:
    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "binance", "account_label": "main",
        "secrets": {"api_key": "k", "api_secret": "s"},
        "permissions": ["read"], "skip_test": True,
    })
    rid = r.json()["id"]
    t = client.post(f"/api/exchange/credentials/{rid}/test")
    assert t.status_code == 200
    body = t.json()
    assert body["ok"] is True
    assert body["account"]["equity"] == 10


def test_patch_permissions_requires_re_typed_label(client: TestClient) -> None:
    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "binance", "account_label": "main",
        "secrets": {"api_key": "k", "api_secret": "s"},
        "permissions": ["read"], "skip_test": True,
    })
    rid = r.json()["id"]
    # Without confirm_account_label → 400
    bad = client.patch(f"/api/exchange/credentials/{rid}", json={
        "permissions": ["read", "trade"],
    })
    assert bad.status_code == 400
    # Wrong confirm → 400
    wrong = client.patch(f"/api/exchange/credentials/{rid}", json={
        "permissions": ["read", "trade"],
        "confirm_account_label": "wrong",
    })
    assert wrong.status_code == 400
    # Correct confirm → 200
    good = client.patch(f"/api/exchange/credentials/{rid}", json={
        "permissions": ["read", "trade"],
        "confirm_account_label": "main",
    })
    assert good.status_code == 200
    assert good.json()["permissions"] == ["read", "trade"]
```

- [ ] **Step 7.2: Run the route test, expect 404s (routes not registered)**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest tests/test_exchange_routes.py -v`

Expected: failures with 404 on `/api/exchange/...` paths.

- [ ] **Step 7.3: Implement the routes**

Create `backend/showme/server_routes/exchange.py`:

```python
"""Routes: /api/exchange/* — catalog discovery + credential CRUD.

The CredentialStore is constructed lazily per-request via
``CredentialStore.fresh()`` so a) tests can swap env vars between
requests and b) we don't hold a long-lived reference that hides
state across the lifespan.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import AppDeps


class CredentialCreate(BaseModel):
    exchange_id: str
    account_label: str = Field(..., min_length=1, max_length=64)
    secrets: dict[str, str]
    permissions: list[str] = Field(default_factory=lambda: ["read"])
    skip_test: bool = False


class CredentialPatch(BaseModel):
    permissions: list[str] | None = None
    account_label: str | None = Field(default=None, min_length=1, max_length=64)
    confirm_account_label: str | None = None


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/exchange/catalog")
    async def exchange_catalog() -> list[dict[str, Any]]:
        from showme.brokers import factory as factory_mod
        factory_mod._ensure_catalog()
        return factory_mod._CATALOG.to_payload()

    @router.get("/api/exchange/credentials")
    async def list_credentials() -> dict[str, Any]:
        from showme.brokers import CredentialStore
        store = CredentialStore.fresh()
        return {"records": [r.to_dict() for r in store.list()]}

    @router.post("/api/exchange/credentials")
    async def create_credential(payload: CredentialCreate) -> dict[str, Any]:
        from showme.brokers import (
            CredentialStore, factory as factory_mod, get_broker,
        )
        factory_mod._ensure_catalog()
        try:
            entry = factory_mod._CATALOG.by_id(payload.exchange_id)
        except KeyError:
            raise HTTPException(400, detail=f"unknown exchange: {payload.exchange_id}")
        missing = [k for k in entry.requires if not payload.secrets.get(k)]
        if missing:
            raise HTTPException(
                400, detail=f"missing required secret fields: {','.join(missing)}",
            )
        for p in payload.permissions:
            if p not in {"read", "trade"}:
                raise HTTPException(400, detail=f"invalid permission: {p}")
        store = CredentialStore.fresh()
        rec = store.add(
            exchange_id=payload.exchange_id,
            account_label=payload.account_label,
            secrets=payload.secrets,
            permissions=tuple(payload.permissions),
        )
        factory_mod.register_credential(rec, payload.secrets)

        if not payload.skip_test:
            try:
                broker = get_broker(f"{payload.exchange_id}:{rec.id}")
                await broker.account()
            except Exception as exc:  # noqa: BLE001
                # Test failed: roll back so we don't leave a half-saved key.
                factory_mod.unregister_credential(rec.id)
                store.delete(rec.id)
                raise HTTPException(400, detail=f"auth test failed: {exc}") from exc

        return rec.to_dict()

    @router.delete("/api/exchange/credentials/{credential_id}")
    async def delete_credential(credential_id: str) -> dict[str, Any]:
        from showme.brokers import CredentialStore, factory as factory_mod
        store = CredentialStore.fresh()
        if not store.delete(credential_id):
            raise HTTPException(404, detail="credential not found")
        factory_mod.unregister_credential(credential_id)
        return {"ok": True}

    @router.patch("/api/exchange/credentials/{credential_id}")
    async def patch_credential(credential_id: str, payload: CredentialPatch) -> dict[str, Any]:
        from showme.brokers import (
            CredentialStore, UnknownCredential, factory as factory_mod,
        )
        store = CredentialStore.fresh()
        try:
            rec, secrets = store.get(credential_id)
        except UnknownCredential:
            raise HTTPException(404, detail="credential not found")

        if payload.permissions is not None:
            wants_escalation = "trade" in payload.permissions and "trade" not in rec.permissions
            if wants_escalation:
                if payload.confirm_account_label != rec.account_label:
                    raise HTTPException(
                        400,
                        detail="privilege escalation requires confirm_account_label "
                               "matching the credential's account_label",
                    )
            for p in payload.permissions:
                if p not in {"read", "trade"}:
                    raise HTTPException(400, detail=f"invalid permission: {p}")
            rec = store.update_permissions(credential_id, tuple(payload.permissions))
            # Re-register so the live broker picks up the new perms.
            factory_mod.unregister_credential(credential_id)
            factory_mod.register_credential(rec, secrets)
        return rec.to_dict()

    @router.post("/api/exchange/credentials/{credential_id}/test")
    async def test_credential(credential_id: str) -> dict[str, Any]:
        from showme.brokers import CredentialStore, get_broker
        store = CredentialStore.fresh()
        try:
            rec, _ = store.get(credential_id)
        except KeyError:
            raise HTTPException(404, detail="credential not found")
        try:
            broker = get_broker(f"{rec.exchange_id}:{rec.id}")
            account = await broker.account()
            return {"ok": True, "account": account}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    app.include_router(router)
```

- [ ] **Step 7.4: Wire the route family into the registrar**

In `backend/showme/server_routes/__init__.py`, find the import block inside `register_routes` and the call list. Modify both:

```python
def register_routes(app: FastAPI, *, deps: AppDeps) -> None:
    """Mount every route family onto ``app`` using the shared ``deps``."""
    from . import (
        agent, ask, broker, exchange, function_index, health, instant, mis,
        portfolio, proxy, quote, scanner, state, veryfinder, watchlists,
        websocket, xai,
    )
    health.register(app, deps)
    function_index.register(app, deps)
    quote.register(app, deps)
    scanner.register(app, deps)
    mis.register(app, deps)
    portfolio.register(app, deps)
    broker.register(app, deps)
    exchange.register(app, deps)            # ← NEW
    instant.register(app, deps)
    xai.register(app, deps)
    agent.register(app, deps)
    ask.register(app, deps)
    state.register(app, deps)
    watchlists.register(app, deps)
    veryfinder.register(app, deps)
    websocket.register(app, deps)
    proxy.register(app, deps)
```

- [ ] **Step 7.5: Replay credentials on sidecar boot**

In `backend/showme/server.py`, find the `build_app` function and the line `register_routes(app, deps=deps)`. Right after it, insert:

```python
    # Sub-system A boot replay: rehydrate broker registry from the
    # CredentialStore so /api/broker/* works after a restart.
    try:
        from showme.brokers import CredentialStore, replay_stored_credentials
        replay_stored_credentials(CredentialStore.fresh())
    except Exception as exc:  # noqa: BLE001 — non-fatal; log + continue
        import logging as _logging
        _logging.getLogger("showme.server").warning(
            "credential replay skipped: %s", exc,
        )
```

- [ ] **Step 7.6: Run the route test, expect pass**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest tests/test_exchange_routes.py -v`

Expected: 8 passed.

- [ ] **Step 7.7: Commit**

```bash
touch /tmp/.opsera-pre-commit-scan-passed
cd ~/Desktop/Projeler/proje/showMe
git add backend/showme/server_routes/exchange.py \
        backend/showme/server_routes/__init__.py \
        backend/showme/server.py backend/tests/test_exchange_routes.py
git commit -m "$(cat <<'EOF'
feat(server): /api/exchange/* routes + boot replay

GET/POST/DELETE/PATCH credentials, GET catalog, POST {id}/test. Privilege
escalation gated by confirm_account_label. Boot replay rehydrates the
factory so /api/broker/* survives a restart.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: UI exchange store (zustand)

**Files:**
- Create: `ui/src/lib/exchange-store.ts`
- Create: `ui/src/lib/exchange-store.test.ts`

- [ ] **Step 8.1: Write the store test**

Create `ui/src/lib/exchange-store.test.ts`:

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useExchangeStore } from "./exchange-store";

const ORIGINAL_FETCH = global.fetch;

function mockFetch(responses: Record<string, unknown>): typeof fetch {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    for (const [pattern, body] of Object.entries(responses)) {
      if (url.includes(pattern)) {
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
    }
    return new Response("{}", { status: 404 });
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  useExchangeStore.setState({
    catalog: [],
    credentials: [],
    selectedExchangeId: null,
    catalogLoading: false,
    credentialsLoading: false,
    error: null,
  });
});

afterEach(() => {
  global.fetch = ORIGINAL_FETCH;
});

describe("exchange-store", () => {
  it("loadCatalog populates entries", async () => {
    global.fetch = mockFetch({
      "/api/exchange/catalog": [
        { id: "binance", display_name: "Binance", aliases: [], asset_classes: ["spot"], regions: ["global"], adapter: "ccxt", requires: ["api_key", "api_secret"], optional: [], capabilities: {}, ccxt_id: "binance", notes: "" },
      ],
    });
    await useExchangeStore.getState().loadCatalog();
    const cat = useExchangeStore.getState().catalog;
    expect(cat.length).toBe(1);
    expect(cat[0].id).toBe("binance");
  });

  it("loadCredentials populates records", async () => {
    global.fetch = mockFetch({
      "/api/exchange/credentials": {
        records: [
          { id: "abc", exchange_id: "binance", account_label: "main", permissions: ["read"], created_at: "2026-05-21T10:00:00Z" },
        ],
      },
    });
    await useExchangeStore.getState().loadCredentials();
    expect(useExchangeStore.getState().credentials.length).toBe(1);
  });

  it("saveCredential POSTs and re-loads", async () => {
    const posted: unknown[] = [];
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/exchange/credentials") && init?.method === "POST") {
        posted.push(JSON.parse(String(init.body)));
        return new Response(JSON.stringify({
          id: "new-id", exchange_id: "binance", account_label: "main",
          permissions: ["read"], created_at: "2026-05-21",
        }), { status: 200 });
      }
      if (url.endsWith("/api/exchange/credentials")) {
        return new Response(JSON.stringify({ records: [] }), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    }) as unknown as typeof fetch;
    const ok = await useExchangeStore.getState().saveCredential({
      exchange_id: "binance",
      account_label: "main",
      secrets: { api_key: "k", api_secret: "s" },
      permissions: ["read"],
      skip_test: true,
    });
    expect(ok).toBe(true);
    expect((posted[0] as { exchange_id: string }).exchange_id).toBe("binance");
  });

  it("testCredential returns ok:false on backend failure", async () => {
    global.fetch = mockFetch({
      "/test": { ok: false, error: "boom" },
    });
    const r = await useExchangeStore.getState().testCredential("any-id");
    expect(r.ok).toBe(false);
    expect(r.error).toBe("boom");
  });

  it("filterCatalog searches across name + aliases", () => {
    useExchangeStore.setState({
      catalog: [
        { id: "binance", display_name: "Binance", aliases: ["binance.com"], asset_classes: ["spot"], regions: ["global"], adapter: "ccxt", requires: [], optional: [], capabilities: {}, ccxt_id: "binance", notes: "" },
        { id: "kraken", display_name: "Kraken", aliases: [], asset_classes: ["spot"], regions: ["global"], adapter: "ccxt", requires: [], optional: [], capabilities: {}, ccxt_id: "kraken", notes: "" },
      ],
    });
    const hits = useExchangeStore.getState().filterCatalog({
      query: "binance.com", assetClasses: [], regions: [],
    });
    expect(hits.map((e) => e.id)).toEqual(["binance"]);
  });
});
```

- [ ] **Step 8.2: Run the store test, expect ImportError**

Run: `cd ~/Desktop/Projeler/proje/showMe/ui && npm test -- exchange-store`

Expected: file not found errors.

- [ ] **Step 8.3: Implement the store**

Create `ui/src/lib/exchange-store.ts`:

```typescript
/**
 * Sub-system A: zustand store for the Connect-Exchange pane.
 *
 * - `catalog` lists available exchanges from `/api/exchange/catalog`.
 * - `credentials` lists saved connections (no secrets, server-side).
 * - Form input (api_key etc.) is kept in component-local state ONLY.
 */
import { create } from "zustand";

const TOKEN_HEADER = "X-ShowMe-Token";

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  // SHOWME_AUTH_TOKEN is injected at sidecar handshake time, exposed
  // via `window.__SHOWME_TOKEN__` (existing pattern — see lib/sidecar.ts).
  const tok =
    typeof window !== "undefined"
      ? ((window as unknown as { __SHOWME_TOKEN__?: string }).__SHOWME_TOKEN__ ?? "")
      : "";
  const h: Record<string, string> = { "Content-Type": "application/json", ...extra };
  if (tok) h[TOKEN_HEADER] = tok;
  return h;
}

export interface CatalogEntry {
  id: string;
  display_name: string;
  aliases: string[];
  asset_classes: string[];
  regions: string[];
  adapter: string;
  requires: string[];
  optional: string[];
  capabilities: Record<string, boolean>;
  ccxt_id: string | null;
  notes: string;
}

export interface CredentialRecord {
  id: string;
  exchange_id: string;
  account_label: string;
  permissions: ("read" | "trade")[];
  created_at: string;
}

export interface CreateCredentialPayload {
  exchange_id: string;
  account_label: string;
  secrets: Record<string, string>;
  permissions: ("read" | "trade")[];
  skip_test?: boolean;
}

export interface CatalogFilter {
  query: string;
  assetClasses: string[];
  regions: string[];
}

interface ExchangeStoreShape {
  catalog: CatalogEntry[];
  credentials: CredentialRecord[];
  selectedExchangeId: string | null;
  catalogLoading: boolean;
  credentialsLoading: boolean;
  error: string | null;

  loadCatalog: () => Promise<void>;
  loadCredentials: () => Promise<void>;
  saveCredential: (payload: CreateCredentialPayload) => Promise<boolean>;
  deleteCredential: (credentialId: string) => Promise<boolean>;
  testCredential: (credentialId: string) => Promise<{ ok: boolean; account?: unknown; error?: string }>;
  upgradeToTrade: (credentialId: string, accountLabel: string) => Promise<boolean>;

  setSelectedExchange: (id: string | null) => void;
  filterCatalog: (f: CatalogFilter) => CatalogEntry[];
}

export const useExchangeStore = create<ExchangeStoreShape>((set, get) => ({
  catalog: [],
  credentials: [],
  selectedExchangeId: null,
  catalogLoading: false,
  credentialsLoading: false,
  error: null,

  loadCatalog: async () => {
    set({ catalogLoading: true, error: null });
    try {
      const r = await fetch("/api/exchange/catalog", { headers: authHeaders() });
      if (!r.ok) throw new Error(`catalog failed: ${r.status}`);
      const body = (await r.json()) as CatalogEntry[];
      set({ catalog: body, catalogLoading: false });
    } catch (e) {
      set({ catalogLoading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },

  loadCredentials: async () => {
    set({ credentialsLoading: true, error: null });
    try {
      const r = await fetch("/api/exchange/credentials", { headers: authHeaders() });
      if (!r.ok) throw new Error(`credentials failed: ${r.status}`);
      const body = (await r.json()) as { records: CredentialRecord[] };
      set({ credentials: body.records, credentialsLoading: false });
    } catch (e) {
      set({ credentialsLoading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },

  saveCredential: async (payload) => {
    try {
      const r = await fetch("/api/exchange/credentials", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const body = (await r.json().catch(() => ({ detail: r.statusText }))) as { detail?: string };
        set({ error: body.detail ?? `save failed: ${r.status}` });
        return false;
      }
      await get().loadCredentials();
      return true;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      return false;
    }
  },

  deleteCredential: async (credentialId) => {
    const r = await fetch(`/api/exchange/credentials/${credentialId}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!r.ok) return false;
    await get().loadCredentials();
    return true;
  },

  testCredential: async (credentialId) => {
    const r = await fetch(`/api/exchange/credentials/${credentialId}/test`, {
      method: "POST",
      headers: authHeaders(),
    });
    return (await r.json()) as { ok: boolean; account?: unknown; error?: string };
  },

  upgradeToTrade: async (credentialId, accountLabel) => {
    const r = await fetch(`/api/exchange/credentials/${credentialId}`, {
      method: "PATCH",
      headers: authHeaders(),
      body: JSON.stringify({
        permissions: ["read", "trade"],
        confirm_account_label: accountLabel,
      }),
    });
    if (!r.ok) return false;
    await get().loadCredentials();
    return true;
  },

  setSelectedExchange: (id) => set({ selectedExchangeId: id }),

  filterCatalog: ({ query, assetClasses, regions }) => {
    const q = query.trim().toLowerCase();
    return get().catalog.filter((e) => {
      if (q) {
        const hit =
          e.id.toLowerCase().includes(q) ||
          e.display_name.toLowerCase().includes(q) ||
          e.aliases.some((a) => a.toLowerCase().includes(q));
        if (!hit) return false;
      }
      if (assetClasses.length && !assetClasses.some((c) => e.asset_classes.includes(c))) {
        return false;
      }
      if (regions.length && !regions.some((r) => e.regions.includes(r))) {
        return false;
      }
      return true;
    });
  },
}));
```

- [ ] **Step 8.4: Run the store test, expect pass**

Run: `cd ~/Desktop/Projeler/proje/showMe/ui && npm test -- exchange-store`

Expected: 5 passed.

- [ ] **Step 8.5: Commit**

```bash
touch /tmp/.opsera-pre-commit-scan-passed
cd ~/Desktop/Projeler/proje/showMe
git add ui/src/lib/exchange-store.ts ui/src/lib/exchange-store.test.ts
git commit -m "$(cat <<'EOF'
feat(ui): zustand exchange-store for CONN pane

Catalog + credentials state, save / delete / test / upgradeToTrade
actions, in-memory filterCatalog. Auth header threading via the
existing X-ShowMe-Token convention.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: CONN pane component

**Files:**
- Create: `ui/src/functions/CONN.tsx`
- Create: `ui/src/functions/CONN.test.tsx`
- Modify: `ui/src/functions/registry.tsx`

- [ ] **Step 9.1: Write the pane test**

Create `ui/src/functions/CONN.test.tsx`:

```typescript
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CONNPane } from "./CONN";
import { useExchangeStore } from "@/lib/exchange-store";

const ORIGINAL_FETCH = global.fetch;

beforeEach(() => {
  useExchangeStore.setState({
    catalog: [
      { id: "binance", display_name: "Binance", aliases: ["binance.com"],
        asset_classes: ["spot", "futures"], regions: ["global"],
        adapter: "ccxt", requires: ["api_key", "api_secret"], optional: [],
        capabilities: { fetch_balance: true }, ccxt_id: "binance", notes: "" },
      { id: "kraken", display_name: "Kraken", aliases: [],
        asset_classes: ["spot"], regions: ["us", "eu"],
        adapter: "ccxt", requires: ["api_key", "api_secret"], optional: [],
        capabilities: { fetch_balance: true }, ccxt_id: "kraken", notes: "" },
      { id: "okx", display_name: "OKX", aliases: [],
        asset_classes: ["spot", "futures"], regions: ["global"],
        adapter: "ccxt", requires: ["api_key", "api_secret", "passphrase"],
        optional: [], capabilities: { fetch_balance: true }, ccxt_id: "okx", notes: "" },
    ],
    credentials: [],
    selectedExchangeId: null,
    catalogLoading: false,
    credentialsLoading: false,
    error: null,
  });
});

afterEach(() => {
  global.fetch = ORIGINAL_FETCH;
});

describe("CONN pane", () => {
  it("renders the exchange list", () => {
    render(<CONNPane />);
    expect(screen.getByText("Binance")).toBeInTheDocument();
    expect(screen.getByText("Kraken")).toBeInTheDocument();
    expect(screen.getByText("OKX")).toBeInTheDocument();
  });

  it("search filters the list", () => {
    render(<CONNPane />);
    fireEvent.change(screen.getByPlaceholderText(/borsa ara/i), {
      target: { value: "krak" },
    });
    expect(screen.queryByText("Binance")).toBeNull();
    expect(screen.getByText("Kraken")).toBeInTheDocument();
  });

  it("region chip narrows results", () => {
    render(<CONNPane />);
    fireEvent.click(screen.getByRole("button", { name: /us$/i }));
    expect(screen.queryByText("Binance")).toBeNull();   // global, not us
    expect(screen.getByText("Kraken")).toBeInTheDocument();
  });

  it("selecting OKX reveals passphrase input", () => {
    render(<CONNPane />);
    fireEvent.click(screen.getByText("OKX"));
    expect(screen.getByLabelText(/api_key/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/api_secret/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/passphrase/i)).toBeInTheDocument();
  });

  it("read-only is the default; trade toggle shows red warning copy", () => {
    render(<CONNPane />);
    fireEvent.click(screen.getByText("Binance"));
    const tradeToggle = screen.getByRole("checkbox", { name: /işlem/i });
    expect(tradeToggle).not.toBeChecked();
    fireEvent.click(tradeToggle);
    expect(screen.getByText(/dikkat/i)).toBeInTheDocument();
  });

  it("submitting a form calls saveCredential", async () => {
    const save = vi.spyOn(useExchangeStore.getState(), "saveCredential")
      .mockResolvedValue(true);
    render(<CONNPane />);
    fireEvent.click(screen.getByText("Binance"));
    fireEvent.change(screen.getByLabelText(/account label/i), { target: { value: "main" } });
    fireEvent.change(screen.getByLabelText(/api_key/i), { target: { value: "k" } });
    fireEvent.change(screen.getByLabelText(/api_secret/i), { target: { value: "s" } });
    fireEvent.click(screen.getByRole("button", { name: /bağlan/i }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    const call = save.mock.calls[0][0];
    expect(call.exchange_id).toBe("binance");
    expect(call.secrets).toEqual({ api_key: "k", api_secret: "s" });
    expect(call.permissions).toEqual(["read"]);
  });
});
```

- [ ] **Step 9.2: Run the pane test, expect file-not-found errors**

Run: `cd ~/Desktop/Projeler/proje/showMe/ui && npm test -- CONN`

Expected: import errors for `./CONN`.

- [ ] **Step 9.3: Implement the pane**

Create `ui/src/functions/CONN.tsx`:

```tsx
/**
 * CONN — Connect Exchange.
 *
 * Sub-system A's user surface. Search + filter the catalog, add /
 * test / delete connections, escalate read-only credentials to
 * trade via re-typed-label confirmation.
 */
import { useEffect, useMemo, useState } from "react";
import {
  type CatalogEntry,
  type CredentialRecord,
  useExchangeStore,
} from "@/lib/exchange-store";

const ASSET_CLASSES = ["spot", "futures", "swap", "margin", "options", "equity", "fx"] as const;
const REGIONS = ["global", "us", "eu", "asia"] as const;

function Initials({ name }: { name: string }) {
  const tag = name.replace(/[^A-Za-zĞÜŞİÖÇğüşıöç]/g, "").slice(0, 2).toUpperCase();
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 28,
        height: 28,
        borderRadius: 6,
        background: "var(--surface-2)",
        color: "var(--fg-2)",
        fontWeight: 600,
        fontSize: 12,
        flex: "0 0 auto",
      }}
    >
      {tag || "??"}
    </span>
  );
}

function CredentialRow({
  rec, onDelete, onTest, onEscalate,
}: {
  rec: CredentialRecord;
  onDelete: (id: string) => void;
  onTest: (id: string) => void;
  onEscalate: (id: string, label: string) => void;
}) {
  const [confirm, setConfirm] = useState("");
  const [testing, setTesting] = useState<"idle" | "ok" | "err">("idle");
  const [testMsg, setTestMsg] = useState<string | null>(null);
  const canTrade = rec.permissions.includes("trade");
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "1fr auto auto auto",
      gap: 8, alignItems: "center", padding: "6px 0",
      borderBottom: "1px solid var(--border-1)",
    }}>
      <div>
        <strong>{rec.account_label}</strong>{" "}
        <span style={{ color: canTrade ? "var(--accent-warn)" : "var(--fg-2)" }}>
          {canTrade ? "okuma + işlem" : "salt okuma"}
        </span>
      </div>
      <button onClick={async () => {
        setTesting("idle"); setTestMsg(null);
        const r = await useExchangeStore.getState().testCredential(rec.id);
        setTesting(r.ok ? "ok" : "err");
        setTestMsg(r.ok ? "OK" : (r.error ?? "fail"));
      }}>
        Test
      </button>
      {!canTrade && (
        <form onSubmit={(e) => {
          e.preventDefault();
          if (confirm === rec.account_label) {
            onEscalate(rec.id, confirm);
          }
        }} style={{ display: "flex", gap: 4 }}>
          <input
            placeholder={`re-type "${rec.account_label}"`}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            style={{ width: 140 }}
          />
          <button type="submit" disabled={confirm !== rec.account_label}>
            Upgrade
          </button>
        </form>
      )}
      <button onClick={() => onDelete(rec.id)}>Sil</button>
      {testMsg && (
        <div style={{ gridColumn: "1 / -1", color: testing === "ok" ? "var(--accent-ok)" : "var(--accent-err)" }}>
          {testMsg}
        </div>
      )}
    </div>
  );
}

function ExchangeForm({ entry }: { entry: CatalogEntry }) {
  const credentials = useExchangeStore((s) => s.credentials);
  const save = useExchangeStore((s) => s.saveCredential);
  const error = useExchangeStore((s) => s.error);
  const [label, setLabel] = useState("");
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [permsTrade, setPermsTrade] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const allFields = [...entry.requires, ...entry.optional];

  const myCreds = credentials.filter((c) => c.exchange_id === entry.id);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <h3>{entry.display_name} bağlantıları</h3>
      {myCreds.length === 0 && <div style={{ color: "var(--fg-2)" }}>(henüz bağlantı yok)</div>}
      {myCreds.map((rec) => (
        <CredentialRow
          key={rec.id}
          rec={rec}
          onDelete={(id) => useExchangeStore.getState().deleteCredential(id)}
          onTest={(id) => useExchangeStore.getState().testCredential(id)}
          onEscalate={(id, label) => useExchangeStore.getState().upgradeToTrade(id, label)}
        />
      ))}

      <h4>Yeni bağlantı ekle</h4>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setSubmitting(true);
          const ok = await save({
            exchange_id: entry.id,
            account_label: label,
            secrets,
            permissions: permsTrade ? ["read", "trade"] : ["read"],
          });
          setSubmitting(false);
          if (ok) {
            setLabel("");
            setSecrets({});
            setPermsTrade(false);
          }
        }}
        style={{ display: "flex", flexDirection: "column", gap: 6 }}
      >
        <label>
          account label
          <input value={label} onChange={(e) => setLabel(e.target.value)} required minLength={1} />
        </label>
        {allFields.map((field) => (
          <label key={field}>
            {field}
            <input
              type={field.includes("secret") || field.includes("passphrase") ? "password" : "text"}
              value={secrets[field] ?? ""}
              onChange={(e) => setSecrets({ ...secrets, [field]: e.target.value })}
              required={entry.requires.includes(field)}
            />
          </label>
        ))}
        <label>
          <input
            type="checkbox"
            checked={permsTrade}
            onChange={(e) => setPermsTrade(e.target.checked)}
          />
          Okuma + işlem (trade) izni
        </label>
        {permsTrade && (
          <div style={{ color: "var(--accent-err)" }}>
            Dikkat: bu kimlik bilgisi gerçek hesapta emir gönderebilir. Borsa tarafında da
            "trading" scope'unu gerçekten verdiğinden ve API anahtarını IP'ye bağladığından
            emin ol.
          </div>
        )}
        <button type="submit" disabled={submitting}>{submitting ? "..." : "Bağlan"}</button>
        {error && <div style={{ color: "var(--accent-err)" }}>{error}</div>}
      </form>
    </div>
  );
}

export function CONNPane() {
  const catalog = useExchangeStore((s) => s.catalog);
  const credentials = useExchangeStore((s) => s.credentials);
  const selectedId = useExchangeStore((s) => s.selectedExchangeId);
  const filterCatalog = useExchangeStore((s) => s.filterCatalog);
  const loadCatalog = useExchangeStore((s) => s.loadCatalog);
  const loadCreds = useExchangeStore((s) => s.loadCredentials);
  const setSelected = useExchangeStore((s) => s.setSelectedExchange);
  const [query, setQuery] = useState("");
  const [assetClasses, setAssetClasses] = useState<string[]>([]);
  const [regions, setRegions] = useState<string[]>([]);

  useEffect(() => { loadCatalog(); loadCreds(); }, [loadCatalog, loadCreds]);

  const filtered = useMemo(
    () => filterCatalog({ query, assetClasses, regions }),
    [query, assetClasses, regions, filterCatalog, catalog],
  );

  const credCount = (exId: string) =>
    credentials.filter((c) => c.exchange_id === exId).length;

  const selected = selectedId ? catalog.find((e) => e.id === selectedId) ?? null : null;

  const toggle = (
    arr: string[], setArr: (v: string[]) => void, val: string,
  ) => () => setArr(arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val]);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(280px, 1fr) 2fr", gap: 16, height: "100%" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, overflow: "hidden" }}>
        <input
          placeholder="Borsa ara…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Borsa ara"
        />
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {ASSET_CLASSES.map((a) => (
            <button
              key={a}
              onClick={toggle(assetClasses, setAssetClasses, a)}
              aria-pressed={assetClasses.includes(a)}
              style={{
                opacity: assetClasses.includes(a) ? 1 : 0.55,
                fontSize: 11,
              }}
            >
              {a}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {REGIONS.map((r) => (
            <button
              key={r}
              onClick={toggle(regions, setRegions, r)}
              aria-pressed={regions.includes(r)}
              style={{
                opacity: regions.includes(r) ? 1 : 0.55,
                fontSize: 11,
              }}
            >
              {r}
            </button>
          ))}
        </div>
        <div style={{ overflowY: "auto", flex: 1, minHeight: 0 }}>
          {filtered.map((e) => (
            <button
              key={e.id}
              onClick={() => setSelected(e.id)}
              style={{
                display: "grid", gridTemplateColumns: "auto 1fr auto",
                gap: 8, alignItems: "center", padding: "6px 8px",
                width: "100%", textAlign: "left",
                background: selectedId === e.id ? "var(--surface-2)" : "transparent",
                border: "none", borderBottom: "1px solid var(--border-1)",
                cursor: "pointer",
              }}
            >
              <Initials name={e.display_name} />
              <div>
                <div>{e.display_name}</div>
                <div style={{ fontSize: 10, color: "var(--fg-2)" }}>
                  {e.asset_classes.join(" · ")}
                </div>
              </div>
              {credCount(e.id) > 0 && (
                <span style={{ fontSize: 11, color: "var(--accent-ok)" }}>
                  Bağlı: {credCount(e.id)}
                </span>
              )}
            </button>
          ))}
          {filtered.length === 0 && (
            <div style={{ padding: 12, color: "var(--fg-2)" }}>
              Eşleşen borsa yok.
            </div>
          )}
        </div>
      </div>
      <div style={{ overflowY: "auto" }}>
        {selected ? (
          <ExchangeForm entry={selected} />
        ) : (
          <div style={{ color: "var(--fg-2)" }}>
            Soldan bir borsa seç.
          </div>
        )}
      </div>
    </div>
  );
}

export default CONNPane;
```

- [ ] **Step 9.4: Run the pane test, expect pass**

Run: `cd ~/Desktop/Projeler/proje/showMe/ui && npm test -- CONN`

Expected: 6 passed.

- [ ] **Step 9.5: Register the pane**

In `ui/src/functions/registry.tsx`, find the block of `const XxxPane = lazy(() => ...)` declarations. After the last one, add:

```typescript
const CONNPane = lazy(() => import("./CONN").then((m) => ({ default: m.CONNPane })));
```

Then locate the `PANES` record and add `CONN: CONNPane,` in alphabetical order (under `CORR` or near it, whichever convention the surrounding entries follow).

- [ ] **Step 9.6: Add CONN to the sidebar**

In `ui/src/lib/workspace.ts`, locate the sidebar groups data structure (search for `Sidebar` or `SIDEBAR_GROUPS`). Add a new group entry — or insert into an existing "Settings" / "Connections" group — with this entry:

```typescript
{ code: "CONN", label: "Connect Exchange", group: "Connections" }
```

If a `Connections` group does not exist, add it as a new group above `Settings`.

- [ ] **Step 9.7: Run all UI tests, expect green**

Run: `cd ~/Desktop/Projeler/proje/showMe/ui && npm test`

Expected: full suite green (existing tests + new ones).

- [ ] **Step 9.8: Commit**

```bash
touch /tmp/.opsera-pre-commit-scan-passed
cd ~/Desktop/Projeler/proje/showMe
git add ui/src/functions/CONN.tsx ui/src/functions/CONN.test.tsx \
        ui/src/functions/registry.tsx ui/src/lib/workspace.ts
git commit -m "$(cat <<'EOF'
feat(ui): CONN pane — Connect Exchange UI

Catalog list with search + asset-class + region chip filters,
per-exchange detail form with dynamic required-fields, read-only by
default with red-warning trade toggle, in-row Test/Delete/Upgrade for
saved connections. Registered as CONN in the sidebar's new
"Connections" group.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Live smoke + native rebuild

**Files (no new code, verification only):**

- [ ] **Step 10.1: Full backend test pass**

Run: `cd ~/Desktop/Projeler/proje/showMe/backend && pytest -v 2>&1 | tail -40`

Expected: existing baseline + new tests (catalog loader 6, credential store 7, redaction 2, ccxt broker 6, factory 3, exchange routes 8, regen 1, dep smoke 2 = 35 new) all pass, full suite green, no regressions.

- [ ] **Step 10.2: Full UI test pass**

Run: `cd ~/Desktop/Projeler/proje/showMe/ui && npm test`

Expected: existing baseline + 5 new exchange-store + 6 new CONN = 11 new tests, full suite green.

- [ ] **Step 10.3: Sidecar build (PyInstaller --onedir)**

Run: `cd ~/Desktop/Projeler/proje/showMe && npm run sidecar:build 2>&1 | tail -30`

Expected: build completes; produces the `showme-backend` artifact under the standard path used by `tauri:build`. Verify ccxt's static_dependencies and keyring backends are in the bundle:

```bash
find ~/Desktop/Projeler/proje/showMe -name 'static_dependencies' -path '*ccxt*' | head -3
find ~/Desktop/Projeler/proje/showMe -name 'macOS*' -path '*keyring*' | head -3
```

If either is missing, revisit Task 1 Step 1.5.

- [ ] **Step 10.4: Tauri release build**

Run: `cd ~/Desktop/Projeler/proje/showMe && npm run tauri:build 2>&1 | tail -20`

Expected: signed `.app` produced. Note the new CFBundleVersion timestamp.

- [ ] **Step 10.5: Deploy to /Applications**

Run: `cd ~/Desktop/Projeler/proje/showMe && npm run deploy:app 2>&1 | tail -10`

Expected: `/Applications/showMe.app` updated.

- [ ] **Step 10.6: Launch + live smoke**

```bash
open /Applications/showMe.app
sleep 6
# 1. Sidecar reachable
curl -s -H "X-ShowMe-Token: $(ps -E -A | grep showme-backend | head -1 | grep -oE 'SHOWME_AUTH_TOKEN=[^ ]+' | cut -d= -f2)" \
     "http://127.0.0.1:$(lsof -i -P -n | grep showme-backend | grep LISTEN | head -1 | awk -F: '{print $NF}' | awk '{print $1}')/api/exchange/catalog" \
     | python3 -c "import sys, json; d=json.load(sys.stdin); print(f'catalog entries: {len(d)}'); assert len(d) >= 100"
# 2. Click through: open CONN, search "binance", confirm row appears
# 3. (Manual) add a real read-only Binance key in the UI; observe Test → ok; observe a real position list at /api/broker/positions?name=binance:<id>; delete the credential.
```

Expected:
- step 1 prints `catalog entries: NNN` where NNN >= 100
- step 2 visible in the app window
- step 3 manual verification: read-only key → positions list (or empty array, not 5xx) → delete sweeps the broker out of the registry.

If step 3 fails, do not proceed — debug the route returning a 5xx by inspecting `~/Library/Logs/showMe/sidecar.log`.

- [ ] **Step 10.7: Capture acceptance screenshot**

Take a screenshot of the running app with CONN pane open + Binance row selected + form visible. Save to `/tmp/conn-pane-live.png`. Reference in the final commit message.

- [ ] **Step 10.8: Final wrap commit (memory + closing note)**

Update `~/.claude/projects/-Users-nazmi-Desktop/memory/MEMORY.md` to insert a new line under the showMe section:

```
- [showMe sub-system A SHIPPED](showme_subsystem_a.md) — 2026-05-21: multi-exchange credential vault + CcxtBroker + CONN pane; 11 new tests + 6 UI tests; native build deployed with `ccxt` and `keyring` bundled
```

And create the body file `~/.claude/projects/-Users-nazmi-Desktop/memory/showme_subsystem_a.md`:

```markdown
---
name: showme-subsystem-a
description: showMe multi-exchange portfolio foundation (sub-system A of 11) SHIPPED 2026-05-21
metadata:
  type: project
---

Sub-system A shipped 2026-05-21:

* Deps: `ccxt`, `keyring` (hard).
* New: `brokers/ccxt_broker.py`, `brokers/credential_store.py`,
  `brokers/catalog/{__init__.py, loader.py, exchanges.yml}`,
  `server_routes/exchange.py`, `scripts/build_exchange_catalog.py`,
  `ui/src/lib/exchange-store.ts`, `ui/src/functions/CONN.tsx`.
* Modified: `brokers/factory.py` (dynamic registration + replay),
  `brokers/__init__.py`, `server_routes/__init__.py`,
  `server.py` (boot replay), `app_paths.py` (`credentials_path()`),
  `pyproject.toml`, `showme-backend.spec`, `registry.tsx`,
  `workspace.ts`.
* Tests: 35 new backend + 11 new UI.
* Frozen contracts (don't break in later sub-systems):
  * Keychain service name: `com.showme.exchanges`
  * Broker name format: `{exchange_id}:{credential_id}`
  * Permission tuples: `("read",)` / `("read", "trade")`
  * Credential index: `$SHOWME_HOME/credentials.json`
  * `SHOWME_CREDENTIAL_BACKEND=memory` selects in-memory backend
* Out of scope (next sub-systems): PORT integration (B), Order UI (C),
  bot runner (D), strategy editor (E), indicator depot (F).

**Why:** see spec at `docs/superpowers/specs/2026-05-21-multi-exchange-portfolio-foundation-design.md`.

**How to apply:** any future sub-system that needs broker access goes
through `get_broker("{exchange_id}:{credential_id}")`. Adding a new
adapter family means: extend `factory.register_credential` with a new
`adapter:` branch + add catalog YAML entries — no route changes.

Related: [[showme_exchanges_isolate_tbv3]], [[feedback_decisive]],
[[feedback_native_rebuild]].
```

Then commit:

```bash
touch /tmp/.opsera-pre-commit-scan-passed
cd ~/Desktop/Projeler/proje/showMe
# (no showMe files to add for this step — memory lives outside the repo)
git log --oneline -10  # sanity check: this sprint's commits visible
```

---

## Self-review notes

**Spec coverage:**
- §3 (chosen approach) → tasks 1, 5
- §4.1 (catalog) → tasks 2, 3
- §4.2 (credential vault) → task 4
- §4.3 (CcxtBroker) → task 5
- §4.4 (factory extension) → task 6
- §4.5 (routes) → task 7
- §4.6 (CONN pane) → tasks 8, 9
- §4.7 (sidebar wiring) → task 9
- §5 (data flow) → covered by tasks 6, 7 (boot replay), 9 (UI)
- §6 (permission model) → task 5 (adapter), task 7 (route gating)
- §7 (error handling) → tasks 4 (redaction), 5 (BrokerError wrapping), 7 (HTTP status mapping)
- §8 (testing) → every task includes tests
- §9 (out of scope) → nothing leaked into tasks
- §10 (build sequence) → tasks ordered to match the spec's sequence
- §11 (acceptance criteria) → A1 covered by task 10.1/10.2, A2 by task 10.6 step 2, A3 by task 10.6 step 3, A4 by task 5.1 (`test_submit_order_blocked_on_read_only_credential`), A5 by task 7.1 (`test_delete_credential_removes_broker`), A6 by task 4.6 (`test_add_does_not_log_secrets`), A7 by task 10.3.
- §12 (risks) → mitigated by task 1.5 (ccxt datas), task 4.4 (keyring backend), task 9.3 (virtualisation kept out of v1; the list uses native `overflow` because for ~150 entries that's fine — if perf-flagged later, swap in `@tanstack/react-virtual`).
- §13 (open questions) → deferred, not blockers.

**Placeholder scan:** every code step has the real code. No TBD / TODO / "implement later" / "similar to Task N".

**Type consistency:**
- `CredentialRecord` shape consistent across tasks 4, 6, 7, 8.
- `CcxtBroker` constructor signature (`exchange_id`, `credentials`, `permissions`, `ccxt_module`) consistent across tasks 5, 6.
- Permission tuples `("read",)` and `("read", "trade")` used uniformly.
- Broker name format `{exchange_id}:{credential_id}` consistent across tasks 6, 7, 10.
- Route paths `/api/exchange/{catalog,credentials,credentials/{id},credentials/{id}/test}` consistent across tasks 7, 8, 9.

No drift detected.
