# Manual trading UI (Sub-system C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Wire the existing `POST /api/broker/orders` + `DELETE /api/broker/orders/{id}` (from A) into the PORT pane as OrderTicket form + per-position Close + per-order Cancel buttons, gated by credential trade permission + confirmation modal.

**Architecture:** Pure UI. Spec at `docs/superpowers/specs/2026-05-22-manual-trading-ui-design.md`.

**Tech Stack:** React + TypeScript + zustand + vitest. No new deps.

---

## Tasks

### Task C1: trading-store (zustand) + tests

**Files:** `ui/src/lib/trading-store.ts` + `ui/src/lib/trading-store.test.ts`

- [ ] **Step C1.1:** Write `ui/src/lib/trading-store.test.ts`:

```typescript
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTradingStore } from "./trading-store";

vi.mock("./sidecar", () => ({ sidecarFetch: vi.fn() }));
vi.mock("./portfolio-store", () => ({
  usePortfolioStore: { getState: () => ({ loadPortfolio: vi.fn() }) },
}));

import { sidecarFetch } from "./sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  useTradingStore.setState({
    ticket: null, pendingConfirm: null, submitting: false, lastResult: null,
  });
  mock.mockReset();
});

describe("trading-store", () => {
  it("openTicket initializes ticket fields", () => {
    useTradingStore.getState().openTicket("abc-id", "binance:abc-id");
    const t = useTradingStore.getState().ticket;
    expect(t).not.toBeNull();
    expect(t!.credentialId).toBe("abc-id");
    expect(t!.brokerName).toBe("binance:abc-id");
    expect(t!.side).toBe("buy");
    expect(t!.orderType).toBe("market");
  });

  it("requestSubmit moves ticket into pendingConfirm", () => {
    useTradingStore.getState().openTicket("abc", "binance:abc");
    useTradingStore.getState().setTicketField("symbol", "BTC/USDT");
    useTradingStore.getState().setTicketField("quantity", 0.01);
    useTradingStore.getState().requestSubmit();
    expect(useTradingStore.getState().pendingConfirm?.kind).toBe("submit");
  });

  it("confirm sends POST to /api/broker/orders", async () => {
    mock.mockResolvedValueOnce({ broker: "binance:abc", order: { id: "o1", status: "new" } });
    useTradingStore.getState().openTicket("abc", "binance:abc");
    useTradingStore.getState().setTicketField("symbol", "BTC/USDT");
    useTradingStore.getState().setTicketField("quantity", 0.01);
    useTradingStore.getState().requestSubmit();
    await useTradingStore.getState().confirm("main");
    expect(mock.mock.calls[0][0]).toBe("/api/broker/orders");
    const init = mock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body.symbol).toBe("BTC/USDT");
    expect(body.quantity).toBe(0.01);
    expect(body.broker).toBe("binance:abc");
    expect(useTradingStore.getState().lastResult?.ok).toBe(true);
  });

  it("confirm surfaces backend error", async () => {
    mock.mockRejectedValueOnce(new Error("403 permission"));
    useTradingStore.getState().openTicket("abc", "binance:abc");
    useTradingStore.getState().setTicketField("symbol", "BTC/USDT");
    useTradingStore.getState().setTicketField("quantity", 0.01);
    useTradingStore.getState().requestSubmit();
    await useTradingStore.getState().confirm("main");
    expect(useTradingStore.getState().lastResult?.ok).toBe(false);
    expect(useTradingStore.getState().lastResult?.error).toContain("403");
  });

  it("cancelOrder sends DELETE", async () => {
    mock.mockResolvedValueOnce({ broker: "binance:abc", ok: true });
    await useTradingStore.getState().cancelOrder("binance:abc", "order-1");
    expect(mock.mock.calls[0][0]).toContain("/api/broker/orders/order-1");
    expect(mock.mock.calls[0][0]).toContain("name=binance");
    expect((mock.mock.calls[0][1] as RequestInit).method).toBe("DELETE");
  });

  it("closePosition stages confirmation with opposite-side market order", () => {
    useTradingStore.getState().closePosition("binance:abc", "BTC/USDT", "buy", 0.5);
    const pc = useTradingStore.getState().pendingConfirm;
    expect(pc?.kind).toBe("close");
    expect(pc?.payload.side).toBe("sell");
    expect(pc?.payload.quantity).toBe(0.5);
    expect(pc?.payload.order_type).toBe("market");
  });
});
```

