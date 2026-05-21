# Read-only portfolio aggregation (Sub-system B)

**Date:** 2026-05-22
**Project:** showMe
**Sub-system:** B of {A, B, C, D, E, F, G, H, I, J, K} (per original decomposition)
**Depends on:** A (SHIPPED 2026-05-22, see [SUBSYSTEM_A.md](../../backend/SUBSYSTEM_A.md))
**Status:** Design — auto-approved per user's `feedback_decisive` directive

## 1. Goal

Aggregate live read-only portfolio data from every credential saved in the vault (built by A), expose it via a new fan-out route, and render it inside the existing `PORT` pane — fulfilling the user's original Turkish ask: "gerçek portföyü hakkında bilgileri uygulamanın ilgili olan fonksiyonlarından alabilmeli".

This sub-system performs **NO** writes (no order placement, no position close). It only consumes A's `get_broker(...)` to read `account()`, `list_positions()`, and `list_orders()`.

## 2. Chosen approach

**Backend fan-out + UI aggregation.**

* A new route `GET /api/portfolio/aggregate?include_orders=bool` iterates every dynamic credential currently registered in the factory (`factory._DYNAMIC`), invokes `broker.account()` + `broker.list_positions()` concurrently via `asyncio.gather`, and returns a unified payload.
* The existing `PORT.tsx` pane gains a top header showing aggregate equity, plus per-credential row groups under it. The current Alpaca-paper layout becomes one possible row group among many.
* A 30-second LRU cache keyed on `(credential_id, "positions" | "account" | "orders")` smooths over rapid re-renders and rate-limits the underlying exchanges.

## 3. Components

### 3.1 New route — `backend/showme/server_routes/portfolio_aggregate.py`

* `GET /api/portfolio/aggregate?include_orders=false&credential_ids=<csv>`
  * No body. Optional query params.
  * Response shape:
    ```json
    {
      "as_of": "2026-05-22T10:00:00Z",
      "groups": [
        {
          "credential_id": "abc123",
          "exchange_id": "binance",
          "account_label": "main",
          "permissions": ["read"],
          "account": { "cash": 100, "equity": 100, "buying_power": 100, "currency": "USDT", "raw": {} },
          "positions": [ { "symbol": "BTC/USDT", "side": "buy", "quantity": 0.5, ... } ],
          "orders": [],
          "error": null
        },
        { "credential_id": "...", "error": "rate limit: try again in 60s", ... }
      ],
      "totals": { "equity_by_currency": { "USDT": 250, "USD": 14000 } }
    }
    ```
  * Each group surfaces its own `error` field — one stale broker doesn't 5xx the whole route.
  * `credential_ids` filter lets the UI request a subset (e.g., user clicks "show only Binance").

### 3.2 Aggregation logic — `backend/showme/portfolio_aggregate.py`

* `async def aggregate(credential_ids: list[str] | None, include_orders: bool) -> dict` — pure-Python module that the route handler calls.
* Iterates `factory._DYNAMIC` keys (filtered by `credential_ids` when provided).
* For each: spins up an `asyncio.Task` for `broker.account()` and (in parallel) `broker.list_positions()` + (conditional) `broker.list_orders(status="open", limit=50)`.
* Uses a single `asyncio.gather(*all_tasks, return_exceptions=True)` so partial failures don't break the whole sweep.
* Per-credential exception → that group's `error` field; other groups still surface their data.
* Optional in-process cache: `_CACHE: dict[tuple[str, str], tuple[float, Any]]` with 30-second TTL. Cache invalidated by `unregister_credential` (we hook into factory).

### 3.3 Factory hook — `backend/showme/brokers/factory.py`

* Tiny addition: a module-level `_INVALIDATION_HOOKS: list[Callable[[str], None]] = []` list and an `_invalidate(credential_id)` helper that `unregister_credential` calls after popping. The aggregation module registers its cache-clear function into this list at import time.

### 3.4 UI — `ui/src/lib/portfolio-store.ts` (new)

* zustand store with state `groups: PortfolioGroup[]`, `totals: Record<string, number>`, `loading`, `error`, `lastFetchedAt`.
* Actions: `loadPortfolio(opts?)` calling `sidecarFetch<PortfolioPayload>("/api/portfolio/aggregate?...")`.
* Auto-refresh every 30s via `useEffect` interval inside the PORT pane (cleared on unmount).

### 3.5 UI — `ui/src/functions/PORT.tsx` (modified)

