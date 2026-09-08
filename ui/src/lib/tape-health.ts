/**
 * Tape health — one honest aggregate over the live quote layer.
 *
 * Campaign 2026-09-08 (Lane B, U3): the Statusbar asserted sidecar *process*
 * health but said nothing about market *data* liveness. Every quote
 * subscription already funnels through `subscribeQuoteMultiplexed`
 * (lib/market-data.ts), which now reports transport transitions and ticks
 * into this tiny module-level registry. Nothing here opens sockets or polls:
 * the store only mirrors what the quote layer already knows.
 *
 * Public surface:
 *   - useTapeHealth()          — React binding (useSyncExternalStore).
 *   - getTapeHealth()          — snapshot for non-React callers / tests.
 *   - subscribeTapeHealth(fn)  — external-store subscription.
 *
 * Aggregation vocabulary (matches the pane pills: LIVE / RECONNECTING / DOWN):
 *   - idle          — no symbol subscriptions at all (pill hidden upstream).
 *   - live          — at least one symbol transport is live.
 *   - reconnecting  — nothing live, but at least one socket is (re)connecting.
 *   - down          — subscriptions exist but every one is stale/error/offline.
 *
 * `lastTickAt` is the freshest tick timestamp across all subscribed symbols
 * so the Statusbar can show honest staleness ("2s") instead of a bare dot.
 */
import { useSyncExternalStore } from "react";
import type { TransportState } from "./market-data";

export type TapeState = "idle" | "live" | "reconnecting" | "down";

export interface TapeHealth {
  state: TapeState;
  /** Symbols whose current transport state is `live`. */
  liveSymbols: number;
  /** Total symbols with an open quote subscription. */
  totalSymbols: number;
  /** Unix ms of the freshest tick seen across symbols; null when none yet. */
  lastTickAt: number | null;
}

interface TapeEntry {
  transport: TransportState;
  lastTickAt: number | null;
}

const entries = new Map<string, TapeEntry>();
const listeners = new Set<() => void>();
let snapshot: TapeHealth = computeSnapshot();

function computeSnapshot(): TapeHealth {
  let live = 0;
  let total = 0;
  let connecting = 0;
  let lastTickAt: number | null = null;
  for (const entry of entries.values()) {
    total += 1;
    if (entry.transport === "live") live += 1;
    if (entry.transport === "connecting" || entry.transport === "reconnecting") {
      connecting += 1;
    }
    if (entry.lastTickAt != null && (lastTickAt == null || entry.lastTickAt > lastTickAt)) {
      lastTickAt = entry.lastTickAt;
    }
  }
  const state: TapeState =
    total === 0 ? "idle" : live > 0 ? "live" : connecting > 0 ? "reconnecting" : "down";
  return { state, liveSymbols: live, totalSymbols: total, lastTickAt };
}

function commit(): void {
  snapshot = computeSnapshot();
  for (const notify of listeners) {
    try {
      notify();
    } catch {
      // One bad listener must never break the rest of the fan-out.
    }
  }
}

// ---------- instrumentation surface (called from market-data.ts) ----------

/** Record a transport-state transition for `symbol`. */
export function __tapeRecordTransport(symbol: string, transport: TransportState): void {
  const target = symbol.trim().toUpperCase();
  if (!target) return;
  const existing = entries.get(target);
  if (existing) {
    if (existing.transport === transport) return;
    existing.transport = transport;
  } else {
    entries.set(target, { transport, lastTickAt: null });
  }
  commit();
}

/** Record a valid tick for `symbol` (timestamps in unix ms). */
export function __tapeRecordTick(symbol: string, atMs: number): void {
  const target = symbol.trim().toUpperCase();
  if (!target || !Number.isFinite(atMs)) return;
  const existing = entries.get(target);
  if (existing) {
    // Later ticks only — late/out-of-order frames never move the clock back.
    if (existing.lastTickAt != null && atMs <= existing.lastTickAt) return;
    existing.lastTickAt = atMs;
  } else {
    entries.set(target, { transport: "connecting", lastTickAt: atMs });
  }
  commit();
}

/** Drop `symbol` from the registry (subscription fully closed). */
export function __tapeRelease(symbol: string): void {
  const target = symbol.trim().toUpperCase();
  if (!target || !entries.has(target)) return;
  entries.delete(target);
  commit();
}

// ---------- external store ----------

export function getTapeHealth(): TapeHealth {
  return snapshot;
}

export function subscribeTapeHealth(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** React binding — re-renders on transport/tick registry changes only. */
export function useTapeHealth(): TapeHealth {
  return useSyncExternalStore(subscribeTapeHealth, getTapeHealth, getTapeHealth);
}

// ---------- tests ----------

export function __resetTapeHealthForTests(): void {
  entries.clear();
  commit();
}