- [ ] **Step C1.2:** Implement `ui/src/lib/trading-store.ts`:

```typescript
/**
 * Sub-system C: trading store. Wraps POST /api/broker/orders + DELETE.
 * Confirmation modal (pendingConfirm) gates every write.
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";
import { usePortfolioStore } from "./portfolio-store";

export type OrderSide = "buy" | "sell";
export type OrderType = "market" | "limit" | "stop" | "stop_limit";
export type TimeInForce = "day" | "gtc" | "ioc" | "fok";

export interface TicketState {
  credentialId: string;
  brokerName: string;            // "{exchange_id}:{credential_id}"
  symbol: string;
  side: OrderSide;
  orderType: OrderType;
  quantity: number;
  limitPrice: number | null;
  stopPrice: number | null;
  tif: TimeInForce;
  notes: string;
}

export interface PendingConfirm {
  kind: "submit" | "close" | "cancel";
  brokerName: string;
  accountLabel: string;          // for re-type confirmation; populated on open
  payload: Record<string, unknown>;  // ready-to-send body for the API
}

export interface LastResult {
  ok: boolean;
  orderId?: string;
  error?: string;
}

interface TradingStoreShape {
  ticket: TicketState | null;
  pendingConfirm: PendingConfirm | null;
  submitting: boolean;
  lastResult: LastResult | null;

  openTicket: (credentialId: string, brokerName: string, accountLabel?: string) => void;
  closeTicket: () => void;
  setTicketField: <K extends keyof TicketState>(k: K, v: TicketState[K]) => void;
  requestSubmit: (accountLabel?: string) => void;
  cancelOrder: (brokerName: string, orderId: string) => Promise<boolean>;
  closePosition: (brokerName: string, symbol: string, currentSide: OrderSide, quantity: number, accountLabel?: string) => void;
  confirm: (typedLabel: string) => Promise<void>;
  dismissConfirm: () => void;
}

const _DEFAULT_TICKET = (credentialId: string, brokerName: string): TicketState => ({
  credentialId, brokerName,
  symbol: "", side: "buy", orderType: "market", quantity: 0,
  limitPrice: null, stopPrice: null, tif: "gtc", notes: "",
});

function _ticketToBody(t: TicketState): Record<string, unknown> {
  return {
    broker: t.brokerName,
    symbol: t.symbol,
    side: t.side,
    quantity: t.quantity,
    order_type: t.orderType,
    time_in_force: t.tif,
    limit_price: t.orderType === "limit" || t.orderType === "stop_limit" ? t.limitPrice : null,
    stop_price: t.orderType === "stop" || t.orderType === "stop_limit" ? t.stopPrice : null,
    notes: t.notes,
  };
}

export const useTradingStore = create<TradingStoreShape>((set, get) => ({
  ticket: null, pendingConfirm: null, submitting: false, lastResult: null,

  openTicket: (credentialId, brokerName, accountLabel = "") => {
    set({
      ticket: { ..._DEFAULT_TICKET(credentialId, brokerName) },
      pendingConfirm: null, lastResult: null,
    });
  },
  closeTicket: () => set({ ticket: null, pendingConfirm: null, lastResult: null }),

  setTicketField: (k, v) => {
    const cur = get().ticket;
    if (!cur) return;
    set({ ticket: { ...cur, [k]: v } });
  },

  requestSubmit: (accountLabel = "") => {
    const t = get().ticket;
    if (!t) return;
    set({
      pendingConfirm: {
        kind: "submit",
        brokerName: t.brokerName,
        accountLabel,
        payload: _ticketToBody(t),
      },
    });
  },

  cancelOrder: async (brokerName, orderId) => {
    set({ submitting: true });
    try {
      await sidecarFetch(`/api/broker/orders/${encodeURIComponent(orderId)}?name=${encodeURIComponent(brokerName)}`, {
        method: "DELETE",
      });
      set({ submitting: false, lastResult: { ok: true } });
      await usePortfolioStore.getState().loadPortfolio();
      return true;
    } catch (e) {
      set({ submitting: false, lastResult: { ok: false, error: e instanceof Error ? e.message : String(e) } });
      return false;
    }
  },

  closePosition: (brokerName, symbol, currentSide, quantity, accountLabel = "") => {
    const opposite: OrderSide = currentSide === "buy" ? "sell" : "buy";
    set({
      pendingConfirm: {
        kind: "close",
        brokerName,
        accountLabel,
        payload: {
          broker: brokerName,
          symbol,
          side: opposite,
          quantity,
          order_type: "market",
          time_in_force: "ioc",
          limit_price: null,
          stop_price: null,
          notes: "close_position",
        },
      },
    });
  },

  confirm: async (typedLabel) => {
    const pc = get().pendingConfirm;
    if (!pc) return;
    if (pc.accountLabel && typedLabel !== pc.accountLabel) {
      set({ lastResult: { ok: false, error: "account_label mismatch" } });
      return;
    }
    set({ submitting: true });
    try {
      const resp = await sidecarFetch<{ broker: string; order: { id: string; status: string } }>(
        "/api/broker/orders",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(pc.payload),
        },
      );
      set({
        submitting: false,
        pendingConfirm: null,
        lastResult: { ok: true, orderId: resp.order?.id },
        ticket: null,
      });
      await usePortfolioStore.getState().loadPortfolio();
    } catch (e) {
      set({
        submitting: false,
        pendingConfirm: null,
        lastResult: { ok: false, error: e instanceof Error ? e.message : String(e) },
      });
    }
  },

  dismissConfirm: () => set({ pendingConfirm: null }),
}));
```

