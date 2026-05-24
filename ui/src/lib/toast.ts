/**
 * Toast / inline alert host.
 *
 * Replaces native `alert()` / `confirm()` (forbidden by ui_standards §6).
 * Round 16+ promotes "critical" toasts to NSAlert via tauri-plugin-dialog.
 */
import { create } from "zustand";

export type ToastTone = "info" | "success" | "warn" | "error";

export interface Toast {
  id: string;
  tone: ToastTone;
  title: string;
  body?: string;
  ttl?: number; // ms, 0 = sticky
  ts: number;
}

interface State {
  toasts: Toast[];
  push: (t: Omit<Toast, "id" | "ts"> & { id?: string }) => string;
  dismiss: (id: string) => void;
  clear: () => void;
}

// HIGH FIX (audit S13): TTL setTimeout handles were never tracked, so
// `clear()` left them running. After a clear they'd still fire `dismiss(id)`,
// which is harmless for the store but pinned closures over the toast id
// strings forever. Track timer handles in a module-scoped map and tear them
// down explicitly on dismiss + clear.
const _toastTimers = new Map<string, ReturnType<typeof setTimeout>>();

function _cancelToastTimer(id: string): void {
  const t = _toastTimers.get(id);
  if (t != null) {
    clearTimeout(t);
    _toastTimers.delete(id);
  }
}

/**
 * HIGH #17 (UI-Shell-Bundle UB) — hard cap on the queue.
 *
 * A burst of 100+ toasts (sidecar restart loop, malformed feed) used to
 * render the whole stack to the DOM at once because the store has no
 * upper bound and the ToastHost just maps over the array. Cap the
 * visible queue at MAX_QUEUE; when a new toast pushes the queue over,
 * evict the *oldest* (FIFO) so the user always sees the latest signal
 * at the bottom.
 */
const MAX_QUEUE = 10;
export const TOAST_MAX_QUEUE = MAX_QUEUE;

export const useToastStore = create<State>((set, get) => ({
  toasts: [],
  push: (t) => {
    const id = t.id ?? `t-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const ttl = t.ttl ?? (t.tone === "error" ? 8000 : 4000);
    const ts = Date.now();
    // If the caller is replacing an existing toast (e.g. same explicit id),
    // cancel its scheduled dismiss before installing the new one.
    _cancelToastTimer(id);
    set((s) => {
      const deduped = s.toasts.filter((x) => x.id !== id);
      const next = [...deduped, { ...t, id, ts }];
      if (next.length > MAX_QUEUE) {
        // Drop the oldest entries first so the freshly-pushed toast
        // is always in the visible slice. Cancel their timers too —
        // otherwise the dismiss timer would no-op against an absent
        // store entry but keep its closure alive.
        const evicted = next.slice(0, next.length - MAX_QUEUE);
        for (const dead of evicted) _cancelToastTimer(dead.id);
        return { toasts: next.slice(next.length - MAX_QUEUE) };
      }
      return { toasts: next };
    });
    if (ttl > 0) {
      const timer = setTimeout(() => {
        _toastTimers.delete(id);
        get().dismiss(id);
      }, ttl);
      _toastTimers.set(id, timer);
    }
    return id;
  },
  dismiss: (id) => {
    _cancelToastTimer(id);
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },
  clear: () => {
    for (const timer of _toastTimers.values()) clearTimeout(timer);
    _toastTimers.clear();
    set({ toasts: [] });
  },
}));

export const toast = {
  info: (title: string, body?: string) =>
    useToastStore.getState().push({ tone: "info", title, body }),
  success: (title: string, body?: string) =>
    useToastStore.getState().push({ tone: "success", title, body }),
  warn: (title: string, body?: string) =>
    useToastStore.getState().push({ tone: "warn", title, body }),
  error: (title: string, body?: string) =>
    useToastStore.getState().push({ tone: "error", title, body }),
};
