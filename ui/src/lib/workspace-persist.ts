/**
 * Workspace tree persistence.
 *
 * Serializes the live tree on every mutation (debounced) and restores it
 * on app boot. Tauri shell uses
 * `~/Library/Application Support/showMe/state/workspace.json`; browser
 * mode falls back to `localStorage["showme.workspace"]`.
 */
import {
  loadWorkspace,
  serializeWorkspace,
  useWorkspace,
  type SerializedWorkspace,
} from "./workspace";
import { invoke, isInTauri } from "./tauri";

const KEY = "showme.workspace";
const DEBOUNCE_MS = 400;

let timer: ReturnType<typeof setTimeout> | null = null;

async function currentLabel(): Promise<string | undefined> {
  if (!isInTauri()) return undefined;
  try {
    const win = await import("@tauri-apps/api/window");
    return win.getCurrentWindow().label;
  } catch {
    return undefined;
  }
}

function lsKey(label?: string): string {
  return label ? `${KEY}.${label}` : KEY;
}

async function persist(state: SerializedWorkspace): Promise<void> {
  const label = await currentLabel();
  if (isInTauri()) {
    try {
      await invoke("save_workspace", { content: state, label });
      return;
    } catch (err) {
      console.warn("save_workspace failed; falling back to localStorage", err);
    }
  }
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(lsKey(label), JSON.stringify(state));
  }
}

async function readPersisted(): Promise<SerializedWorkspace | null> {
  const label = await currentLabel();
  if (isInTauri()) {
    try {
      const raw = await invoke<SerializedWorkspace | null>("load_workspace", { label });
      if (raw) return raw;
    } catch {
      /* fall through */
    }
  }
  if (typeof localStorage === "undefined") return null;
  try {
    // Prefer per-window key, fall back to legacy global key.
    const text =
      localStorage.getItem(lsKey(label)) ?? localStorage.getItem(KEY);
    if (!text) return null;
    return JSON.parse(text) as SerializedWorkspace;
  } catch {
    return null;
  }
}

/**
 * Wait for the Tauri shell's `shell:ready` event before doing the first
 * disk read. Resolves immediately in browser-mode (no shell) and falls
 * back after a short timeout if the event never fires (older Tauri
 * builds, dev quirks).
 */
async function waitForShellReady(timeoutMs = 1500): Promise<void> {
  if (!isInTauri()) return;
  let listenFn: typeof import("@tauri-apps/api/event").listen | null = null;
  try {
    const mod = await import("@tauri-apps/api/event");
    listenFn = mod.listen;
  } catch {
    return;
  }
  if (!listenFn) return;
  await new Promise<void>((resolve) => {
    let done = false;
    const finish = () => {
      if (!done) {
        done = true;
        resolve();
      }
    };
    const timer = setTimeout(finish, timeoutMs);
    listenFn!("shell:ready", () => {
      clearTimeout(timer);
      finish();
    }).then((unlisten) => {
      // If the event already fired before we subscribed, the timeout
      // closes the gap; otherwise this resolves on the next tick.
      if (done) unlisten();
    });
  });
}

/** Hydrate the workspace store from disk. Idempotent — safe to call once. */
export async function restoreWorkspace(): Promise<boolean> {
  await waitForShellReady();
  const state = await readPersisted();
  if (!state) return false;
  loadWorkspace(state);
  return true;
}

/** Subscribe the store to disk-write on change (debounced). Returns disposer. */
export function startWorkspaceAutosave(): () => void {
  return useWorkspace.subscribe(() => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      persist(serializeWorkspace()).catch(() => {});
    }, DEBOUNCE_MS);
  });
}

/** Used by tests — fire the persisted save immediately. */
export async function flushWorkspaceAutosave(): Promise<void> {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  await persist(serializeWorkspace());
}
