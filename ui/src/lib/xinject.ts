/**
 * Cross-pane handoff for the XSEN → INSTANT flow.
 *
 * XSEN's "→ INSTANT" button calls `setInjection(symbol)` and then
 * `navigate("/fn/INSTANT")`. INSTANT consumes the pending injection on
 * mount via {@link useXInjectStore.getState().consumeInjection} and
 * applies it to the X-merge query input.
 *
 * Zustand store chosen over `sessionStorage` because:
 *   - we already use Zustand everywhere else in the app (one mental model);
 *   - the consumer can subscribe declaratively if it ever needs to react
 *     to a re-injection while INSTANT is already mounted;
 *   - no JSON parse/serialize round-trip per handoff.
 */
import { create } from "zustand";

export interface PendingInjection {
  symbol: string;
  ts: number;
}

interface XInjectState {
  pendingInjection: PendingInjection | null;
  setInjection(symbol: string): void;
  consumeInjection(): PendingInjection | null;
}

export const useXInjectStore = create<XInjectState>((set, get) => ({
  pendingInjection: null,
  setInjection(symbol: string) {
    const trimmed = symbol.trim();
    if (!trimmed) return;
    set({ pendingInjection: { symbol: trimmed, ts: Date.now() } });
  },
  consumeInjection() {
    const pending = get().pendingInjection;
    if (pending) set({ pendingInjection: null });
    return pending;
  },
}));
