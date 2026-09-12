/**
 * Watchlist store — list of symbols persisted via Tauri filesystem
 * (round 16's `state/` directory) with a localStorage fallback.
 *
 * The schema is dead simple: an array of symbol strings + an optional
 * label per row (e.g. "tech mega-caps", "crypto majors"). Round 27+
 * may extend with per-row alert thresholds; the store is forward-
 * compatible because the writer always reads back the same JSON
 * shape.
 */
import { useSyncExternalStore } from "react";
import { invoke, isInTauri } from "./tauri";
import { safeReadLocal, safeWriteLocal } from "./safe-storage";

const KEY = "showme.watchlist";

export interface WatchlistRow {
  symbol: string;
  label?: string;
  added_at?: string;
}

interface Bundle {
  rows: WatchlistRow[];
}

function readLocal(): Bundle {
  return safeReadLocal<Bundle>(KEY, { rows: [] }, {
    label: "Watchlist",
    validate: (v): v is Bundle =>
      Boolean(v && typeof v === "object" && Array.isArray((v as { rows?: unknown }).rows)),
  });
}

function writeLocal(bundle: Bundle): void {
  // HIGH FIX (audit S14): channel the localStorage write through
  // safeWriteLocal so a QuotaExceededError surfaces a single, accurate
  // toast instead of silently dropping the row.
  safeWriteLocal(KEY, bundle, { label: "Watchlist" });
}

async function readTauri(): Promise<Bundle | null> {
  if (!isInTauri()) return null;
  try {
    const v = await invoke<Bundle | null>("read_preset", { name: "watchlist" });
    return v ?? null;
  } catch {
    return null;
  }
}

async function writeTauri(bundle: Bundle): Promise<boolean> {
  if (!isInTauri()) return false;
  try {
    await invoke("write_preset", { name: "watchlist", content: bundle });
    return true;
  } catch {
    return false;
  }
}

/** Read the active watchlist; Tauri preferred, local fallback. */
export async function loadWatchlist(): Promise<WatchlistRow[]> {
  const remote = await readTauri();
  const rows = remote && remote.rows ? remote.rows : readLocal().rows;
  publish(rows);
  return rows;
}

export async function saveWatchlist(rows: WatchlistRow[]): Promise<void> {
  const bundle: Bundle = { rows };
  if (await writeTauri(bundle)) {
    publish(rows);
    return;
  }
  writeLocal(bundle);
  publish(rows);
}

/**
 * Reactive layer (campaign 2026-09-11 double / lane B1).
 *
 * PaneChrome's "+ watch" toggle must reflect membership changes made
 * anywhere else in the app (WATCH pane, Welcome seeding, MIS). The
 * watchlist itself stays async (Tauri preset filesystem / localStorage),
 * so a module-level cache is the single source of truth for snapshots:
 * every load/save publishes it, and subscribers re-read
 * `isWatched()` synchronously.
 */
const listeners = new Set<() => void>();
let cache: WatchlistRow[] | null = null;
let initialLoad: Promise<WatchlistRow[]> | null = null;

function publish(rows: WatchlistRow[]): void {
  cache = rows;
  for (const listener of listeners) listener();
}

export function subscribeWatchlist(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Synchronous membership check against the published cache. */
export function isWatched(symbol: string): boolean {
  const sym = symbol.trim().toUpperCase();
  if (!sym || !cache) return false;
  return cache.some((r) => r.symbol === sym);
}

/**
 * One-shot hydration for components that mount before any other surface
 * has read the store (PaneChrome mounts with the desk). Shares a single
 * in-flight read across every caller; a failed read resolves empty so a
 * mount can never hang.
 */
export function ensureWatchlistLoaded(): Promise<WatchlistRow[]> {
  if (!initialLoad) {
    initialLoad = loadWatchlist().catch(() => [] as WatchlistRow[]);
  }
  return initialLoad;
}

/** Test-only: reset the module cache + in-flight hydration promise. */
export function resetWatchlistStoreForTests(): void {
  cache = null;
  initialLoad = null;
  listeners.clear();
}

/**
 * React binding for the toggle. Returns false (not watched) until the
 * store is hydrated, then tracks every publish.
 */
export function useIsWatched(symbol?: string): boolean {
  const sym = symbol ? symbol.trim().toUpperCase() : "";
  return useSyncExternalStore(
    subscribeWatchlist,
    () => (sym ? isWatched(sym) : false),
    () => false,
  );
}

/**
 * Bundle D / TOCTOU-01. Module-level serializer for read-modify-write paths.
 *
 * `addSymbol("AAPL")` and `addSymbol("MSFT")` fired concurrently used to
 * both `loadWatchlist()` against the *same* baseline, both append, both
 * `saveWatchlist()` — second write clobbers the first. Funnelling every
 * mutator through this queue means the second one waits for the first to
 * publish before re-reading the freshest rows. Order matches call order.
 */
let _writeQueue: Promise<unknown> = Promise.resolve();

function enqueue<T>(task: () => Promise<T>): Promise<T> {
  const next = _writeQueue.then(task, task);
  // Keep the queue chain alive even if a task throws; never block future writes.
  _writeQueue = next.catch(() => undefined);
  return next;
}

export async function addSymbol(symbol: string, label?: string): Promise<WatchlistRow[]> {
  return enqueue(async () => {
    const sym = symbol.trim().toUpperCase();
    if (!sym) return loadWatchlist();
    const rows = await loadWatchlist();
    if (rows.some((r) => r.symbol === sym)) return rows;
    const next = [...rows, { symbol: sym, label, added_at: new Date().toISOString() }];
    await saveWatchlist(next);
    return next;
  });
}

export async function removeSymbol(symbol: string): Promise<WatchlistRow[]> {
  return enqueue(async () => {
    const sym = symbol.trim().toUpperCase();
    const rows = await loadWatchlist();
    const next = rows.filter((r) => r.symbol !== sym);
    if (next.length !== rows.length) await saveWatchlist(next);
    return next;
  });
}

export async function clearWatchlist(): Promise<void> {
  return enqueue(async () => {
    await saveWatchlist([]);
    if (typeof localStorage !== "undefined") localStorage.removeItem(KEY);
  });
}
