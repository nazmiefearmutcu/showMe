/**
 * Local alerts store — symbol + threshold + direction. Persists via
 * the preset filesystem on Tauri, localStorage on browser dev.
 *
 * Round 23 keeps it client-side only — the sidecar's ShowMe alert engine
 * stays untouched. Round 24+ may duplex against `/api/fn/ALRT` so a
 * single alert lives in both worlds.
 */
import { invoke, isInTauri } from "./tauri";
import { safeReadLocal } from "./safe-storage";

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
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(KEY, JSON.stringify(bundle));
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

export async function addAlert(input: Omit<AlertRow, "id" | "created_at" | "fired_count" | "active">): Promise<AlertRow> {
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
}

export async function deleteAlert(id: string): Promise<AlertRow[]> {
  const rows = await loadAlerts();
  const next = rows.filter((r) => r.id !== id);
  if (next.length !== rows.length) await saveAlerts(next);
  return next;
}

export async function toggleAlert(id: string, active: boolean): Promise<AlertRow[]> {
  const rows = await loadAlerts();
  const next = rows.map((r) => (r.id === id ? { ...r, active } : r));
  await saveAlerts(next);
  return next;
}

export async function recordFire(id: string): Promise<AlertRow[]> {
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
}

export async function clearAlerts(): Promise<void> {
  await saveAlerts([]);
  if (typeof localStorage !== "undefined") localStorage.removeItem(KEY);
}
