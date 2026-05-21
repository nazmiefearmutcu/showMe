# Multi-exchange portfolio foundation (Sub-system A)

**Date:** 2026-05-21
**Project:** showMe
**Sub-system:** A of {A, B, C, D, E, F, G, H, I, J, K} (see Decomposition section)
**Status:** Design — pending user approval before writing-plans

## 1. Goal

Let showMe connect to **any** exchange the user already has a portfolio on, store credentials safely, and expose a uniform `BaseBroker` instance per saved credential so every downstream sub-system (read portfolio, manual trading, bot runner, etc.) talks to one shape regardless of vendor.

> Direct quote from user: "bütün borsalar derken gerçekten bütün borsaları kast ettim … token girme ekranına bir arama özelliği de koy."

This sub-system is **infrastructure only**: it does not display portfolios (Sub-system B), submit orders from the UI (Sub-system C), or run bots (Sub-system D). It opens the door for those.

## 2. Decomposition reminder

The full user request maps to 11 sub-systems across 6 tiers (see brainstorming chat). Sub-system A is the foundation; all writes/automation are gated by it. **TBV3 is explicitly out of scope** in this and every downstream sub-system — confirmed by user 2026-05-21.

| # | Sub-system | Depends on |
|---|---|---|
| **A** | **Multi-exchange credential vault + adapter registry (this doc)** | — |
| B | Read-only portfolio view | A |
| C | Manual trading UI | A |
| D | Strategy bot runner | A, E |
| E | Strategy editor | F |
| F | Indicator depot | — |
| G | Template bot library | E, F, K |
| H | Bot supervision | D |
| I | Cumulative performance | D |
| J | Bot dev assistant | E, K |
| K | GitHub/HF integrations | — |

## 3. Chosen approach (auto-picked per user directive)

**Approach 1 — ccxt for crypto + `BaseBroker` extensions for traditional brokers.**

* Crypto coverage: import [`ccxt`](https://github.com/ccxt/ccxt) (MIT, ~120+ exchanges). One adapter class `CcxtBroker(BaseBroker)` parametrised by `exchange_id` (`binance`, `bybit`, `okx`, `kraken`, …) handles all of them by calling ccxt's unified API (`fetch_balance`, `fetch_positions`, `fetch_open_orders`, `create_order`, `cancel_order`).
* Traditional brokers: hand-roll one `BaseBroker` adapter per vendor (Alpaca already exists; IBKR, Tradier, OANDA, Saxo, IG come in later sprints — A only commits to the framework, not to writing each adapter).
* Discovery: a curated **exchange catalog** YAML (~150 entries) drives the Connect-Exchange UI's search and tells the factory which adapter class + parameter set to instantiate.

**Why this over the alternatives:**

* **vs hand-rolling every exchange** — ccxt gives 120+ crypto exchanges from one adapter class. Hand-rolling is 6–12 months of full-time work for the same surface.
* **vs three SDKs** (ccxt + Alpaca + a third) — structurally the same as Approach 1 but blurs the line between "crypto adapter" and "traditional adapter". One class per asset family is cleaner.

`ccxt` is bundled as a hard dependency (the user explicitly asked to leverage GitHub heavily, this is the canonical GitHub library for the problem). `keyring` is added as a hard dependency for the credential vault.

## 4. Components

### 4.1 Exchange catalog
**File:** `backend/showme/brokers/catalog/exchanges.yml`

YAML list. Each entry:

```yaml
- id: binance                       # stable, lowercase, lookup key
  display_name: Binance
  aliases: [binance.com, binance-spot]
  asset_classes: [spot, futures, options, margin]
  regions: [global]                 # for region filter chip
  adapter: ccxt                     # which adapter class instantiates this
  ccxt_id: binance                  # passed to ccxt.binance(...)
  requires:                         # credential fields the UI must collect
    - api_key
    - api_secret
  optional: []
  capabilities:                     # what the adapter supports for this exchange
    fetch_balance: true
    fetch_positions: true
    fetch_open_orders: true
    create_order: true
    cancel_order: true
  notes: "Bind API key to your IP for safety; enable spot+futures read for portfolio viewing."

- id: alpaca-live
  display_name: Alpaca (live)
  aliases: [alpaca]
  asset_classes: [equity, crypto, options]
  regions: [us]
  adapter: alpaca
  requires: [api_key, api_secret]
  optional: []
  capabilities:
    fetch_balance: true
    fetch_positions: true
    fetch_open_orders: true
    create_order: true
    cancel_order: true

- id: okx
  ...
  requires: [api_key, api_secret, passphrase]  # OKX needs passphrase
```

Initial catalog: every exchange ccxt's registry exposes (auto-generated from `ccxt.exchanges`) + a small hand-curated section for traditional brokers. The auto-generated ccxt entries default `capabilities` from ccxt's own `.has` table and `requires` from ccxt's `.requiredCredentials`.

A small `scripts/build_exchange_catalog.py` regenerates the file from ccxt's metadata; CI fails if the file drifts from the regenerated form (so we don't hand-edit ccxt entries).

