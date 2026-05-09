/**
 * Frontend wrapper around the Tauri updater commands defined in Round 28.
 *
 * Browser-mode (vite dev / unit tests) returns a stub so the same hook
 * compiles in both shells.
 */
import { invoke, isInTauri } from "./tauri";

export interface UpdateInfo {
  available: boolean;
  current_version: string;
  latest_version: string | null;
  release_date: string | null;
  release_notes: string | null;
  error: string | null;
}

export async function checkForUpdates(): Promise<UpdateInfo> {
  if (!isInTauri()) {
    return {
      available: false,
      current_version: "browser",
      latest_version: null,
      release_date: null,
      release_notes: null,
      error: "Updater is Tauri-only",
    };
  }
  return invoke<UpdateInfo>("check_for_updates");
}

export async function applyUpdate(): Promise<void> {
  if (!isInTauri()) throw new Error("Updater is Tauri-only");
  await invoke("apply_update");
}
