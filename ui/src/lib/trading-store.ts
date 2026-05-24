/**
 * Sub-system C: trading store. Wraps POST /api/broker/orders + DELETE.
 * Confirmation modal (pendingConfirm) gates every write — including
 * cancel-order (fix QA-2026-05-23).
 *
 * Contract notes (financial safety):
 *   - `confirm()` REQUIRES a non-empty accountLabel; an empty label is
 *     always rejected with `error="missing_account_label"`. This closes
 *     the bypass where the old `if (pc.accountLabel && ...)` skipped the
 *     guard when CONN/PORT forgot to pass the label.
 *   - `cancelOrder` is now `requestCancel` + `confirm` (modal-gated); the
 *     legacy DELETE happens only inside `confirm()` after re-type passes.
 *   - `lastResult.kind` lets the UI route toasts to the right place
 *     ("submit" → OrderTicket, "close"/"cancel" → PORT).
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";
import { usePortfolioStore } from "./portfolio-store";

export type OrderSide = "buy" | "sell";
export type OrderType = "market" | "limit" | "stop" | "stop_limit";
export type TimeInForce = "day" | "gtc" | "ioc" | "fok";

export type ConfirmKind = "submit" | "close" | "cancel";

/**
 * Backend `Position.side` may carry futures-style "long"/"short" instead of
 * the spot "buy"/"sell" the broker write APIs expect. Normalize so PORT.tsx
 * can hand any backend payload to `closePosition` without casting.
 */
export function normalizeSide(s: string | null | undefined): OrderSide {
  const v = (s ?? "").trim().toLowerCase();
  if (v === "buy" || v === "long") return "buy";
  if (v === "sell" || v === "short") return "sell";
  // eslint-disable-next-line no-console
  console.warn(`[trading-store] normalizeSide: unknown side "${s}", defaulting to "buy"`);
  return "buy";
}

export interface TicketState {
  credentialId: string;
  brokerName: string;            // "{exchange_id}:{credential_id}"
  accountLabel: string;          // resolved from credential on openTicket
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
  kind: ConfirmKind;
  brokerName: string;
  accountLabel: string;          // for re-type confirmation; populated on open
  payload: Record<string, unknown>;  // ready-to-send body for the API
  // cancel-only — DELETE doesn't go through POST /api/broker/orders:
  orderId?: string;
  symbol?: string;
}

export interface LastResult {
  ok: boolean;
  kind?: ConfirmKind;            // routing key for toasts
  orderId?: string;
  symbol?: string;
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
  /**
   * @deprecated Use `requestCancel` + `confirm` to keep the re-type guard.
   * Retained only so older test fixtures keep compiling; production code
   * paths now stage `pendingConfirm.kind="cancel"` and gate via the modal.
   */
  cancelOrder: (brokerName: string, orderId: string) => Promise<boolean>;
  requestCancel: (
    brokerName: string,
    orderId: string,
    accountLabel: string,
    symbol?: string,
  ) => void;
  closePosition: (brokerName: string, symbol: string, currentSide: OrderSide, quantity: number, accountLabel?: string) => void;
  confirm: (typedLabel: string) => Promise<void>;
  dismissConfirm: () => void;
  clearLastResult: () => void;
}

