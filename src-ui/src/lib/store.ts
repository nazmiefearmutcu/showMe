/**
 * Top-level UI state. zustand keeps the surface tiny; per-pane state lives
 * inside its own module slice.
 */
import { create } from "zustand";
import type { FunctionEntry } from "./sidecar";

export type SidecarStatus = "booting" | "healthy" | "crashed" | "stopped" | "stub";

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
  sidebarVisible: false,
  setSidecarStatus: (sidecarStatus) => set({ sidecarStatus }),
  setSidecarPort: (sidecarPort) => set({ sidecarPort }),
  setEngineRoot: (engineRoot) => set({ engineRoot }),
  setFunctionIndex: (functionIndex) => set({ functionIndex }),
  togglePalette: (force) =>
    set((state) => ({
      paletteOpen: typeof force === "boolean" ? force : !state.paletteOpen,
    })),
  toggleSidebar: (force) =>
    set((state) => ({
      sidebarVisible: typeof force === "boolean" ? force : !state.sidebarVisible,
    })),
}));
