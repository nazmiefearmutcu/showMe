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
import { useMemo } from "react";
import { create } from "zustand";

import type { DataMode } from "@/manifest/types";
import { onWorkspaceReset, useWorkspace, type WorkspaceNode } from "./workspace";

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

/**
 * UI-ROBUSTNESS F5 — every (code, symbol) pair ever fetched used to be
 * retained for the process lifetime, and `clear()` had zero production
 * callers. Symbol scanners walking hundreds of symbols grew `byKey`
 * monotonically. Cap it drop-oldest (by `receivedAt`) and subscribe the
 * store to `onWorkspaceReset` so a workspace teardown actually drops the
 * stale contract data (see workspace.ts HIGH #9 hook).
 */
const MAX_CONTRACT_ENTRIES = 200;

interface PaneContractState {
  byKey: Record<string, PaneContractSnapshot>;
  record: (code: string, symbol: string | undefined, snapshot: PaneContractSnapshot) => void;
  clear: (code?: string, symbol?: string) => void;
}

export const usePaneContractStore = create<PaneContractState>((set) => ({
  byKey: {},
  record(code, symbol, snapshot) {
    const key = makeKey(code, symbol);
    set((prev) => {
      const next: Record<string, PaneContractSnapshot> = { ...prev.byKey, [key]: snapshot };
      const keys = Object.keys(next);
      if (keys.length <= MAX_CONTRACT_ENTRIES) return { byKey: next };
      // Drop-oldest by receivedAt (missing stamp sorts first = dropped first).
      keys.sort(
        (a, b) => (next[a]?.receivedAt ?? 0) - (next[b]?.receivedAt ?? 0),
      );
      const excess = keys.length - MAX_CONTRACT_ENTRIES;
      for (let i = 0; i < excess; i += 1) {
        delete next[keys[i]];
      }
      return { byKey: next };
    });
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

// F5 — workspace teardown (resetTo / preset load / self-heal) wipes the
// contract cache. Module-level subscription on purpose: the store lives for
// the process lifetime. `onWorkspaceReset` returns an unsubscriber we
// deliberately discard.
onWorkspaceReset(() => {
  usePaneContractStore.getState().clear();
});

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

/* ──────────────────────────────────────────────────────────────────────────
 * Desk-health rollup (campaign 2026-09-11, Lane L4)
 *
 * Per-pane provenance (dataMode / asOf / sources / warnings / latencyMs) was
 * tooltip-only. These pure selectors classify every recorded contract into
 * exactly one health tier and aggregate the desk-level counts the Statusbar
 * and PaneHealth chip render.
 *
 * Tier semantics (frozen, shared with PaneHealth):
 *   - stale    : stamp older than PANE_STALE_AFTER_MS (highest precedence —
 *                age is the strongest evidence that data can't be trusted)
 *   - degraded : warnings present, OR the declared mode is not a live tier
 *                (synthetic/reference/modeled/cached/unavailable/unknown — an
 *                undeclared mode can never claim "live")
 *   - live     : live_official / live_exchange, fresh, no warnings
 *
 * The stamp is the payload's own ISO `asOf` when parseable, falling back to
 * the client `receivedAt` (a pane whose fetches stopped ages out even when
 * the provider never stamped the payload).
 * ────────────────────────────────────────────────────────────────────────── */

/** Canonical shape alias for component props (frozen cross-lane interface). */
export type PaneContract = PaneContractSnapshot;

export type PaneHealthTier = "live" | "degraded" | "stale";

export interface DeskHealth {
  live: number;
  degraded: number;
  stale: number;
  /** Max latencyMs across recorded contracts; null when none declared. */
  worstLatencyMs: number | null;
  /** Max receivedAt across recorded contracts; null when none recorded. */
  lastUpdatedAt: number | null;
}

/**
 * How old a contract may be before the desk calls it stale. Five minutes is
 * ~2.5-10x the slowest pane poll (90-120 s) — long enough that a healthy
 * slow pane never trips it, short enough that a dead feed is named as stale
 * within the same sitting.
 */
export const PANE_STALE_AFTER_MS = 5 * 60_000;

const LIVE_DATA_MODES: ReadonlySet<string> = new Set<string>([
  "live_official",
  "live_exchange",
]);

/** Resolve the timestamp a contract is judged by (asOf, else receivedAt). */
export function paneStampedAt(snap: PaneContractSnapshot): number {
  if (typeof snap.asOf === "string") {
    const parsed = Date.parse(snap.asOf);
    if (Number.isFinite(parsed)) return parsed;
  }
  return snap.receivedAt;
}

/** Clamped age of a contract in ms (never negative — clock skew reads 0). */
export function paneAgeMs(snap: PaneContractSnapshot, now: number): number {
  return Math.max(0, now - paneStampedAt(snap));
}

/** Classify a single contract into exactly one tier. */
export function paneHealthTier(snap: PaneContractSnapshot, now: number): PaneHealthTier {
  if (paneAgeMs(snap, now) > PANE_STALE_AFTER_MS) return "stale";
  if ((snap.warnings?.length ?? 0) > 0) return "degraded";
  const mode = typeof snap.dataMode === "string" ? snap.dataMode : "";
  return LIVE_DATA_MODES.has(mode) ? "live" : "degraded";
}

/** Aggregate a byKey map into desk-level health counts. Pure + testable. */
export function computeDeskHealth(
  byKey: Record<string, PaneContractSnapshot>,
  now: number,
): DeskHealth {
  let live = 0;
  let degraded = 0;
  let stale = 0;
  let worstLatencyMs: number | null = null;
  let lastUpdatedAt: number | null = null;
  for (const key of Object.keys(byKey)) {
    const snap = byKey[key];
    if (!snap) continue;
    const tier = paneHealthTier(snap, now);
    if (tier === "live") live += 1;
    else if (tier === "degraded") degraded += 1;
    else stale += 1;
    if (
      typeof snap.latencyMs === "number" &&
      Number.isFinite(snap.latencyMs) &&
      (worstLatencyMs == null || snap.latencyMs > worstLatencyMs)
    ) {
      worstLatencyMs = snap.latencyMs;
    }
    if (lastUpdatedAt == null || snap.receivedAt > lastUpdatedAt) {
      lastUpdatedAt = snap.receivedAt;
    }
  }
  return { live, degraded, stale, worstLatencyMs, lastUpdatedAt };
}

/**
 * Contract cache keys for every leaf currently in the workspace tree.
 * Desk health counts only ON-SCREEN panes (R1-F3): record() keeps a cache
 * of every (code, symbol) ever fetched, so aggregating the raw cache let a
 * retargeted or closed leaf inflate STALE/DEGRADED until the 200-entry cap.
 */
export function leafContractKeys(tree: WorkspaceNode): string[] {
  const out: string[] = [];
  const walk = (node: WorkspaceNode): void => {
    if (node.kind === "leaf") {
      out.push(makeKey(node.code, node.symbol));
      return;
    }
    for (const child of node.children) walk(child);
  };
  walk(tree);
  return out;
}

/**
 * Desk-level health over the contracts bound to the CURRENT workspace
 * leaves. Recomputed on each render of the consuming component (counters
 * are O(entries ≤ 200)); a consumer that renders on a clock (Statusbar,
 * 1 Hz) therefore keeps the staleness classification moving without extra
 * timers in the store.
 */
export function useDeskHealth(): DeskHealth {
  const byKey = usePaneContractStore((s) => s.byKey);
  const tree = useWorkspace((s) => s.tree);
  const liveKeys = useMemo(() => new Set(leafContractKeys(tree)), [tree]);
  const scoped = useMemo(() => {
    let changed = false;
    const out: Record<string, PaneContractSnapshot> = {};
    for (const key of Object.keys(byKey)) {
      if (liveKeys.has(key)) {
        out[key] = byKey[key];
      } else {
        changed = true;
      }
    }
    return changed ? out : byKey;
  }, [byKey, liveKeys]);
  return computeDeskHealth(scoped, Date.now());
}

/** Compact latency readout: "84ms" under a second, "1.2s" above. */
export function formatLatencyMs(ms: number): string {
  const clamped = Math.max(0, ms);
  if (clamped < 1000) return `${Math.round(clamped)}ms`;
  return `${(clamped / 1000).toFixed(1)}s`;
}