* Above the existing Bloomberg-grade layout, add:
  * **Aggregate header strip**: total equity (sum of all groups' equity, converted to USD if currency != USD via a static `STABLE_TO_USD = {"USDT": 1, "USDC": 1, "DAI": 1}` map; non-stable currencies show in native units with a chip), positions count, errors-count badge.
  * **Source filter**: chips showing each connected credential (`binance:main`, `kraken:cold`, etc.) with click-to-toggle. Pre-selects all by default.
* Below the header, render one `<CredentialGroup>` per non-error group, each containing:
  * Account totals row (cash/equity/currency).
  * Positions sub-table (symbol / side / qty / entry / mark / PnL / value).
  * Optional orders sub-table (only when `include_orders` chip is on).
* The legacy single-broker layout (which used `/api/broker/positions` directly) becomes a fallback for the `paper` broker only and renders inline as one more `<CredentialGroup>`.
* No connection saved → the pane shows a CTA card linking to `CONN` ("Connect an exchange in /CONN to see your portfolios").

### 3.6 USD conversion helper — `backend/showme/portfolio_aggregate.py` (same file)

* `_STABLE_TO_USD = {"USDT": 1.0, "USDC": 1.0, "DAI": 1.0, "BUSD": 1.0, "TUSD": 1.0}`.
* `_to_usd(amount, currency)` returns `(amount * _STABLE_TO_USD[currency], True)` if stable, else `(amount, False)` with a `converted=False` flag in the payload.
* For non-stable currencies we explicitly DO NOT call price oracles in B — that's a separate cross-cutting concern. The UI shows native units with a "≈ ?" tooltip.

## 4. Data flow

```
PORT.tsx mounts
  → loadPortfolio() in portfolio-store
  → GET /api/portfolio/aggregate
  → portfolio_aggregate.aggregate(None, false)
    → for each credential in factory._DYNAMIC:
        get_broker(name)
        gather(broker.account(), broker.list_positions())
    → returns {as_of, groups: [...], totals: {...}}
  → store updates → PORT re-renders header + per-group rows
  → 30s interval fires → repeat
```

## 5. Permission model

Every aggregation call is read-only. The route does NOT require `trade` permission. A `("read",)` credential is sufficient — and that's the recommended way to use this sub-system (the user binds a read-only API key on the exchange side).

## 6. Error handling

| Failure | Surface |
|---|---|
| One broker rate-limits | That group's `error` field, others succeed |
| Catalog missing for a credential | Aggregation skips it with WARNING; UI shows a "stale credential" pill |
| All brokers fail | Route still 200 with `groups: [...]` where every group has `error`; UI shows aggregate "0 exchanges responded" warning |
| Vault unreachable | 503 from the route; UI shows "credential vault unavailable" |
| Cache lookup miss | Falls through to live call; transparent |

## 7. Testing

* `backend/tests/test_portfolio_aggregate.py` — fixture-based: mock `_DYNAMIC` with 2 fake CcxtBroker-shaped objects + assert aggregate response shape; test partial failure (one broker raises); test caching (second call within 30s doesn't hit broker); test invalidation (after `unregister_credential`, cache key drops).
* `backend/tests/test_portfolio_aggregate_route.py` — TestClient against `/api/portfolio/aggregate` with the same fakes; cover `?credential_ids=` filter, `?include_orders=true`.
* `ui/src/lib/portfolio-store.test.ts` — mocks `sidecarFetch`, asserts load + filter actions.
* `ui/src/functions/PORT.test.tsx` — existing PORT tests should not regress; add a new test that renders PORT with two fake groups and asserts the aggregate header + per-group rows are present.

Acceptance: full backend suite + UI suite pass with the +N delta. Live smoke: with one real read-only Binance credential added in CONN, navigating to PORT shows the aggregated portfolio within 5 seconds.

## 8. Out of scope (this sub-system)

* Order placement from PORT (→ C)
* Bot-runner-aware filtering (→ D)
* Tax-lot or cost-basis tracking
* P&L attribution per trade
* Non-stable-currency USD conversion (defer to a price-oracle sub-system)
* Mobile / responsive layout (showMe is desktop-only)
* WebSocket live updates (B is poll-based; future sub-system can layer ws on top)

## 9. Frozen contracts (for sub-systems C-K)

* Route: `GET /api/portfolio/aggregate` — response shape above is locked
* Group object keys: `credential_id, exchange_id, account_label, permissions, account, positions, orders, error`
* UI store: `usePortfolioStore` exported from `ui/src/lib/portfolio-store.ts`
* Factory invalidation hook: `factory._INVALIDATION_HOOKS.append(fn)` — sub-system D's bot runner can register here too

## 10. Build sequence

1. Factory invalidation hook (additive, doesn't touch existing factory behavior)
2. `portfolio_aggregate.py` module with cache + tests
3. `server_routes/portfolio_aggregate.py` route + tests + wire into family register
4. `portfolio-store.ts` UI store + tests
5. `PORT.tsx` aggregate header + per-credential rows + tests
6. Live smoke + native rebuild + deploy

## 11. Acceptance criteria

* B1. `pytest backend/tests` green; `npm test` green (excluding pre-existing 9 unrelated failures).
* B2. `GET /api/portfolio/aggregate` with 0 saved credentials returns `{groups: [], totals: {}}` (not 5xx).
* B3. `GET /api/portfolio/aggregate` with 1 fake credential returns 1 group with non-null `account` and `positions`.
* B4. Partial failure (mock one broker to raise) → response 200 with one `error` group + one ok group.
* B5. 30-second cache: a second identical call within 30s doesn't hit the broker (verified by call counter on the fake).
* B6. Cache invalidation: after `unregister_credential(id)`, the cache for that id is gone.
* B7. PORT.tsx renders aggregate header + per-group rows; "Connect an exchange" CTA appears when zero credentials.

## 12. Risks

* **PORT.tsx is already 734 lines** ([memory](feedback)). Adding aggregate header risks pushing it over 1000. Mitigation: extract `<AggregateHeader>` and `<CredentialGroup>` into co-located sub-components in PORT.tsx, or split into `PORT/Header.tsx` / `PORT/Group.tsx`. Decide at implementation time.
* **Cache invalidation correctness**: a stale cache could show an old position list after a real-world position close. Mitigation: 30s TTL is a soft cap; user can hit a "Refresh" button (added in the header) for forced reload.
* **Concurrent fan-out exhausts exchange rate limits** when N credentials hit the same exchange (e.g., 3 Binance accounts). ccxt's `enableRateLimit: True` is on at the adapter level (T5), so requests serialize per exchange instance. Cross-instance no coordination — acceptable for v1 since N≤a handful per exchange in realistic use.
