import { create } from "zustand";
import { sidecarFetch } from "./sidecar";

export interface StrategyFromTextResult {
  spec: Record<string, unknown> | null;
  notes: string[];
  saved_id: string | null;
}

interface AssistantStoreShape {
  text: string;
  result: StrategyFromTextResult | null;
  explanation: string | null;
  loading: boolean;
  error: string | null;
  setText: (t: string) => void;
  generate: (save?: boolean) => Promise<StrategyFromTextResult | null>;
  explainStrategy: (id: string) => Promise<string | null>;
}

export const useAssistantStore = create<AssistantStoreShape>((set, get) => ({
  text: "", result: null, explanation: null, loading: false, error: null,
  setText: (t) => set({ text: t }),
  generate: async (save = false) => {
    set({ loading: true, error: null });
    try {
      const r = await sidecarFetch<StrategyFromTextResult>(
        "/api/assistant/strategy-from-text",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: get().text, save }),
        },
      );
      set({ result: r, loading: false });
      return r;
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
      return null;
    }
  },
  explainStrategy: async (id) => {
    set({ loading: true, error: null });
    try {
      const r = await sidecarFetch<{ explanation: string }>(
        "/api/assistant/explain-strategy",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ strategy_id: id }),
        },
      );
      set({ explanation: r.explanation, loading: false });
      return r.explanation;
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
      return null;
    }
  },
}));
