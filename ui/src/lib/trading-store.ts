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

  openTicket: (credentialId, brokerName, _accountLabel = "") => {
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