### 4.2 Credential vault
**File:** `backend/showme/brokers/credential_store.py`

```python
@dataclass(frozen=True)
class CredentialRecord:
    id: str                       # uuid4 hex
    exchange_id: str              # FK to catalog
    account_label: str            # user-supplied, e.g. "main", "tax-2026"
    permissions: tuple[str, ...]  # ("read",) or ("read", "trade")
    created_at: str
    # secret fields are NOT in this object — they live in the OS keychain
```

Backing store:

* **macOS keychain** via [`keyring`](https://github.com/jaraco/keyring) — service name `com.showme.exchanges`, account key `{exchange_id}:{credential_id}`. Stores a JSON blob `{api_key, api_secret, passphrase?}`.
* **Catalog** (non-secret metadata: `id`, `exchange_id`, `account_label`, `permissions`, `created_at`) stored in `~/Library/Application Support/showMe/credentials.json` so we can list saved connections without unlocking the keychain.
* **In-memory backend** for tests, selectable via `SHOWME_CREDENTIAL_BACKEND=memory` env var.

API:

```python
class CredentialStore:
    def list(self) -> list[CredentialRecord]: ...
    def get(self, credential_id: str) -> tuple[CredentialRecord, dict]:
        """(record, secrets dict). Raises KeyError if unknown."""
    def add(self, exchange_id: str, account_label: str,
            secrets: dict, permissions: tuple[str, ...]) -> CredentialRecord: ...
    def delete(self, credential_id: str) -> bool: ...
    def update_permissions(self, credential_id: str,
                            permissions: tuple[str, ...]) -> CredentialRecord: ...
```

Secrets never get logged. The store scrubs any `api_key`/`api_secret`/`passphrase` substring from exception messages before re-raising.

### 4.3 `CcxtBroker` adapter
**File:** `backend/showme/brokers/ccxt_broker.py`

```python
class CcxtBroker(BaseBroker):
    name = "ccxt"  # overridden per instance to "{ccxt_id}:{credential_id}"

    def __init__(self, *, exchange_id: str, credentials: dict,
                 permissions: Sequence[str], ccxt_module=None):
        # ccxt_module injectable for tests; default = real ccxt.async_support
        ...

    async def account(self) -> dict[str, Any]:
        bal = await self._ex.fetch_balance()
        return self._normalise_account(bal)

    async def list_positions(self) -> list[Position]:
        rows = await self._ex.fetch_positions()
        return [self._to_position(r) for r in rows if float(r.get("contracts") or 0) != 0]

    async def submit_order(self, *, ...) -> Order:
        self._require("trade")  # raises NotSupported on read-only key
        raw = await self._ex.create_order(...)
        return self._to_order(raw)

    # cancel_order, close_position, list_orders similar
```

* `_require(perm)` checks `perm in self._permissions`; if missing, raises `NotSupported("credential {id} lacks {perm} permission")`. Defends UI bugs from sneaking a trade call onto a read-only key.
* Normalisation helpers (`_to_order`, `_to_position`, `_normalise_account`) map ccxt's unified shape to showMe's existing `Order` / `Position` dataclasses.
* Async ccxt is used (`ccxt.async_support`) so we stay non-blocking.

### 4.4 Factory extension
**File:** `backend/showme/brokers/factory.py` (modified)

* On import, factory loads the catalog YAML once.
* `register_credential(record, store)` dynamically registers a broker named `"{exchange_id}:{credential_id}"` whose factory function builds the right adapter (looks up `adapter` in catalog → instantiates `CcxtBroker(...)` or `AlpacaBroker(...)`).
* On startup, sidecar iterates `store.list()` and calls `register_credential` for each, so the existing `/api/broker/*` routes work with the new names without changes.
* `get_broker(None)` continues to default to `paper` for backward compat.

### 4.5 Routes
**File:** `backend/showme/server_routes/exchange.py` (new)

* `GET  /api/exchange/catalog` — full catalog (id, display_name, asset_classes, regions, capabilities). Used by the Connect UI's search.
* `GET  /api/exchange/credentials` — list saved `CredentialRecord`s (no secrets).
* `POST /api/exchange/credentials` — body `{exchange_id, account_label, secrets, permissions}`. Validates against catalog `requires`, saves to vault, registers in factory, returns the new record.
* `DELETE /api/exchange/credentials/{credential_id}` — remove from vault and factory.
* `PATCH /api/exchange/credentials/{credential_id}` — update `permissions` or `account_label` only.
* `POST /api/exchange/credentials/{credential_id}/test` — calls `broker.account()` once; returns `{ok, account?, error?}` for the UI's "Test connection" button.

Existing `/api/broker/*` routes are **unchanged** — they already accept `?name=` which now resolves to `"{exchange_id}:{credential_id}"`.

### 4.6 UI: Connect Exchange pane
**File:** `ui/src/functions/CONN.tsx` (new)

Layout (single pane, ShowMe design system):

* **Top:** search input with placeholder "Borsa ara…". Filters the catalog list as the user types (debounced 150ms). Filter chips below: `Crypto | Equity | FX | Futures | Options` × `Global | US | EU | Asia`.
* **List (left half):** virtualised list of exchanges. Each row: a 2-char initials disc (e.g. "BI" for Binance, "OK" for OKX — `display_name` first two letters), display_name, asset_class chips, "Bağlı: N hesap" badge if user has credentials. No bundled exchange logos in v1 (trademark/legal cleanliness; logos can be revisited in a later sub-system once an asset pipeline exists).
* **Detail (right half):** when an exchange is selected:
  * Existing connections (if any): table of `{account_label, permissions, last test}` with row-level Test/Delete buttons.
  * "Yeni bağlantı ekle" form: dynamic fields based on `requires`/`optional` from the catalog entry. Permission toggle (default: "Sadece okuma"; toggle to "Okuma + işlem" with red warning). Submit button posts to `/api/exchange/credentials`.
  * Connection-test result inline; if `error`, surface the exchange's message verbatim (no rewriting — ccxt error strings are user-actionable).

Registered in `ui/src/functions/registry.tsx` as `CONN: CONNPane`. Added to the sidebar under a new "Connections" group.

State management follows showMe's existing pattern (zustand stores in `ui/src/lib/`): a new `exchange-store.ts` exposes `catalog`, `credentials`, `selected_exchange_id`, plus async actions `loadCatalog()`, `loadCredentials()`, `saveCredential()`, `deleteCredential()`, `testCredential()`. Each action calls the sidecar over the existing `X-ShowMe-Token` auth header and updates store slices on success. Secrets typed into the form are kept in component-local state only; never written to the store, never persisted to disk on the UI side. The catalog list uses `@tanstack/react-virtual` (already in `package.json`) for virtualisation.

### 4.7 Sidebar entry
**File:** `ui/src/lib/sidebar.ts` (existing pattern)

Add a `CONN` entry under a new "Connections" group. No new icon system — uses existing pictogram.

## 5. Data flow

### Adding a credential
```
User clicks "Connect Exchange" in sidebar
  → CONN pane mounts
  → GET /api/exchange/catalog → renders list
  → User searches "binance" → list filters → selects Binance
  → User enters api_key/api_secret/passphrase, picks permissions, names account "main"
  → POST /api/exchange/credentials {exchange_id, account_label, secrets, permissions}
  → sidecar:
      a) validates exchange_id in catalog
      b) validates `secrets` matches catalog.requires
      c) pings exchange (calls broker.account() once) to fail fast on bad keys —
         can be skipped via body `skip_test: true` for offline-creation workflows
      d) stores secrets in macOS Keychain
      e) appends record to credentials.json
      f) registers in broker factory under "binance:{uuid}"
  → returns CredentialRecord
  → UI invalidates credentials query → row appears
```

### Using a credential (downstream sub-system)
```
Sub-system B (read portfolio) calls
  GET /api/broker/positions?name=binance:abc123
    → existing broker_positions route
    → get_broker("binance:abc123")
    → CcxtBroker reads cached credentials, calls ccxt.binance().fetch_positions()
    → returns [Position, ...] normalised
```

### Restart
```
sidecar boot
  → loads credentials.json (metadata only)
  → for each record: ask Keychain for secret, register adapter in factory
  → factory now has paper + alpaca-paper + binance:{uuid} + bybit:{uuid} + ...
```

## 6. Permission model

Per-credential `permissions: tuple[str, ...]`:

* `("read",)` — only `account`, `list_positions`, `list_orders` work. Write methods raise `NotSupported`.
* `("read", "trade")` — full surface.

Default at create-time is `("read",)`. UI shows a red explicit-confirm toggle to upgrade to `("read", "trade")`. Privilege escalation (read → read+trade on an already-saved credential) requires the user to **re-type the credential's `account_label`** in a confirmation input before the `PATCH` is sent — small friction by design, defense against accidental clicks.

`NotSupported` flows up as HTTP 403 from `/api/broker/orders` etc., with `detail` naming the missing permission. UI catches and surfaces an actionable "this connection is read-only; reconnect with trade permission to place orders" message.

The user is also asked at credential-creation time to **also** restrict the API key scope **on the exchange side** (Binance "Enable Reading" only, vs "Enable Spot & Margin Trading") — defense in depth.

## 7. Error handling

| Failure mode | Surface | UX |
|---|---|---|
| Catalog YAML missing/corrupt | startup fatal log + `/api/exchange/catalog` returns 503 | Pane shows "Borsa kataloğu yüklenemedi" + retry |
| Keychain unavailable (CI, sandboxed test) | startup falls back to in-memory store with WARNING log | header chip says "Credential vault: in-memory (test mode)" |
| `keyring.errors.PasswordDeleteError` etc. | `CredentialStore` wraps in `BrokerError("vault: <reason>")` at the boundary so the rest of the stack never sees raw `keyring` exceptions | toast "Kimlik bilgisi silinemedi: …" |
| Exchange API rate-limit | ccxt's `RateLimitExceeded` mapped to `BrokerError` 429 | toast "Borsa rate limit'i: 60s sonra tekrar dene" |
| Exchange auth failure | ccxt's `AuthenticationError` mapped to `BrokerError` 401 | UI marks connection as "Invalid keys, retest" |
| Read-only key + trade call | `NotSupported` 403 | toast as in §6 |
| Catalog has exchange but ccxt doesn't | `KeyError` at factory time | startup log, exchange hidden from catalog response |

All credentials/secrets are scrubbed from log lines via a `RedactingFormatter` filter that masks anything matching `api_key`/`api_secret`/`passphrase` keys in dicts. No exceptions: even `repr(record)` returns `CredentialRecord(id=..., secrets=<redacted>)`.

## 8. Testing

* `tests/test_credential_store.py` — memory backend, CRUD, redaction, multi-account-per-exchange, permissions upgrade workflow.
* `tests/test_ccxt_broker.py` — `ccxt_module` injected as `MagicMock`; assert correct method calls, payload shape, permission enforcement, normalisation correctness for a handful of representative exchanges (binance, okx with passphrase, kraken).
* `tests/test_exchange_routes.py` — FastAPI TestClient against `/api/exchange/*`, including the "secrets never appear in response body" assertion, and that `POST /credentials` calls `broker.account()` before saving (so bad keys fail fast).
* `tests/test_catalog_regen.py` — runs `scripts/build_exchange_catalog.py --check` to fail CI if `exchanges.yml` was hand-edited away from the regenerated form for ccxt entries.
* `ui/src/functions/CONN.test.tsx` — vitest + Testing Library. Search filtering, chip filters, form validation, error rendering, "test connection" loading state, permission toggle red-warning copy.

Acceptance: All new tests added under the same pattern as existing showMe tests (`pytest-asyncio` for backend, vitest for UI). Full suite stays at 100% pass rate (current baseline: 428 + S07 57 owned + S12 +13 + small recent adds — must not regress).

## 9. Out of scope (this sub-system)

* Portfolio aggregation across exchanges (→ Sub-system B)
* Order placement from UI (→ Sub-system C)
* Bot runners (→ Sub-system D)
* Indicators / strategies (→ Sub-systems E, F)
* Streaming/WebSocket price feeds from new exchanges (existing `quotes.py` / `streams.py` not touched in A)
* iOS/Android — desktop only as today
* Migration of existing `alpaca-paper` env-var credentials into the new vault — out of scope; the env-var path keeps working in parallel

## 10. Build sequence inside Sub-system A

Suggested ordering for the writing-plans phase (each step a discrete task, can be parallelised where indicated):

1. **Dep bump** — add `ccxt`, `keyring` to `pyproject.toml`; `pip install` smoke; PyInstaller spec verifies ccxt's vendored ABI files bundle correctly.
2. **Catalog generator** — `scripts/build_exchange_catalog.py` + initial `exchanges.yml` + CI check.
3. **Credential store** — `credential_store.py` + keyring + memory backend + unit tests. *(Parallel with 2.)*
4. **`CcxtBroker`** — adapter + unit tests with mocked ccxt. *(Parallel with 2 and 3 after step 1.)*
5. **Factory extension** — dynamic registration from store; tests covering startup-replay.
6. **Routes** — `/api/exchange/*`; route tests.
7. **UI: CONN pane** — component + state hooks + tests + storybook entry. *(Parallel with 5 and 6 once route shapes are stable.)*
8. **Sidebar wiring + registry.tsx** — small.
9. **Live smoke** — connect a real read-only Binance key, hit `/api/broker/positions`, screenshot in PORT for proof; then delete the key. *(Per [[feedback_live_test]].)*
10. **Native rebuild + deploy** — per [[feedback_native_rebuild]]. New CFBundleVersion, signed sidecar `--onedir`.

Parallelism: After step 1 lands, an agent fleet can take steps 2/3/4 in parallel worktrees; another fleet handles 6/7 in parallel once 5 is on `main`. Total sub-system A expected to be ~3–4 implementation days with parallel agents.

## 11. Acceptance criteria for Sub-system A

A1. From a fresh checkout, `pytest backend/tests` is green, `npm test` is green.
A2. From a fresh native build, opening the app, clicking the new "Connections" group → "Connect Exchange" loads a pane that lists ≥120 exchanges, with a working search that filters by name, and chip filters that filter by asset class and region.
A3. Adding a read-only Binance key via the UI persists across app restart, shows as "Connected", and `curl /api/broker/positions?name=binance:<id>` returns an empty-or-real positions list (no 5xx).
A4. Attempting `curl -X POST /api/broker/orders` against a read-only credential returns HTTP 403 with `detail` naming the missing `trade` permission.
A5. Deleting the credential via UI removes it from both Keychain and `credentials.json`, and `/api/broker/positions?name=binance:<id>` then returns 404 with the existing "unknown broker" error shape.
A6. No credential, key, or secret string ever appears in any log line (verified by a dedicated test that exercises the redacting formatter).
A7. `ccxt` and `keyring` are bundled into the `--onedir` PyInstaller spec; the production app does not require an internet install of dependencies.

## 12. Risks

* **ccxt vendored data files**: ccxt ships large JS files inside the Python package; PyInstaller's hidden-import heuristics sometimes miss them. Mitigation: explicit `datas` entry in `showme-backend.spec` + the smoke test in step 1.
* **Keychain prompt UX**: macOS may prompt the user "showMe wants to access your keychain" on first access per process. Acceptable but the UI should explain it ahead of time.
* **Catalog size in pane**: 150+ rows is fine virtualised; without virtualisation the search box would feel laggy. The design specifies virtualisation up front.
* **Exchange-specific quirks**: some exchanges (Coinbase, Kucoin sub-accounts) need extra fields. Mitigated by `requires`/`optional` in the catalog and the dynamic form. If a user reports a gap, fix is catalog YAML + one extra field — no code change.
* **Read-only key actually has trade rights** (user lied to the permission toggle): UI cannot enforce this; the **exchange-side** key scope is the only real defense. Documented in the form's helper text.

## 13. Open questions (not blockers)

These are deferred to later sub-systems; calling them out so the writing-plans phase doesn't trip:

* (Sub-system B) Does PORT.tsx aggregate across all saved credentials by default, or show one at a time with a selector? — answer when B is brainstormed.
* (Sub-system D) Whether a bot can be bound to multiple credentials (multi-leg arbitrage) or only one — answer at D.
* (Cross-cutting) Whether secrets should be redacted from showMe's audit log file (separate from runtime logs) — answer at C.
