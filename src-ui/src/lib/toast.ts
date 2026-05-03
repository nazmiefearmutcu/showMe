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

export const useToastStore = create<State>((set, get) => ({
  toasts: [],
  push: (t) => {
    const id = t.id ?? `t-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const ttl = t.ttl ?? (t.tone === "error" ? 8000 : 4000);
    const ts = Date.now();
    set((s) => ({
      toasts: [...s.toasts.filter((x) => x.id !== id), { ...t, id, ts }],
    }));
    if (ttl > 0) {
      setTimeout(() => get().dismiss(id), ttl);
    }
    return id;
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  clear: () => set({ toasts: [] }),
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
