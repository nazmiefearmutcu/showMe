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
  type WorkspaceNode,
} from "./workspace";
import { invoke, isInTauri } from "./tauri";

const KEY = "showme.workspace";
const DEBOUNCE_MS = 400;

/**
 * Cutoff for the S11 poisoned-workspace migration. Any persisted state
 * older than this *and* matching the structural signature of the S09
 * markets-overview cold-boot default is treated as auto-generated junk
 * (the user never explicitly chose that layout — S09 silently planted
 * it on first launch). Anything saved on/after this instant is trusted
 * because, post-S10, the only way to produce that layout is an explicit
 * `loadBuiltinPreset("markets-overview")` invocation.
 *
 * S10 deploy was 2026-05-20T22:42 local (UTC+3 = 19:42Z). Cutoff is
 * pinned a few minutes after that to cover the build/deploy/launch
 * window. Persisted files captured during the recovery (e.g. the
 * /tmp/showme-workspace-backup-s10.json sample, savedAt 19:34:42Z) are
 * cleanly pre-cutoff.
 */
const POISONED_LAYOUT_CUTOFF_ISO = "2026-05-20T20:00:00Z";

/**
 * Structural detector for the S09 markets-overview cold-boot default
 * and its routeToTarget(welcome)→HOME mutation variant. Returns true
 * only when the tree EXACTLY matches one of two shapes:
 *
 *   ╔══════════╤═══════════╗      ╔══════════╤═══════════╗
 *   ║ DES@APPL │  GP@AAPL  ║  OR  ║   HOME   │  GP@AAPL  ║
 *   ╠══════════╪═══════════╣      ╠══════════╪═══════════╣
 *   ║   WEI    │    TOP    ║      ║   WEI    │    TOP    ║
 *   ╚══════════╧═══════════╝      ╚══════════╧═══════════╝
 *
 * Anything that differs structurally (extra leaves, different codes in
 * the corners, custom symbols other than AAPL on the GP slot, sizes
 * deviating from the [0.55, 0.45] default, link groups present) is a
 * real user customization and is left alone.
 */
export function isPoisonedMarketsOverviewLayout(tree: WorkspaceNode): boolean {
  if (tree.kind !== "split") return false;
  if (tree.direction !== "v") return false;
  if (tree.children.length !== 2) return false;
  if (
    !tree.sizes ||
    tree.sizes.length !== 2 ||
    Math.abs(tree.sizes[0] - 0.55) > 0.001 ||
    Math.abs(tree.sizes[1] - 0.45) > 0.001
  ) {
    return false;
  }
  const [top, bottom] = tree.children;
  if (top.kind !== "split" || top.direction !== "h" || top.children.length !== 2) return false;
  if (bottom.kind !== "split" || bottom.direction !== "h" || bottom.children.length !== 2) return false;
  const [tl, tr] = top.children;
  const [bl, br] = bottom.children;
  if (tl.kind !== "leaf" || tr.kind !== "leaf" || bl.kind !== "leaf" || br.kind !== "leaf") {
    return false;
  }
  // Top-left: either the original S09 default (DES@AAPL) or its
  // welcome-route-mutated variant (HOME). Anything else means the user
  // swapped the corner manually — preserve.
  if (tl.code !== "DES" && tl.code !== "HOME") return false;
  if (tl.code === "DES" && tl.symbol !== "AAPL") return false;
  // Top-right: GP@AAPL (the cold-boot focus chart).
  if (tr.code !== "GP" || tr.symbol !== "AAPL") return false;
  // Bottom row: WEI + TOP, no symbols (no SymbolBar input on these).
  if (bl.code !== "WEI" || bl.symbol) return false;
  if (br.code !== "TOP" || br.symbol) return false;
  // No link-group customization — that would be a real user choice.
  if (tl.linkGroup || tr.linkGroup || bl.linkGroup || br.linkGroup) return false;
  return true;
}

/**
 * Returns true if the persisted state is old enough to qualify for the
 * S11 cleanup. Missing/unparseable `savedAt` is treated as pre-cutoff
 * (it's almost certainly legacy junk).
 */
