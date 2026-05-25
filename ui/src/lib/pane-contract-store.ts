/**
 * Pane contract store — per-(code, symbol) latest contract envelope fields.
 *
 * `useFunction` writes the rebuild contract fields (data_mode, as_of,
 * sources, warnings, next_actions, latency_ms) here on every successful
 * fetch. PaneChrome subscribes and renders the visible contract strip
 * (mode pill + as-of + sources + warnings + next-actions chips) for
 * EVERY pane — not just ManifestPane — so the rebuild is visible on top
 * of every bespoke pane.
 *
 * This is the bridge that makes 30+ bespoke panes (GP/HP/DES/PORT/...)
 * surface the new mode-pill / sources / next-actions affordances without
 * each pane having to opt in explicitly.
 */
import { create } from "zustand";

import type { DataMode } from "@/manifest/types";

export interface PaneContractSnapshot {
  /** Honest data mode label. */
  dataMode?: DataMode | string;
  /** ISO 8601 as-of timestamp. */
  asOf?: string;
  /** Provider source labels. */
  sources?: string[];
  /** Live-mode latency in ms. */
  latencyMs?: number;
  /** Warnings array (always present when manifest declares it). */
  warnings?: string[];
  /** Next-actions array (manifest contract). */
  nextActions?: string[];
  /** Last-updated wall-clock for cache invalidation in UI. */
  receivedAt: number;
}

function makeKey(code: string, symbol?: string): string {
  return symbol ? `${code.toUpperCase()}::${symbol.toUpperCase()}` : code.toUpperCase();
}

interface PaneContractState {
  byKey: Record<string, PaneContractSnapshot>;
  record: (code: string, symbol: string | undefined, snapshot: PaneContractSnapshot) => void;
  clear: (code?: string, symbol?: string) => void;
}

export const usePaneContractStore = create<PaneContractState>((set) => ({
  byKey: {},
  record(code, symbol, snapshot) {
    const key = makeKey(code, symbol);
    set((prev) => ({ byKey: { ...prev.byKey, [key]: snapshot } }));
  },
  clear(code, symbol) {
    set((prev) => {
      if (!code) return { byKey: {} };
      const key = makeKey(code, symbol);
      const next = { ...prev.byKey };
      delete next[key];
      return { byKey: next };
    });
  },
}));

/** React hook reading the contract snapshot for a specific (code, symbol) leaf. */
export function usePaneContract(code: string, symbol?: string): PaneContractSnapshot | undefined {
  const key = makeKey(code, symbol);
  return usePaneContractStore((s) => s.byKey[key]);
}

/** Pure helper for non-React callers (tests, useFunction). */
export function recordPaneContract(
  code: string,
  symbol: string | undefined,
  snapshot: PaneContractSnapshot,
): void {
  usePaneContractStore.getState().record(code, symbol, snapshot);
}
