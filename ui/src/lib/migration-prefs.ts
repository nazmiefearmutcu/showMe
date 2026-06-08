/**
 * Migration-pane persistence helpers (UI-INT-PREF P3).
 *
 * The State-importer used to forget the engine path + mode on every reload —
 * the user had to retype the path each session. These tiny helpers round-trip
 * both to localStorage under explicit, versioned keys so a remount restores
 * the last-used values. A persisted path takes precedence over the
 * auto-fill-from-`engineRoot` default; if nothing was persisted we fall back
 * to that store-provided value.
 */

export const MIGRATION_PATH_KEY = "showme.migration.lastPath.v1";
export const MIGRATION_MODE_KEY = "showme.migration.mode.v1";

export type MigrationMode = "read-only" | "writable";

export function readMigrationPath(): string | null {
  if (typeof localStorage === "undefined") return null;
  try {
    const v = localStorage.getItem(MIGRATION_PATH_KEY);
    return v && v.trim() ? v : null;
  } catch {
    return null;
  }
}

export function writeMigrationPath(path: string): void {
  if (typeof localStorage === "undefined") return;
  try {
    if (path.trim()) localStorage.setItem(MIGRATION_PATH_KEY, path);
    else localStorage.removeItem(MIGRATION_PATH_KEY);
  } catch {
    // ignore quota
  }
}

export function readMigrationWritable(): boolean | null {
  if (typeof localStorage === "undefined") return null;
  try {
    const v = localStorage.getItem(MIGRATION_MODE_KEY);
    if (v === "writable") return true;
    if (v === "read-only") return false;
    return null;
  } catch {
    return null;
  }
}

export function writeMigrationWritable(writable: boolean): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(MIGRATION_MODE_KEY, writable ? "writable" : "read-only");
  } catch {
    // ignore quota
  }
}