- [ ] **Step C1.3:** Run tests, expect 6 passed.
- [ ] **Step C1.4:** Commit.

### Task C2: OrderTicket component

**Files:** `ui/src/functions/OrderTicket.tsx` + `ui/src/functions/OrderTicket.test.tsx`

OrderTicket is rendered inside CredentialGroup when `g.permissions.includes("trade")`. Compact form: symbol/side/type/qty/limit_price/stop_price/tif/notes. Submit button calls `requestSubmit(g.account_label)`. Inline confirmation modal (when pendingConfirm.kind=="submit"): requires re-typing `accountLabel`. Result strip below.

Implementation pattern mirrors CONN.tsx form. See C1 for store contracts.

Tests cover: renders form, fills fields, submit opens modal, correct accountLabel enables button, wrong accountLabel disables. 4-5 vitest cases.

### Task C3: PORT.tsx wiring (Close, Cancel, OrderTicket)

Modify `ui/src/functions/PORT.tsx`. Inside `<CredentialGroup>`:
- When permissions include "trade", render `<OrderTicket credentialId={g.credential_id} brokerName={`${g.exchange_id}:${g.credential_id}`} accountLabel={g.account_label} />` below the positions table.
- Each position row: add `<Close>` button calling `useTradingStore.getState().closePosition(...)`.
- Each order row: add `<Cancel>` button calling `useTradingStore.getState().cancelOrder(...)`.
- Render `<ConfirmModal>` at the top level of PORTPane when `pendingConfirm` is non-null.

Update PORT.aggregate.test.tsx with at least 2 new tests pinning Close + Cancel button presence/absence based on permissions.

### Task C4: Live smoke + native rebuild

Full pytest + npm test pass; sidecar+tauri+deploy; live curl `POST /api/broker/orders` against a paper broker (existing); screenshot; memory note `showme_subsystem_c.md`; close-out commit `backend/SUBSYSTEM_C.md`.
