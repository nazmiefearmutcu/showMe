/**
 * Sub-system E UI store: list strategies, edit/save/preview.
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";

export interface IndicatorRef {
  alias: string;
  id: string;
  params: Record<string, unknown>;
}

export interface Rule {
  kind: "crosses_above" | "crosses_below" | "greater_than" | "less_than" | "equals_approximately";
  left: string;
  right: string;
  tolerance?: number | null;
}

export interface Position {
  side: "long" | "short";
  sizing_kind: "fixed_quote" | "fixed_base" | "risk_pct";
  sizing_value: number;
  stop_loss_pct?: number | null;
  take_profit_pct?: number | null;
}

export interface AssetFilter {
  exchanges?: string[] | null;
  symbols?: string[] | null;
  asset_classes?: string[] | null;
}

export interface StrategySpec {
  id: string;
  name: string;
  description: string;
  version: number;
  asset_filter: AssetFilter;
  timeframe: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
  indicators: IndicatorRef[];
  entry_rules: Rule[];
  entry_logic: "all" | "any";
  exit_rules: Rule[];
  exit_logic: "all" | "any";
  position: Position;
  created_at: string;
  updated_at: string;
}

export interface StrategyMeta {
  id: string;
  name: string;
  description: string;
  timeframe: string;
  created_at: string;
  updated_at: string;
}

export interface PreviewEvent {
  bar_index: number;
  bar_time: string;
  kind: "entry" | "exit";
  price: number;
  details: Record<string, unknown>;
}

export interface PreviewResult {
  strategy_id: string;
  symbol: string;
  timeframe: string;
  bars: number;
  events: PreviewEvent[];
  source: string;
}

const _BLANK_SPEC = (): Omit<StrategySpec, "id" | "created_at" | "updated_at"> => ({
  name: "",
  description: "",
  version: 1,
  asset_filter: {},
  timeframe: "1h",
  indicators: [],
  entry_rules: [],
  entry_logic: "all",
  exit_rules: [],
  exit_logic: "any",
  position: { side: "long", sizing_kind: "fixed_quote", sizing_value: 100 },
});

interface StrategyStoreShape {
  strategies: StrategyMeta[];
  draft: Partial<StrategySpec> | null;
  draftIsNew: boolean;
  dirty: boolean;
  loading: boolean;
  error: string | null;
  lastPreview: PreviewResult | null;

  loadList: () => Promise<void>;
  openNew: () => void;
  openExisting: (id: string) => Promise<void>;
  setDraftField: <K extends keyof StrategySpec>(k: K, v: StrategySpec[K]) => void;
  save: () => Promise<StrategySpec | null>;
  remove: (id: string) => Promise<boolean>;
  preview: (id: string) => Promise<PreviewResult | null>;
}

export const useStrategyStore = create<StrategyStoreShape>((set, get) => ({
  strategies: [],
  draft: null,
  draftIsNew: false,
  dirty: false,
  loading: false,
  error: null,
  lastPreview: null,

  loadList: async () => {
    set({ loading: true, error: null });
    try {
      const body = await sidecarFetch<{ records: StrategyMeta[] }>("/api/strategies");
      set({ strategies: body.records, loading: false });
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },

  openNew: () => set({ draft: _BLANK_SPEC(), draftIsNew: true, dirty: false, lastPreview: null }),

  openExisting: async (id) => {
    set({ loading: true, error: null });
    try {
      const spec = await sidecarFetch<StrategySpec>(`/api/strategies/${id}`);
      set({ draft: spec, draftIsNew: false, dirty: false, loading: false, lastPreview: null });
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },

  setDraftField: (k, v) => {
    const cur = get().draft;
    if (!cur) return;
    set({ draft: { ...cur, [k]: v }, dirty: true });
  },

  save: async () => {
    const cur = get().draft;
    if (!cur) return null;
    set({ loading: true, error: null });
    try {
      if (get().draftIsNew || !cur.id) {
        const saved = await sidecarFetch<StrategySpec>("/api/strategies", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cur),
        });
        set({ draft: saved, draftIsNew: false, dirty: false, loading: false });
        await get().loadList();
        return saved;
      } else {
        const saved = await sidecarFetch<StrategySpec>(`/api/strategies/${cur.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cur),
        });
        set({ draft: saved, dirty: false, loading: false });
        await get().loadList();
        return saved;
      }
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
      return null;
    }
  },

  remove: async (id) => {
    try {
      await sidecarFetch(`/api/strategies/${id}`, { method: "DELETE" });
      const draft = get().draft;
      if (draft && draft.id === id) {
        set({ draft: null, draftIsNew: false, dirty: false });
      }
      await get().loadList();
      return true;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      return false;
    }
  },

  preview: async (id) => {
    try {
      const result = await sidecarFetch<PreviewResult>(
        `/api/strategies/${id}/preview`, { method: "POST" },
      );
      set({ lastPreview: result });
      return result;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      return null;
    }
  },
}));
