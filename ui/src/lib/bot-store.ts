/**
 * Sub-system D UI store: bot CRUD + enable/disable + signal log.
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";

export interface SignalEntry {
  bar_index: number;
  bar_time: string;
  kind: "entry" | "exit";
  price: number;
  action: "placed" | "shadow" | "skipped";
  order_id?: string | null;
  error?: string | null;
  timestamp?: string;
}

export interface BotRecord {
  id: string;
  strategy_id: string;
  credential_id: string;
  exchange_id: string;
  symbol: string;
  timeframe: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
  tick_interval_seconds: number;
  mode: "shadow" | "live";
  enabled: boolean;
  last_processed_event: SignalEntry | null;
  signal_log: SignalEntry[];
  created_at: string;
  updated_at: string;
}

export interface BotMeta {
  id: string;
  strategy_id: string;
  credential_id: string;
  exchange_id: string;
  symbol: string;
  timeframe: string;
  mode: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

const _BLANK_BOT = (): Omit<BotRecord, "id" | "created_at" | "updated_at" | "last_processed_event" | "signal_log" | "enabled" | "mode"> => ({
  strategy_id: "",
  credential_id: "",
  exchange_id: "",
  symbol: "",
  timeframe: "1h",
  tick_interval_seconds: 60,
});

interface BotStoreShape {
  bots: BotMeta[];
  draft: Partial<BotRecord> | null;
  draftIsNew: boolean;
  dirty: boolean;
  loading: boolean;
  error: string | null;

  loadList: () => Promise<void>;
  openNew: () => void;
  openExisting: (id: string) => Promise<void>;
  setDraftField: <K extends keyof BotRecord>(k: K, v: BotRecord[K]) => void;
  save: () => Promise<BotRecord | null>;
  remove: (id: string) => Promise<boolean>;
  enable: (id: string, confirmLabel?: string) => Promise<BotRecord | null>;
  disable: (id: string) => Promise<BotRecord | null>;
}

export const useBotStore = create<BotStoreShape>((set, get) => ({
  bots: [],
  draft: null,
  draftIsNew: false,
  dirty: false,
  loading: false,
  error: null,

  loadList: async () => {
    set({ loading: true, error: null });
    try {
      const body = await sidecarFetch<{ records: BotMeta[] }>("/api/bots");
      set({ bots: body.records, loading: false });
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },

  openNew: () => set({
    draft: { ..._BLANK_BOT(), mode: "shadow", enabled: false, signal_log: [], last_processed_event: null },
    draftIsNew: true, dirty: false,
  }),

  openExisting: async (id) => {
    set({ loading: true, error: null });
    try {
      const rec = await sidecarFetch<BotRecord>(`/api/bots/${id}`);
      set({ draft: rec, draftIsNew: false, dirty: false, loading: false });
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
        const saved = await sidecarFetch<BotRecord>("/api/bots", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cur),
        });
        set({ draft: saved, draftIsNew: false, dirty: false, loading: false });
        await get().loadList();
        return saved;
      } else {
        const saved = await sidecarFetch<BotRecord>(`/api/bots/${cur.id}`, {
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
      await sidecarFetch(`/api/bots/${id}`, { method: "DELETE" });
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

  enable: async (id, confirmLabel) => {
    try {
      const rec = await sidecarFetch<BotRecord>(`/api/bots/${id}/enable`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(confirmLabel !== undefined ? { confirm_account_label: confirmLabel } : {}),
      });
      const draft = get().draft;
      if (draft && draft.id === id) set({ draft: rec });
      await get().loadList();
      return rec;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      return null;
    }
  },

  disable: async (id) => {
    try {
      const rec = await sidecarFetch<BotRecord>(`/api/bots/${id}/disable`, { method: "POST" });
      const draft = get().draft;
      if (draft && draft.id === id) set({ draft: rec });
      await get().loadList();
      return rec;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      return null;
    }
  },
}));
