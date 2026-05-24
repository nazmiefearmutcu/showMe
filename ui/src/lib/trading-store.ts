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
 *
 * Round 24 CRITICAL fix — double-fire guard (REAL MONEY):
 *   - `confirm()` short-circuits when `submitting === true`. A native double
 *     click on the "Gönder" button used to dispatch two POSTs before React
 *     had a chance to re-render `disabled={submitting}`. Without this
 *     store-level gate, every confirm window opened the door to a duplicate
 *     order — which on a live broker means two real positions.
 *   - Every POST payload now carries `idempotency_key = crypto.randomUUID()`
 *     so the backend (broker.submit_order / sidecar) can drop the second
 *     request even if it races past the UI gate. The key is generated once
 *     in `requestSubmit()` / `closePosition()` / `requestCancel()` and
 *     stamped into `pendingConfirm.payload` so the modal preview reflects
 *     the exact bytes we'll send.
 *
 * Backend contract (must be honoured by sidecar — see DOCS_NEW comment in
 * server_routes/broker.py / bots/runner.py):
 *   - Accept `idempotency_key` as a JSON field OR an `Idempotency-Key`
 *     HTTP header. Dedupe window ≥ 60 s. UI sends both forms below so the
 *     server can pick whichever it prefers.
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";
import { usePortfolioStore } from "./portfolio-store";

/**
 * Generate a UUID for idempotency_key. Uses `crypto.randomUUID()` when
 * available (modern browsers + Tauri); falls back to a Math.random+Date
 * hex when not (very old Vitest env without crypto.subtle).
 */
function _newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Fallback — not cryptographically strong but uniqueness is the only
  // requirement here (dedupe key, not a secret).
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}-${Math.random().toString(36).slice(2, 10)}`;
}

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
    // Round 24 CRITICAL — never overwrite an in-flight pendingConfirm. A
    // rapid Run/Continue click after the form re-enabled (e.g. error
    // bounce-back) used to recycle the modal under a second request — the
    // first POST was still in-flight, so this protects us from racing the
    // confirm dialog itself.
    if (get().submitting) return;
    // Prefer the caller-provided label; fall back to whatever was wired in at
    // openTicket time. The confirm() guard rejects empty values either way.
    const resolved = accountLabel || t.accountLabel || "";
    const body = _ticketToBody(t);
    body.idempotency_key = _newIdempotencyKey();
    set({
      pendingConfirm: {
        kind: "submit",
        brokerName: t.brokerName,
        accountLabel: resolved,
        payload: body,
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
    if (get().submitting) return;
    set({
      pendingConfirm: {
        kind: "cancel",
        brokerName,
        accountLabel,
        orderId,
        symbol,
        payload: {
          broker: brokerName,
          order_id: orderId,
          symbol,
          idempotency_key: _newIdempotencyKey(),
        },
      },
      lastResult: null,
    });
  },

  closePosition: (brokerName, symbol, currentSide, quantity, accountLabel = "") => {
    if (get().submitting) return;
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
          idempotency_key: _newIdempotencyKey(),
        },
      },
      lastResult: null,
    });
  },

  confirm: async (typedLabel) => {
    // Round 24 CRITICAL (REAL MONEY) — the OrderTicket confirm modal's
    // "Gönder" button has `disabled={submitting}` BUT React batches state
    // before the next paint, so a hardware double-click (≤ ~50 ms) fired
    // two onClick events before `submitting` flipped true. The result: two
    // POST /api/broker/orders → two real positions on a live broker.
    //
    // This store-level early-exit is the canonical seal. Combined with
    // `idempotency_key` in the payload (backend dedupe defence-in-depth)
    // and the modal's disabled-button, we're three layers deep — none of
    // which can be bypassed by a stale ref or React batching.
    if (get().submitting) return;
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
    // Idempotency key lives inside pc.payload (so the modal preview shows
    // exactly what we'll send); also lifted into an HTTP header so the
    // backend can dedupe without parsing the JSON body — whichever is
    // cheaper for the sidecar to inspect.
    const idemKey =
      typeof pc.payload?.idempotency_key === "string"
        ? (pc.payload.idempotency_key as string)
        : undefined;
    try {
      if (pc.kind === "cancel" && pc.orderId) {
        await sidecarFetch(
          `/api/broker/orders/${encodeURIComponent(pc.orderId)}?name=${encodeURIComponent(pc.brokerName)}`,
          {
            method: "DELETE",
            headers: idemKey ? { "Idempotency-Key": idemKey } : undefined,
          },
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
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (idemKey) headers["Idempotency-Key"] = idemKey;
      const resp = await sidecarFetch<{ broker: string; order: { id: string; status: string } }>(
        "/api/broker/orders",
        {
          method: "POST",
          headers,
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