export function isPersistedStatePreS11Cutoff(state: SerializedWorkspace): boolean {
  if (!state.savedAt) return true;
  const ts = Date.parse(state.savedAt);
  if (!Number.isFinite(ts)) return true;
  return ts < Date.parse(POISONED_LAYOUT_CUTOFF_ISO);
}

/**
 * Migration decision returned by `applyWorkspaceMigrations`. The caller
 * (restoreWorkspace) acts on it without further policy.
 *
 *  "restore"    — load the state as-is (no migration needed)
 *  "skip"       — drop the persisted state; the in-memory default wins
 *  "skip-flush" — drop the persisted state AND rewrite the file with
 *                 the clean default so the next launch reads it back
 *                 cleanly (idempotent self-heal)
 */
export type WorkspaceMigrationOutcome = "restore" | "skip" | "skip-flush";

/**
 * Pure, sync migration policy. Tests exercise this without touching the
 * Zustand store or the Tauri/localStorage backing.
 */
export function applyWorkspaceMigrations(
  state: SerializedWorkspace,
): WorkspaceMigrationOutcome {
  if (
    isPersistedStatePreS11Cutoff(state) &&
    isPoisonedMarketsOverviewLayout(state.tree)
  ) {
    return "skip-flush";
  }
  return "restore";
}

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
  // S11 self-healing migration: detect S09-era poisoned layouts
  // (markets-overview default planted silently, or its HOME-mutated
  // variant after S10's routeToTarget(welcome) swapped DES→HOME) and
  // reset them to the clean single-HOME dashboard. The decision is
  // pure so tests can exercise it without the Tauri backing.
  const outcome = applyWorkspaceMigrations(state);
  if (outcome === "skip-flush") {
    // Write the clean in-memory default (single HOME leaf) back to disk
    // so the next launch sees a healed file even if the user quits
    // before any other mutation triggers the autosave debounce.
    try {
      await persist(serializeWorkspace());
    } catch (err) {
      console.warn("S11 migration flush failed; in-memory default still wins", err);
    }
    return false;
  }
  if (outcome === "skip") return false;
  loadWorkspace(state);
  return true;
}

/** Subscribe the store to disk-write on change (debounced). Returns disposer. */
export function startWorkspaceAutosave(): () => void {
  const unsubStore = useWorkspace.subscribe(() => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      persist(serializeWorkspace()).catch(() => {});
    }, DEBOUNCE_MS);
  });

  // Flush-on-close: the 400 ms debounce silently drops the user's last edit
  // when they hit ⌘W or quit immediately after a mutation. Wire both the
  // browser-native `beforeunload` and (when running inside Tauri) the
  // `tauri://close-requested` event to flush before teardown.
  // See FUNC-04 P0 in the quality audit.
  const browserFlush = () => {
    void flushWorkspaceAutosave();
  };
  if (typeof window !== "undefined") {
    window.addEventListener("beforeunload", browserFlush);
  }

  // Tauri close-requested listener is async; capture the unlisten handle so
  // we can detach in the disposer. Browser-mode (`isInTauri()` false) skips
  // this entirely — the dynamic import would throw otherwise.
  let unlistenTauri: (() => void) | null = null;
  if (isInTauri()) {
    void import("@tauri-apps/api/window")
      .then((mod) => mod.getCurrentWindow().listen("tauri://close-requested", browserFlush))
      .then((unlisten) => {
        unlistenTauri = unlisten;
      })
      .catch((err) => {
        console.warn("workspace flush: tauri close-requested listen failed", err);
      });
  }

  return () => {
    unsubStore();
    if (typeof window !== "undefined") {
      window.removeEventListener("beforeunload", browserFlush);
    }
    if (unlistenTauri) {
      try {
        unlistenTauri();
      } catch {
        /* no-op */
      }
      unlistenTauri = null;
    }
  };
}

/** Used by tests — fire the persisted save immediately. */
export async function flushWorkspaceAutosave(): Promise<void> {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  await persist(serializeWorkspace());
}
