import { create } from "zustand";
import { sidecarFetch } from "./sidecar";
import { useStrategyStore } from "./strategy-store";

export interface StrategyFromTextResult {
  spec: Record<string, unknown> | null;
  notes: string[];
  saved_id: string | null;
}

interface AssistantStoreShape {
  text: string;
  result: StrategyFromTextResult | null;
  explanation: string | null;
  /** Shared spinner; kept for back-compat with existing callers. */
  loading: boolean;
  /** H-UI-7 — separate flag so explain + generate can run independently. */
  loadingGenerate: boolean;
  loadingExplain: boolean;
  error: string | null;
  setText: (t: string) => void;
  generate: (save?: boolean) => Promise<StrategyFromTextResult | null>;
  explainStrategy: (id: string) => Promise<string | null>;
}

export const useAssistantStore = create<AssistantStoreShape>((set, get) => ({
  text: "",
  result: null,
  explanation: null,
  loading: false,
  loadingGenerate: false,
  loadingExplain: false,
  error: null,
  setText: (t) => set({ text: t }),
  generate: async (save = false) => {
    // H-UI-7 — track generate independently from explain so the two
    // bottom-pane buttons don't block each other.
    set({ loadingGenerate: true, loading: true, error: null });
    try {
      const r = await sidecarFetch<StrategyFromTextResult>(
        "/api/assistant/strategy-from-text",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: get().text, save }),
        },
      );
      const stillExplaining = get().loadingExplain;
      set({ result: r, loadingGenerate: false, loading: stillExplaining });
      // C9 cross-store invalidation — if the assistant persisted a new
      // strategy, refresh the strategy list so STRA/BOT dropdowns pick it
      // up without a manual reload.
      if (save && r?.saved_id) {
        try {
          await useStrategyStore.getState().loadList();
        } catch {
          // best-effort; surface error only via strategy-store's own state.
        }
      }
      return r;
    } catch (e) {
      const stillExplaining = get().loadingExplain;
      set({
        loadingGenerate: false,
        loading: stillExplaining,
        error: e instanceof Error ? e.message : String(e),
      });
      return null;
    }
  },
  explainStrategy: async (id) => {
    set({ loadingExplain: true, loading: true, error: null });
    try {
      const r = await sidecarFetch<{ explanation: string }>(
        "/api/assistant/explain-strategy",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ strategy_id: id }),
        },
      );
      const stillGenerating = get().loadingGenerate;
      set({
        explanation: r.explanation,
        loadingExplain: false,
        loading: stillGenerating,
      });
      return r.explanation;
    } catch (e) {
      const stillGenerating = get().loadingGenerate;
      set({
        loadingExplain: false,
        loading: stillGenerating,
        error: e instanceof Error ? e.message : String(e),
      });
      return null;
    }
  },
}));
