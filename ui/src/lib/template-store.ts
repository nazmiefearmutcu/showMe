/**
 * Sub-system G UI store: template catalog + instantiation.
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";
import type { StrategySpec } from "./strategy-store";
import { useStrategyStore } from "./strategy-store";

export interface TemplateEntry {
  id: string;
  name: string;
  description: string;
  uses_indicators: string[];
  recommended_timeframe: string;
  recommended_symbols: string[];
  applicability: string;
  natural_language_explanation: string;
  math: string;
  spec_template: Record<string, unknown>;
  family: string;
}

export interface InstantiateResult {
  template_id: string;
  strategy: StrategySpec;
}

interface TemplateStoreShape {
  entries: TemplateEntry[];
  selectedId: string | null;
  loading: boolean;
  /**
   * Round 24 CRITICAL — concurrent-instantiate guard. The TMPL modal's
   * "Oluştur" button has `disabled={creating}` but a hardware double-click
   * still fired two POST /api/templates/{id}/instantiate before React
   * paint. Each call persists a new strategy → duplicates in STRA/BOT
   * dropdowns. This flag is the canonical seal; the modal-side `creating`
   * is decorative.
   */
  instantiating: boolean;
  error: string | null;

  loadCatalog: () => Promise<void>;
  setSelected: (id: string | null) => void;
  byId: (id: string) => TemplateEntry | undefined;
  instantiate: (id: string, name?: string, symbol?: string) => Promise<InstantiateResult | null>;
}

export const useTemplateStore = create<TemplateStoreShape>((set, get) => ({
  entries: [],
  selectedId: null,
  loading: false,
  instantiating: false,
  error: null,

  loadCatalog: async () => {
    set({ loading: true, error: null });
    try {
      const body = await sidecarFetch<TemplateEntry[]>("/api/templates");
      set({ entries: body, loading: false });
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },

  setSelected: (id) => set({ selectedId: id }),

  byId: (id) => get().entries.find((e) => e.id === id),

  instantiate: async (id, name, symbol) => {
    // Round 24 CRITICAL — see `instantiating` field docstring.
    if (get().instantiating) return null;
    set({ instantiating: true });
    try {
      const result = await sidecarFetch<InstantiateResult>(
        `/api/templates/${id}/instantiate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...(name ? { name } : {}),
            ...(symbol ? { symbol } : {}),
          }),
        },
      );
      // C9 cross-store invalidation — instantiate persists a new strategy
      // server-side, so refresh STRA/BOT dropdowns immediately.
      try {
        await useStrategyStore.getState().loadList();
      } catch {
        // best-effort; strategy-store surfaces its own error.
      }
      return result;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      return null;
    } finally {
      set({ instantiating: false });
    }
  },
}));
