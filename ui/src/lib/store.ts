/**
 * Top-level UI state. zustand keeps the surface tiny; per-pane state lives
 * inside its own module slice.
 */
import { create } from "zustand";
import type { FunctionEntry } from "./sidecar";

export type SidecarStatus = "booting" | "healthy" | "crashed" | "stopped" | "stub";

const SIDEBAR_VISIBLE_KEY = "showme.sidebar.visible.v1";
const SIDEBAR_DESIGN_DEFAULT_KEY = "showme.sidebar.designDefaultHidden.v1";

function readSidebarVisible(): boolean {
  if (typeof localStorage === "undefined") return false;
  if (!localStorage.getItem(SIDEBAR_DESIGN_DEFAULT_KEY)) {
    localStorage.setItem(SIDEBAR_DESIGN_DEFAULT_KEY, "1");
    localStorage.setItem(SIDEBAR_VISIBLE_KEY, "false");
    return false;
  }
  const raw = localStorage.getItem(SIDEBAR_VISIBLE_KEY);
  return raw === null ? false : raw === "true";
}

function writeSidebarVisible(value: boolean): void {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(SIDEBAR_VISIBLE_KEY, String(value));
}

interface AppStateShape {
  sidecarStatus: SidecarStatus;
  sidecarPort: number | null;
  engineRoot: string | null;
  functionIndex: FunctionEntry[];
  paletteOpen: boolean;
  sidebarVisible: boolean;
  setSidecarStatus: (s: SidecarStatus) => void;
  setSidecarPort: (p: number | null) => void;
  setEngineRoot: (r: string | null) => void;
  setFunctionIndex: (idx: FunctionEntry[]) => void;
  togglePalette: (force?: boolean) => void;
  toggleSidebar: (force?: boolean) => void;
}

export const useAppStore = create<AppStateShape>((set) => ({
  sidecarStatus: "booting",
  sidecarPort: null,
  engineRoot: null,
  functionIndex: [],
  paletteOpen: false,
  sidebarVisible: readSidebarVisible(),
  setSidecarStatus: (sidecarStatus) => set({ sidecarStatus }),
  setSidecarPort: (sidecarPort) => set({ sidecarPort }),
  setEngineRoot: (engineRoot) => set({ engineRoot }),
  setFunctionIndex: (functionIndex) => set({ functionIndex }),
  togglePalette: (force) =>
    set((state) => ({
      paletteOpen: typeof force === "boolean" ? force : !state.paletteOpen,
    })),
  toggleSidebar: (force) =>
    set((state) => {
      const sidebarVisible =
        typeof force === "boolean" ? force : !state.sidebarVisible;
      writeSidebarVisible(sidebarVisible);
      return { sidebarVisible };
    }),
}));

// Bundle D / MULTITAB-02. Cross-tab sidebar visibility sync. Toggling the
// sidebar in another tab (or another window) used to leave this tab's
// zustand store out-of-date until the next mount. The `storage` event only
// fires for *cross-tab* writes, so a same-tab `toggleSidebar()` won't
// double-trigger.
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("storage", (event) => {
    if (event.key !== SIDEBAR_VISIBLE_KEY) return;
    useAppStore.setState({ sidebarVisible: readSidebarVisible() });
  });
}