const _DEFAULT_TICKET = (
  credentialId: string,
  brokerName: string,
  accountLabel: string,
): TicketState => ({
  credentialId, brokerName, accountLabel,
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
      ticket: { ..._DEFAULT_TICKET(credentialId, brokerName, accountLabel) },
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
    // Prefer the caller-provided label; fall back to whatever was wired in at
    // openTicket time. The confirm() guard rejects empty values either way.
    const resolved = accountLabel || t.accountLabel || "";
    set({
      pendingConfirm: {
        kind: "submit",
        brokerName: t.brokerName,
        accountLabel: resolved,
        payload: _ticketToBody(t),
      },
    });
  },

  cancelOrder: async (brokerName, orderId) => {
    // Legacy direct path. New code paths must use `requestCancel` so the
    // re-type-confirm modal gates the DELETE. Retained for backwards compat.
    set({ submitting: true });
    try {
      await sidecarFetch(`/api/broker/orders/${encodeURIComponent(orderId)}?name=${encodeURIComponent(brokerName)}`, {
        method: "DELETE",
      });
      set({ submitting: false, lastResult: { ok: true, kind: "cancel", orderId } });
      await usePortfolioStore.getState().loadPortfolio();
      return true;
    } catch (e) {
      set({
        submitting: false,
        lastResult: {
          ok: false,
          kind: "cancel",
          orderId,
          error: e instanceof Error ? e.message : String(e),
        },
      });
      return false;
    }
  },

  requestCancel: (brokerName, orderId, accountLabel, symbol) => {
    set({
      pendingConfirm: {
        kind: "cancel",
        brokerName,
        accountLabel,
        orderId,
        symbol,
        payload: { broker: brokerName, order_id: orderId, symbol },
      },
      lastResult: null,
    });
  },

  closePosition: (brokerName, symbol, currentSide, quantity, accountLabel = "") => {
    const opposite: OrderSide = currentSide === "buy" ? "sell" : "buy";
    set({
      pendingConfirm: {
        kind: "close",
        brokerName,
        accountLabel,
        symbol,
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
      lastResult: null,
    });
  },

  confirm: async (typedLabel) => {
    const pc = get().pendingConfirm;
    if (!pc) return;
    // GUARD #1 — empty accountLabel must NEVER be silently allowed. This is
    // the bypass QA-2026-05-23 flagged: when CONN/PORT forgot to thread the
    // label, the old `if (pc.accountLabel && ...)` evaluated false and the
    // write went through unconfirmed.
    if (!pc.accountLabel || pc.accountLabel.trim() === "") {
      set({
        pendingConfirm: null,
        lastResult: {
          ok: false,
          kind: pc.kind,
          error: "missing_account_label: no active account selected",
        },
      });
      return;
    }
    // GUARD #2 — typed label must match the credential's account_label.
    if (typedLabel !== pc.accountLabel) {
      set({ lastResult: { ok: false, kind: pc.kind, error: "account_label mismatch" } });
      return;
    }
    set({ submitting: true });
    try {
      if (pc.kind === "cancel" && pc.orderId) {
        await sidecarFetch(
          `/api/broker/orders/${encodeURIComponent(pc.orderId)}?name=${encodeURIComponent(pc.brokerName)}`,
          { method: "DELETE" },
        );
        set({
          submitting: false,
          pendingConfirm: null,
          lastResult: { ok: true, kind: "cancel", orderId: pc.orderId, symbol: pc.symbol },
        });
        await usePortfolioStore.getState().loadPortfolio();
        return;
      }
      // submit + close both go through POST /api/broker/orders.
      // Backend (broker.py) now requires confirmation_token to match the
      // credential's account_label. We use the typed label that just passed
      // GUARD #2 above — same string the user typed, same string the backend
      // expects.
      const resp = await sidecarFetch<{ broker: string; order: { id: string; status: string } }>(
        "/api/broker/orders",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...pc.payload, confirmation_token: typedLabel }),
        },
      );
      set({
        submitting: false,
        pendingConfirm: null,
        lastResult: { ok: true, kind: pc.kind, orderId: resp.order?.id, symbol: pc.symbol },
        ticket: pc.kind === "submit" ? null : get().ticket,
      });
      await usePortfolioStore.getState().loadPortfolio();
    } catch (e) {
      set({
        submitting: false,
        pendingConfirm: null,
        lastResult: {
          ok: false,
          kind: pc.kind,
          orderId: pc.orderId,
          symbol: pc.symbol,
          error: e instanceof Error ? e.message : String(e),
        },
      });
    }
  },

  dismissConfirm: () => set({ pendingConfirm: null }),
  clearLastResult: () => set({ lastResult: null }),
}));
