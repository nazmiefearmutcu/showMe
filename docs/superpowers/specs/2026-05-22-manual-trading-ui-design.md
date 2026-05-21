# Manual trading UI (Sub-system C)

**Date:** 2026-05-22
**Project:** showMe
**Depends on:** A (broker /api/broker/orders POST/DELETE), B (PORT aggregate render)
**Status:** Design — auto-approved per `feedback_decisive`

## 1. Goal

Let the user place and cancel orders manually from within the PORT pane via the credentials that have `("read", "trade")` permission. Honor the safety contract A established at the adapter layer (read-only keys reject writes with HTTP 403).

## 2. Approach

Backend already exposes `POST /api/broker/orders` and `DELETE /api/broker/orders/{id}` (A's `server_routes/broker.py`). C is purely a UI integration:

* New `<OrderTicket>` component embedded inside each `<CredentialGroup>` rendered for a `("read","trade")` credential. Inline (collapsed by default), expanded by a "Trade" button.
* `<OrderTicket>` form: symbol (free text or position-selected), side (Buy/Sell), order_type (Market/Limit/Stop/StopLimit), quantity, limit_price (conditional), stop_price (conditional), time_in_force (DAY/GTC/IOC/FOK), notes (client_order_id).
* Confirmation modal: requires re-typing the credential's `account_label` AND clicking the "Place order" button. Cancel button anywhere closes the modal.
* Open-orders list per group, fetched via `usePortfolioStore.includeOrders=true` (B already wires this). Each open order has a "Cancel" button → `DELETE /api/broker/orders/{id}?name={broker_name}`.
* "Close position" button per non-zero position row: posts an opposite-side market order at the position's full quantity. Uses the same confirmation modal.
* New zustand store `useTradingStore` (separate from portfolio-store) for ticket state, submission status, and pending confirmation.

## 3. Components

### 3.1 `ui/src/lib/trading-store.ts` (new)

```ts
interface TradingState {
  ticket: { credentialId, symbol, side, orderType, quantity, limitPrice?, stopPrice?, tif, notes };
  pendingConfirm: null | { kind: "submit" | "close" | "cancel"; broker_name; payload };
  submitting: boolean;
  lastResult: { ok: boolean; orderId?: string; error?: string } | null;
}
```

Actions: `openTicket(credentialId)`, `setTicketField(k, v)`, `submitOrder()`, `cancelOrder(broker_name, order_id)`, `closePosition(broker_name, symbol, qty)`, `confirm(confirmLabel)`, `dismissConfirm()`.

All write actions go via `sidecarFetch` to the existing endpoints. After success, calls `usePortfolioStore.getState().loadPortfolio()` to refresh.

### 3.2 `ui/src/functions/PORT/OrderTicket.tsx` (new, ~150 lines)

* Compact form with the 8 fields above.
* `account_label` confirmation field for the modal — only "Place" button enables when match.
* Result strip: shows `lastResult` (id on success, error on failure).
* Listens to `useExchangeStore.credentials` to check permissions; renders disabled placeholder + tooltip ("Bu bağlantı salt-okuma; CONN'dan trade iznine yükselt") when `permissions` lacks `"trade"`.

### 3.3 `ui/src/functions/PORT.tsx` (modified)

* Inside `<CredentialGroup g={...}>`, when `g.permissions.includes("trade")`, render the `<OrderTicket credentialId={g.credential_id} />` collapsible component.
* Each `position` row gains a "Close" button (only when group has trade perm) that calls `closePosition` action.
* Each `order` row (when `includeOrders=true`) gains a "Cancel" button.

### 3.4 Backend (no changes)

`POST /api/broker/orders` body shape (existing, from A T7 `_models.OrderRequest`):
```json
{
  "broker": "binance:abc123",
  "symbol": "BTC/USDT",
  "side": "buy",
  "quantity": 0.01,
  "order_type": "market",
  "time_in_force": "GTC",
  "limit_price": null,
  "stop_price": null,
  "notes": ""
}
```

Returns `{ broker, order: { id, status, ... } }`. 400 on validation, 403 on permission, 502 on transport.

`DELETE /api/broker/orders/{order_id}?name={broker_name}` — returns `{ broker, ok: bool }`.

## 4. Safety

* **Read-only credentials cannot reach the order form** — the form is conditionally rendered, AND the adapter-level enforcement from A (CcxtBroker `_require("trade")`) is the final defense. Both layers.
* **Confirmation modal** requires re-typing the credential's `account_label`. Same UX as A's privilege escalation — friction proportional to blast radius.
* **No order placement on enter**: the form's submit button is the only path; pressing Enter in any input does NOT auto-submit.
* **Audit log**: every order submission logs `LOG.info("order placed: %s", _scrub(...))` server-side (already in A's broker.py).

## 5. Out of scope

* Bracket orders / OCO (defer)
* Order routing logic (defer to D bot runner)
* Position sizing helpers (defer)
* Margin / leverage controls (some exchanges expose; defer per-exchange detail)
* Real-time WebSocket order updates (B is poll-based; C inherits)
* Tax / cost-basis attribution

## 6. Acceptance criteria

* C1. `useTradingStore` exports the required actions + state shape; vitest covers submit + cancel + close.
* C2. `<OrderTicket>` renders only for credentials with `trade` permission.
* C3. Submission requires the confirmation modal with re-typed `account_label`.
* C4. Successful POST → `loadPortfolio()` refresh → form clears.
* C5. Failed POST → error displayed inline, form unchanged.
* C6. Position close + order cancel work via the existing endpoints.
* C7. Full backend + UI tests green; ≥ 4 new vitest cases.

## 7. Build sequence

1. `trading-store.ts` + tests
2. `<OrderTicket>` component + tests
3. PORT.tsx wiring (Close button + Cancel button + OrderTicket render)
4. Live smoke + native rebuild + memory note
