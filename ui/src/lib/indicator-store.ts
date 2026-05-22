/**
 * Sub-system F: indicator catalog store.
 * Backed by /api/indicators/catalog. Loaded once; client-side search/filter.
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";

export interface IndicatorParam {
  name: string;
  type: string;
  default: unknown;
  min: number | null;
  max: number | null;
  effect: string;
}

export interface IndicatorEntry {
  id: string;
  display_name: string;
  family: string;
  short_description: string;
  long_description: string;
  formula: string;
  parameters: IndicatorParam[];
  confidence: number;          // 1-10
  confidence_rationale: string;
  suggested_strategy: {
    name?: string;
    summary?: string;
    rules?: string[];
  };
  references: string[];
}

interface IndicatorStoreShape {
  entries: IndicatorEntry[];
  loading: boolean;
  error: string | null;
  selectedId: string | null;

  loadCatalog: () => Promise<void>;
  setSelected: (id: string | null) => void;
  byId: (id: string) => IndicatorEntry | undefined;
  search: (q: string, family?: string) => IndicatorEntry[];
}

export const useIndicatorStore = create<IndicatorStoreShape>((set, get) => ({
  entries: [],
  loading: false,
  error: null,
  selectedId: null,

  loadCatalog: async () => {
    set({ loading: true, error: null });
    try {
      const body = await sidecarFetch<IndicatorEntry[]>("/api/indicators/catalog");
      set({ entries: body, loading: false });
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },

  setSelected: (id) => set({ selectedId: id }),

  byId: (id) => get().entries.find((e) => e.id === id),

  search: (q, family) => {
    const query = q.trim().toLowerCase();
    return get().entries.filter((e) => {
      if (family && e.family !== family) return false;
      if (!query) return true;
      return (
        e.id.toLowerCase().includes(query) ||
        e.display_name.toLowerCase().includes(query) ||
        e.family.toLowerCase().includes(query) ||
        e.short_description.toLowerCase().includes(query)
      );
    });
  },
}));

/** Map confidence to a CSS color variable tier. */
export function confidenceColor(c: number): string {
  if (c >= 9) return "var(--accent-ok)";
  if (c >= 7) return "var(--accent-ok-soft, var(--accent-ok))";
  if (c >= 5) return "var(--accent-warn)";
  if (c >= 3) return "var(--accent-warn-strong, var(--accent-warn))";
  return "var(--accent-err)";
}
