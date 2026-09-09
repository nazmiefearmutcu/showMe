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
 *
 * R1-L fix (2026-09-09, lane F): `commit()` used to fire on EVERY tick, and
 * every commit handed useSyncExternalStore a fresh snapshot object — so the
 * Statusbar re-rendered far above its designed 1 Hz heartbeat on a lively
 * crypto desk. Two cheap guards now sit in front of the notify fan-out:
 *   1. Skip entirely when nothing observable changed (state + counters +
 *      lastTickAt all identical).
 *   2. Coalesce tick-only churn (state/counters unchanged) to at most one
 *      commit per TAPE_COMMIT_MIN_MS (~1/s). Transport-structure changes
 *      (subscribe / release / state transitions) always commit immediately —
 *      LIVE→DOWN honesty must never wait on a throttle. A deferred tick
 *      commit loses nothing: the next allowed commit recomputes straight
 *      from the entries map, so `lastTickAt` trails by at most one window.
 */
import { useSyncExternalStore } from "react";
import type { TransportState } from "./market-data";

export type TapeState = "idle" | "live" | "reconnecting" | "down";

/**
 * Shared state-word vocabulary for every tape readout (Statusbar pill,
 * Titlebar mini-tape). Single-sourced here so the two surfaces can never
 * drift into different words for the same transport truth.
 */
export const TAPE_LABEL: Record<TapeState, string> = {
  idle: "IDLE",
  live: "LIVE",
  reconnecting: "RECONNECTING",
  down: "DOWN",
};

/** Minimum spacing between two tick-only commits (R1-L throttle window). */
const TAPE_COMMIT_MIN_MS = 900;

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
// R1-L throttle bookkeeping: signature of the last COMMITTED structure
// (state + counters) and when it was committed. `lastCommitAt === 0` means
// "nothing committed since reset" so the first commit always fires.
let lastCommittedSig = `${snapshot.state}|${snapshot.liveSymbols}|${snapshot.totalSymbols}`;
let lastCommitAt = 0;

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
  const next = computeSnapshot();
  const sig = `${next.state}|${next.liveSymbols}|${next.totalSymbols}`;
  const structureChanged = sig !== lastCommittedSig;
  if (!structureChanged) {
    if (next.lastTickAt === snapshot.lastTickAt) return; // nothing observable moved
    // The FIRST tick (age figure "—" → a number) is a visible state change
    // for every readout — commit it like a transition. Later tick-only
    // churn coalesces to ~1/s. Transport honesty (LIVE/DOWN transitions)
    // never waits — that path took the `structureChanged` branch. A
    // deferred tick is not lost: the next allowed commit recomputes from
    // the entries map, so `lastTickAt` trails by at most one
    // TAPE_COMMIT_MIN_MS window.
    const firstTick = snapshot.lastTickAt === null && next.lastTickAt !== null;
    if (!firstTick && Date.now() - lastCommitAt < TAPE_COMMIT_MIN_MS) return;
  }
  lastCommittedSig = sig;
  lastCommitAt = Date.now();
  snapshot = next;
  notifyAll();
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

function notifyAll(): void {
  for (const notify of listeners) {
    try {
      notify();
    } catch {
      // One bad listener must never break the rest of the fan-out.
    }
  }
}

export function __resetTapeHealthForTests(): void {
  entries.clear();
  snapshot = computeSnapshot();
  lastCommittedSig = `${snapshot.state}|${snapshot.liveSymbols}|${snapshot.totalSymbols}`;
  lastCommitAt = 0;
  // Reset always notifies (bypasses the throttle — it is test-only and
  // must leave subscribed components consistent with the cleared registry).
  notifyAll();
}

/**
 * Shared age formatter for tape readouts (Statusbar pill + Titlebar
 * mini-tape): "<1s" / "12s" / "3m" / "2h 14m". Single-sourced so both
 * surfaces render the same staleness vocabulary.
 */
export function formatTickAge(ms: number): string {
  if (ms < 1_000) return "<1s";
  const s = Math.floor(ms / 1_000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest > 0 ? `${h}h ${rest}m` : `${h}h`;
}
