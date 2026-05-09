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
  if (typeof localStorage === "undefined") return { rows: [] };
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { rows: [] };
    const p = JSON.parse(raw);
    if (Array.isArray(p?.rows)) return p as Bundle;
  } catch {
    /* fall through */
  }
  return { rows: [] };
}

function writeLocal(bundle: Bundle): void {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(KEY, JSON.stringify(bundle));
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

export async function addSymbol(symbol: string, label?: string): Promise<WatchlistRow[]> {
  const sym = symbol.trim().toUpperCase();
  if (!sym) return loadWatchlist();
  const rows = await loadWatchlist();
  if (rows.some((r) => r.symbol === sym)) return rows;
  const next = [...rows, { symbol: sym, label, added_at: new Date().toISOString() }];
  await saveWatchlist(next);
  return next;
}

export async function removeSymbol(symbol: string): Promise<WatchlistRow[]> {
  const sym = symbol.trim().toUpperCase();
  const rows = await loadWatchlist();
  const next = rows.filter((r) => r.symbol !== sym);
  if (next.length !== rows.length) await saveWatchlist(next);
  return next;
}

export async function clearWatchlist(): Promise<void> {
  await saveWatchlist([]);
  if (typeof localStorage !== "undefined") localStorage.removeItem(KEY);
}
