/**
 * Layout presets — async save/load/delete with two backends:
 *
 *   • Tauri shell — `~/Library/Application Support/showMe/state/
 *     layout-presets/<name>.json` via Tauri commands. Survives app
 *     reinstalls per user, accessible from any window.
 *
 *   • Browser dev / vite preview — falls back to localStorage so designers
 *     don't need a Tauri shell to inspect the dropdown.
 *
 * Round 17+ may add cloud sync (Notion / iCloud Drive) by adding a third
 * backend without touching call sites.
 */
import { invoke, isInTauri } from "./tauri";
import {
  loadWorkspace,
  serializeWorkspace,
  type SerializedWorkspace,
} from "./workspace";

const KEY = "showme.layout-presets";

interface PresetEntry {
  name: string;
  state: SerializedWorkspace;
}

export interface PresetSummary {
  name: string;
  savedAt: string;
}

interface RustSummary {
  name: string;
  saved_at: string;
}

interface Bundle {
  presets: PresetEntry[];
}

const usingTauri = (): boolean => isInTauri();

// ── Browser fallback ─────────────────────────────────────────────────────

function readLS(): Bundle {
  if (typeof localStorage === "undefined") return { presets: [] };
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { presets: [] };
    const parsed = JSON.parse(raw);
    if (!parsed || !Array.isArray(parsed.presets)) return { presets: [] };
    return parsed as Bundle;
  } catch {
    return { presets: [] };
  }
}

function writeLS(bundle: Bundle): void {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(KEY, JSON.stringify(bundle));
}

// ── Public API ───────────────────────────────────────────────────────────

export async function listPresets(): Promise<PresetSummary[]> {
  if (usingTauri()) {
    try {
      const items = await invoke<RustSummary[]>("list_presets");
      return items
        .map((p) => ({ name: p.name, savedAt: p.saved_at }))
        .sort((a, b) => a.name.localeCompare(b.name));
    } catch {
      return [];
    }
  }
  return readLS()
    .presets.map((p) => ({ name: p.name, savedAt: p.state.savedAt }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export async function savePreset(name: string): Promise<PresetSummary> {
  const trimmed = name.trim();
  if (!trimmed) throw new Error("preset name required");
  const state = serializeWorkspace();

  if (usingTauri()) {
    await invoke("write_preset", { name: trimmed, content: state });
    return { name: trimmed, savedAt: state.savedAt };
  }
  const bundle = readLS();
  const idx = bundle.presets.findIndex((p) => p.name === trimmed);
  const entry: PresetEntry = { name: trimmed, state };
  if (idx === -1) bundle.presets.push(entry);
  else bundle.presets[idx] = entry;
  writeLS(bundle);
  return { name: trimmed, savedAt: state.savedAt };
}

export async function loadPreset(name: string): Promise<boolean> {
  if (usingTauri()) {
    try {
      const state = await invoke<SerializedWorkspace>("read_preset", { name });
      if (!state) return false;
      loadWorkspace(state);
      return true;
    } catch {
      return false;
    }
  }
  const entry = readLS().presets.find((p) => p.name === name);
  if (!entry) return false;
  loadWorkspace(entry.state);
  return true;
}

export async function deletePreset(name: string): Promise<boolean> {
  if (usingTauri()) {
    try {
      return await invoke<boolean>("delete_preset", { name });
    } catch {
      return false;
    }
  }
  const bundle = readLS();
  const before = bundle.presets.length;
  bundle.presets = bundle.presets.filter((p) => p.name !== name);
  if (bundle.presets.length === before) return false;
  writeLS(bundle);
  return true;
}

export function clearPresets(): void {
  if (typeof localStorage !== "undefined") localStorage.removeItem(KEY);
}
