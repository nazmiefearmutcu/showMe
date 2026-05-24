/**
 * Local alerts store — symbol + threshold + direction. Persists via
 * the preset filesystem on Tauri, localStorage on browser dev.
 *
 * Round 23 keeps it client-side only — the sidecar's ShowMe alert engine
 * stays untouched. Round 24+ may duplex against `/api/fn/ALRT` so a
 * single alert lives in both worlds.
 */
import { invoke, isInTauri } from "./tauri";
import { safeReadLocal, safeWriteLocal } from "./safe-storage";

export type AlertDirection = "above" | "below" | "cross_up" | "cross_down";

export interface AlertRow {
  id: string;
  symbol: string;
  field: "price" | "change_pct" | "volume";
  direction: AlertDirection;
  threshold: number;
  note?: string;
  created_at: string;
  fired_count: number;
  last_fired_at?: string;
  active: boolean;
}

const KEY = "showme.alerts";

interface Bundle {
  rows: AlertRow[];
}

function readLocal(): Bundle {
  return safeReadLocal<Bundle>(KEY, { rows: [] }, {
    label: "Alerts",
    validate: (v): v is Bundle =>
      Boolean(v && typeof v === "object" && Array.isArray((v as { rows?: unknown }).rows)),
  });
}

function writeLocal(bundle: Bundle): void {
  // HIGH FIX (audit S14): same QuotaExceeded protection as watchlist.
  safeWriteLocal(KEY, bundle, { label: "Alerts" });
}

async function readTauri(): Promise<Bundle | null> {
  if (!isInTauri()) return null;
  try {
    const v = await invoke<Bundle | null>("read_preset", { name: "alerts" });
    return v ?? null;
  } catch {
    return null;
  }
}

async function writeTauri(bundle: Bundle): Promise<boolean> {
  if (!isInTauri()) return false;
  try {
    await invoke("write_preset", { name: "alerts", content: bundle });
    return true;
  } catch {
    return false;
  }
}

export async function loadAlerts(): Promise<AlertRow[]> {
  const remote = await readTauri();
  if (remote && remote.rows) return remote.rows;
  return readLocal().rows;
}

export async function saveAlerts(rows: AlertRow[]): Promise<void> {
  const bundle: Bundle = { rows };
  if (await writeTauri(bundle)) return;
  writeLocal(bundle);
}

/**
 * Bundle D / TOCTOU-02. Module-level serializer mirrors `watchlist.ts`.
 * Concurrent `addAlert()` / `toggleAlert()` / `recordFire()` calls used to
 * load the same baseline, append, save — last writer wins. Funnel every
 * mutator through one promise chain so reads happen *after* the previous
 * write has been published.
 */
let _writeQueue: Promise<unknown> = Promise.resolve();

function enqueue<T>(task: () => Promise<T>): Promise<T> {
  const next = _writeQueue.then(task, task);
  _writeQueue = next.catch(() => undefined);
  return next;
}

/**
 * Round 24 HIGH 9 — per-alert toggle guard for the on/off dot. A rapid
 * double-tap could otherwise enqueue (off, on) then (on, off) back-to-back;
 * if the second pair started reading state before the first pair's write
 * landed, the visible dot would flicker and the value could persist as
 * the opposite of the user's last intent.
 *
 * Note: addAlert / deleteAlert do NOT take a global single-flight flag
 * because legitimately-concurrent calls from different code paths (e.g.
 * preset migration adding 10 alerts via Promise.all) must succeed. The
 * `_writeQueue` already serializes the writes safely; UI-level form
 * double-fire is handled by the ALRT pane's local `adding` state.
 */
const _togglingAlerts = new Set<string>();

export function isAlertToggling(id: string): boolean {
  return _togglingAlerts.has(id);
}

/**
 * Round 24 — kept for API symmetry but always returns false. The form
 * disables itself via local React state; the store doesn't need to know.
 * Re-exported so callers can switch to a true global flag in future
 * without re-importing.
 */
export function isAddingAlert(): boolean {
  return false;
}

export async function addAlert(
  input: Omit<AlertRow, "id" | "created_at" | "fired_count" | "active">,
): Promise<AlertRow> {
  return enqueue(async () => {
    const row: AlertRow = {
      ...input,
      id: `a-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
      created_at: new Date().toISOString(),
      fired_count: 0,
      active: true,
    };
    const rows = await loadAlerts();
    await saveAlerts([row, ...rows]);
    return row;
  });
}

export async function deleteAlert(id: string): Promise<AlertRow[]> {
  return enqueue(async () => {
    const rows = await loadAlerts();
    const next = rows.filter((r) => r.id !== id);
    if (next.length !== rows.length) await saveAlerts(next);
    return next;
  });
}

export async function toggleAlert(id: string, active: boolean): Promise<AlertRow[]> {
  // Round 24 HIGH — per-alert in-flight guard. Without this, a rapid
  // double-tap on the dot enqueued (off, on) then (on, off) back-to-back,
  // racing the load → map → save cycle and producing visible dot flicker
  // before settling on the wrong value.
  if (_togglingAlerts.has(id)) return await loadAlerts();
  _togglingAlerts.add(id);
  try {
    return await enqueue(async () => {
      const rows = await loadAlerts();
      const next = rows.map((r) => (r.id === id ? { ...r, active } : r));
      await saveAlerts(next);
      return next;
    });
  } finally {
    _togglingAlerts.delete(id);
  }
}

export async function recordFire(id: string): Promise<AlertRow[]> {
  return enqueue(async () => {
    const rows = await loadAlerts();
    const next = rows.map((r) =>
      r.id === id
        ? {
            ...r,
            fired_count: r.fired_count + 1,
            last_fired_at: new Date().toISOString(),
          }
        : r,
    );
    await saveAlerts(next);
    return next;
  });
}

export async function clearAlerts(): Promise<void> {
  return enqueue(async () => {
    await saveAlerts([]);
    if (typeof localStorage !== "undefined") localStorage.removeItem(KEY);
  });
}
