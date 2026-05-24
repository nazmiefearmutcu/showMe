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
  if (remote && remote.rows) return remote.rows;
  return readLocal().rows;
}

export async function saveWatchlist(rows: WatchlistRow[]): Promise<void> {
  const bundle: Bundle = { rows };
  if (await writeTauri(bundle)) return;
  writeLocal(bundle);
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
